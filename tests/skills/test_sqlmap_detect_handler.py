"""Unit tests for ``sqlmap-detect`` argv construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from secbot.skills.types import InvalidSkillArg, SkillResult
from tests.skills.test_handlers import load_handler


async def test_sqlmap_detect_uses_request_file_for_post_data(make_ctx, monkeypatch):
    mod = load_handler("sqlmap-detect")
    captured: dict[str, object] = {}

    async def _fake_execute(**kwargs):
        captured.update(kwargs)
        return SkillResult(summary={"vulnerable": False})

    monkeypatch.setattr(mod, "execute", _fake_execute, raising=True)
    monkeypatch.setattr(mod, "_resolve_sqlmap_binary", lambda cli: ("sqlmap", cli))

    ctx = make_ctx()
    await mod.run(
        {
            "url": "http://111.228.2.47:8080/vul/sqli/sqli_id.php",
            "method": "POST",
            "data": "id=1&submit=查询",
            "level": 2,
            "risk": 1,
        },
        ctx,
    )

    argv = captured["args"]
    assert isinstance(argv, list)
    raw_log_name = captured["raw_log_name"]
    assert isinstance(raw_log_name, str)
    assert raw_log_name.startswith("sqlmap-detect-")
    assert raw_log_name.endswith(".log")
    assert "--data" not in argv
    assert "id=1&submit=查询" not in argv
    assert argv[argv.index("-p") + 1] == "id"
    request_path = Path(argv[argv.index("-r") + 1])
    request_text = request_path.read_text(encoding="utf-8")
    assert "POST /vul/sqli/sqli_id.php HTTP/1.1" in request_text
    assert "Host: 111.228.2.47:8080" in request_text
    assert "Content-Type: application/x-www-form-urlencoded" in request_text
    assert request_path.read_bytes().endswith("\r\n\r\nid=1&submit=查询".encode())


async def test_sqlmap_detect_request_file_preserves_get_query(make_ctx, monkeypatch):
    mod = load_handler("sqlmap-detect")
    captured: dict[str, object] = {}

    async def _fake_execute(**kwargs):
        captured.update(kwargs)
        return SkillResult(summary={"vulnerable": False})

    monkeypatch.setattr(mod, "execute", _fake_execute, raising=True)
    monkeypatch.setattr(mod, "_resolve_sqlmap_binary", lambda cli: ("sqlmap", cli))

    await mod.run(
        {"url": "https://target.test/search.php?q=abc&sort=id", "method": "GET"},
        make_ctx(),
    )

    argv = captured["args"]
    assert isinstance(argv, list)
    assert "--force-ssl" in argv
    assert argv[argv.index("-p") + 1] == "q,sort"
    assert "https://target.test/search.php?q=abc&sort=id" not in argv
    request_path = Path(argv[argv.index("-r") + 1])
    request_text = request_path.read_text(encoding="utf-8")
    assert "GET /search.php?q=abc&sort=id HTTP/1.1" in request_text
    assert "Host: target.test" in request_text


async def test_sqlmap_detect_uses_post_form_parameter_over_submit(
    make_ctx, monkeypatch
):
    mod = load_handler("sqlmap-detect")
    captured: dict[str, object] = {}

    async def _fake_execute(**kwargs):
        captured.update(kwargs)
        return SkillResult(summary={"vulnerable": False})

    monkeypatch.setattr(mod, "execute", _fake_execute, raising=True)
    monkeypatch.setattr(mod, "_resolve_sqlmap_binary", lambda cli: ("sqlmap", cli))

    await mod.run(
        {
            "url": "http://target.test/vul/sqli/sqli_search.php",
            "method": "POST",
            "data": "key=test&submit=search",
        },
        make_ctx(),
    )

    argv = captured["args"]
    assert isinstance(argv, list)
    assert argv[argv.index("-p") + 1] == "key"


async def test_sqlmap_detect_omits_p_when_only_control_fields(make_ctx, monkeypatch):
    mod = load_handler("sqlmap-detect")
    captured: dict[str, object] = {}

    async def _fake_execute(**kwargs):
        captured.update(kwargs)
        return SkillResult(summary={"vulnerable": False})

    monkeypatch.setattr(mod, "execute", _fake_execute, raising=True)
    monkeypatch.setattr(mod, "_resolve_sqlmap_binary", lambda cli: ("sqlmap", cli))

    await mod.run(
        {
            "url": "http://target.test/form.php",
            "method": "POST",
            "data": "csrf_token=abc&submit=search",
        },
        make_ctx(),
    )

    argv = captured["args"]
    assert isinstance(argv, list)
    assert "-p" not in argv


async def test_sqlmap_detect_rejects_crlf_in_cookie(make_ctx):
    mod = load_handler("sqlmap-detect")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {
                "url": "http://target.test/index.php?id=1",
                "cookie": "sid=abc\r\nX-Evil: yes",
            },
            make_ctx(),
        )
