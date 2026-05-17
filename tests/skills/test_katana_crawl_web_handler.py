"""Unit tests for the Katana crawl skill."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from secbot.skills._shared.sandbox import SandboxResult
from secbot.skills.types import InvalidSkillArg, SkillBinaryMissing, SkillResult, SkillTimeout


def _install_katana_fake(
    monkeypatch, mod, *, capture_argv: list[list[str]], urls: list[str]
) -> None:
    monkeypatch.setattr(
        mod,
        "_resolve_katana_binary",
        lambda cli: ("katana", cli),
        raising=True,
    )

    async def _fake(**kwargs):
        argv = list(kwargs.get("args", []))
        capture_argv.append(argv)
        raw = kwargs.get("raw_log_path")
        if raw is not None:
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
            Path(raw).write_bytes(b"katana mocked\n")
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
        return SandboxResult(exit_code=0, raw_log_path=raw, captured=None)

    monkeypatch.setattr(mod, "run_command", _fake, raising=True)


async def test_katana_crawl_web_happy_classifies_and_filters(
    handler_loader, make_ctx, monkeypatch
):
    mod = handler_loader("katana-crawl-web")
    captured: list[list[str]] = []
    urls = [
        "https://example.com/api/run?cmd=id",
        "https://example.com/api/run?cmd=id#dup-fragment",
        "https://example.com/static/app.js",
        "https://example.com/api/user?id=42&theme=dark",
        "https://example.com/export?file=report.pdf",
        "https://example.com/fetch?url=https%3A%2F%2Fmetadata.internal%2F",
        "https://example.com/import?data=%7B%22%40type%22%3A%22com.sun.rowset.JdbcRowSetImpl%22%7D",
        "https://example.com/api/xml?xml=%3C%21DOCTYPE%20foo%3E",
        "https://example.com/admin/login",
        "https://example.com/export?file=report.pdf&lang=zh",
        "https://example.com/region/list?lang=zh&sort=name",
        "https://example.com/api/region-list?lang=zh",
        "https://example.com/prefs?color=red&theme=dark",
        "https://evil.example.net/api/run?cmd=id",
        "https://example.com:99999/bad?cmd=id",
    ]
    _install_katana_fake(monkeypatch, mod, capture_argv=captured, urls=urls)

    ctx = make_ctx()
    res = await mod.run(
        {
            "target": "https://example.com",
            "depth": 5,
            "max_candidates": 20,
            "timeout_sec": 60,
        },
        ctx,
    )

    assert isinstance(res, SkillResult)
    summary = res.summary
    assert summary["total_urls"] == len(urls)
    assert summary["deduped_urls"] == len(urls) - 2
    assert summary["candidate_count"] == 8
    assert Path(summary["raw_urls_path"]).exists()
    assert Path(res.raw_log_path or "").exists()

    by_url = {candidate["url"]: candidate for candidate in summary["candidates"]}
    assert "https://example.com/static/app.js" not in by_url
    assert "https://example.com/region/list?lang=zh&sort=name" not in by_url
    assert "https://example.com/api/region-list?lang=zh" not in by_url
    assert "https://example.com/prefs?color=red&theme=dark" not in by_url
    assert "https://evil.example.net/api/run?cmd=id" not in by_url

    cmd = by_url["https://example.com/api/run?cmd=id"]
    assert cmd["priority"] == "critical"
    assert cmd["parameters"] == [{"name": "cmd", "risk": "critical"}]
    assert "command_injection" in cmd["guessed_vulnerabilities"]

    user = by_url["https://example.com/api/user?id=42&theme=dark"]
    assert user["parameters"] == [
        {"name": "id", "risk": "high"},
        {"name": "theme", "risk": "skipped"},
    ]
    assert "idor" in user["guessed_vulnerabilities"]

    exported = by_url["https://example.com/export?file=report.pdf"]
    assert "path_traversal" in exported["guessed_vulnerabilities"]
    assert exported["priority"] == "critical"

    exported_with_lang = by_url["https://example.com/export?file=report.pdf&lang=zh"]
    assert exported_with_lang["parameters"] == [
        {"name": "file", "risk": "critical"},
        {"name": "lang", "risk": "skipped"},
    ]

    fetch = by_url["https://example.com/fetch?url=https%3A%2F%2Fmetadata.internal%2F"]
    assert "ssrf" in fetch["guessed_vulnerabilities"]

    deser = by_url[
        "https://example.com/import?data=%7B%22%40type%22%3A%22com.sun.rowset.JdbcRowSetImpl%22%7D"
    ]
    assert "json_deserialization" in deser["guessed_vulnerabilities"]
    assert deser["priority"] == "critical"

    xxe = by_url["https://example.com/api/xml?xml=%3C%21DOCTYPE%20foo%3E"]
    assert "xxe" in xxe["guessed_vulnerabilities"]
    assert xxe["priority"] == "critical"

    admin = by_url["https://example.com/admin/login"]
    assert admin["priority"] == "medium"
    assert "auth_bypass" in admin["guessed_vulnerabilities"]

    argv = captured[0]
    assert argv[:2] == ["-u", "https://example.com"]
    assert "-d" in argv and argv[argv.index("-d") + 1] == "5"
    assert "-jc" in argv
    assert "-aff" in argv
    assert "-ef" in argv and argv[argv.index("-ef") + 1] == "css,png,jpg,gif,svg,woff,ttf,js"
    assert "-o" in argv
    assert "-silent" in argv and "-no-color" in argv


async def test_katana_crawl_web_summary_matches_output_schema(
    handler_loader, make_ctx, monkeypatch
):
    mod = handler_loader("katana-crawl-web")
    captured: list[list[str]] = []
    _install_katana_fake(
        monkeypatch,
        mod,
        capture_argv=captured,
        urls=["https://example.com/download?file=backup.zip&sort=desc"],
    )

    res = await mod.run({"target": "https://example.com"}, make_ctx())

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "secbot"
        / "skills"
        / "katana-crawl-web"
        / "output.schema.json"
    )

    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(
        res.summary
    )


async def test_katana_crawl_web_bounds_candidates(handler_loader, make_ctx, monkeypatch):
    mod = handler_loader("katana-crawl-web")
    captured: list[list[str]] = []
    _install_katana_fake(
        monkeypatch,
        mod,
        capture_argv=captured,
        urls=[
            "https://example.com/a?cmd=1",
            "https://example.com/b?id=2",
            "https://example.com/c?payload=x",
        ],
    )

    res = await mod.run({"target": "https://example.com", "max_candidates": 2}, make_ctx())

    assert [c["url"] for c in res.summary["candidates"]] == [
        "https://example.com/a?cmd=1",
        "https://example.com/b?id=2",
    ]
    assert res.summary["candidate_count"] == 3
    assert res.summary["_truncated"]["candidates"]["shown"] == 2
    assert res.summary["_truncated"]["candidates"]["total"] == 3


@pytest.mark.parametrize(
    "target",
    [
        "ftp://example.com",
        "https://example.com;id",
        "https://exa mple.com",
        "https://example.com:99999",
        "https://user:pass@example.com",
        "not a url",
    ],
)
async def test_katana_crawl_web_rejects_invalid_targets(
    handler_loader, make_ctx, target
):
    mod = handler_loader("katana-crawl-web")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"target": target}, make_ctx())


async def test_katana_crawl_web_timeout_returns_structured_error(
    handler_loader, make_ctx, monkeypatch
):
    mod = handler_loader("katana-crawl-web")

    async def _fake(**_kwargs):
        raise SkillTimeout("timeout")

    monkeypatch.setattr(mod, "run_command", _fake, raising=True)
    monkeypatch.setattr(mod, "_resolve_katana_binary", lambda cli: ("katana", cli))

    res = await mod.run({"target": "https://example.com"}, make_ctx())

    assert res.summary == {"error": "timeout"}
    assert Path(res.raw_log_path or "").name == "katana-crawl-web.log"


async def test_katana_crawl_web_missing_binary_raises(
    handler_loader, make_ctx, monkeypatch
):
    mod = handler_loader("katana-crawl-web")

    def _missing(_cli):
        raise SkillBinaryMissing("missing katana")

    monkeypatch.setattr(mod, "_resolve_katana_binary", _missing)
    with pytest.raises(SkillBinaryMissing):
        await mod.run({"target": "https://example.com"}, make_ctx())
