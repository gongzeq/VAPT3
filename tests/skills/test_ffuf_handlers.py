"""Unit tests for the ffuf-based skills.

Covers the happy path (URL mode + raw-request mode), the shared argv
builder (matchers/filters/auto-calibration/rate), and the common input
validation failures. The sandbox is mocked via ``fake_run_command`` so
no real ffuf binary / network is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from secbot.skills._shared import ffuf as _ffuf
from secbot.skills.types import InvalidSkillArg, SkillResult

from tests.skills.test_handlers import load_handler  # reuse the loader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_results(scan_dir: Path, *, sub: str, filename: str, results: list[dict]) -> None:
    path = scan_dir / "ffuf" / sub / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"results": results, "commandline": "ffuf -u x"}), encoding="utf-8")


def _install_ffuf_fake(
    monkeypatch,
    *,
    capture_argv: list,
    scan_dir: Path,
    sub: str,
    filename: str,
    results: list[dict],
) -> None:
    """Install a sandbox fake that writes a fixed ffuf JSON into results_file
    and records the argv that the skill generated."""
    from secbot.skills._shared import runner as runner_mod
    from secbot.skills._shared.sandbox import SandboxResult

    async def _fake(**kwargs):
        capture_argv.append(list(kwargs.get("args", [])))
        raw = kwargs.get("raw_log_path")
        if raw is not None:
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
            Path(raw).write_bytes(b"")
        _write_results(scan_dir, sub=sub, filename=filename, results=results)
        return SandboxResult(exit_code=0, raw_log_path=raw, captured=None)

    monkeypatch.setattr(runner_mod, "run_command", _fake, raising=True)


# ---------------------------------------------------------------------------
# ffuf-dir-fuzz
# ---------------------------------------------------------------------------


_DIR_HITS = [
    {
        "url": "https://target.com/admin",
        "input": {"FUZZ": "admin"},
        "status": 200,
        "length": 1234,
        "words": 80,
        "lines": 20,
        "duration": 125_000_000,       # 125 ms in ns
        "content-type": "text/html; charset=utf-8",
        "redirectlocation": "",
        "host": "target.com",
    },
    {
        "url": "https://target.com/backup.bak",
        "input": {"FUZZ": "backup.bak"},
        "status": 403,
        "length": 50,
        "words": 5,
        "lines": 1,
        "duration": 40_000_000,
        "content-type": "text/plain",
        "redirectlocation": "",
        "host": "target.com",
    },
]


async def test_ffuf_dir_fuzz_happy_url_mode(make_ctx, monkeypatch):
    mod = load_handler("ffuf-dir-fuzz")
    captured_argv: list[list[str]] = []
    ctx = make_ctx()
    _install_ffuf_fake(
        monkeypatch,
        capture_argv=captured_argv,
        scan_dir=ctx.scan_dir,
        sub="dir",
        filename="dir-results.json",
        results=_DIR_HITS,
    )
    res = await mod.run(
        {
            "url": "https://target.com/FUZZ",
            "wordlist": ["admin", "backup.bak", "hidden"],
            "extensions": [".php", ".bak"],
            "match_codes": "200,301,302,403",
            "filter_sizes": "0",
            "rate": 10,
            "threads": 20,
            "delay": "0.1-0.5",
            "headers": ["X-API-Key: abcdef123456", "Accept: application/json"],
            "cookies": ["session=abcdef"],
        },
        ctx,
    )
    assert isinstance(res, SkillResult)

    hits = res.summary["hits"]
    assert len(hits) == 2
    assert hits[0]["url"] == "https://target.com/admin"
    assert hits[0]["input"] == "admin"
    assert hits[0]["status"] == 200
    assert hits[0]["duration_ms"] == 125
    assert hits[0]["content_type"].startswith("text/html")

    argv = captured_argv[0]
    assert "-u" in argv and "https://target.com/FUZZ" in argv
    assert "-e" in argv
    assert argv[argv.index("-e") + 1] == ".php,.bak"
    assert "-ac" in argv                          # auto-calibration by default
    assert "-mc" in argv
    assert argv[argv.index("-mc") + 1] == "200,301,302,403"
    assert "-fs" in argv
    assert argv[argv.index("-fs") + 1] == "0"
    assert "-t" in argv and argv[argv.index("-t") + 1] == "20"
    assert "-rate" in argv and argv[argv.index("-rate") + 1] == "10"
    assert "-p" in argv and argv[argv.index("-p") + 1] == "0.1-0.5"
    assert "-H" in argv
    # At least one header was forwarded
    h_idxs = [i for i, a in enumerate(argv) if a == "-H"]
    assert len(h_idxs) >= 2
    assert argv[h_idxs[0] + 1] == "X-API-Key: abcdef123456"
    assert "-b" in argv and argv[argv.index("-b") + 1] == "session=abcdef"
    # Output flags are always present
    assert "-of" in argv and "-o" in argv and "-s" in argv


async def test_ffuf_dir_fuzz_raw_request_mode(make_ctx, monkeypatch):
    mod = load_handler("ffuf-dir-fuzz")
    captured_argv: list[list[str]] = []
    ctx = make_ctx()
    _install_ffuf_fake(
        monkeypatch,
        capture_argv=captured_argv,
        scan_dir=ctx.scan_dir,
        sub="dir",
        filename="dir-results.json",
        results=_DIR_HITS[:1],
    )
    raw = (
        "GET /api/v1/users/FUZZ HTTP/1.1\n"
        "Host: api.target.com\n"
        "Authorization: Bearer abcdef\n\n"
    )
    res = await mod.run(
        {"raw_request": raw, "wordlist": ["1", "2", "3"]},
        ctx,
    )
    assert res.summary["hits"][0]["input"] == "admin"

    argv = captured_argv[0]
    assert "--request" in argv
    req_path = argv[argv.index("--request") + 1]
    assert Path(req_path).exists()
    assert Path(req_path).read_text().startswith("GET /api/v1/users/FUZZ")
    assert "-request-proto" in argv
    # URL-mode flags must NOT be present
    assert "-u" not in argv


async def test_ffuf_dir_fuzz_requires_fuzz_marker(make_ctx):
    mod = load_handler("ffuf-dir-fuzz")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {"url": "https://target.com/no-marker", "wordlist": ["a"]},
            make_ctx(),
        )


async def test_ffuf_dir_fuzz_rejects_both_modes(make_ctx):
    mod = load_handler("ffuf-dir-fuzz")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {
                "url": "https://target.com/FUZZ",
                "raw_request": "GET /FUZZ HTTP/1.1\nHost: x\n\n",
                "wordlist": ["a"],
            },
            make_ctx(),
        )


async def test_ffuf_dir_fuzz_rejects_forbidden_header_char(make_ctx):
    mod = load_handler("ffuf-dir-fuzz")
    with pytest.raises(InvalidSkillArg):
        # '$' is in FORBIDDEN_CHARS
        await mod.run(
            {
                "url": "https://target.com/FUZZ",
                "wordlist": ["a"],
                "headers": ["X-Bad: $(whoami)"],
            },
            make_ctx(),
        )


async def test_ffuf_dir_fuzz_auto_calibrate_can_be_disabled(make_ctx, monkeypatch):
    mod = load_handler("ffuf-dir-fuzz")
    captured_argv: list[list[str]] = []
    ctx = make_ctx()
    _install_ffuf_fake(
        monkeypatch,
        capture_argv=captured_argv,
        scan_dir=ctx.scan_dir,
        sub="dir",
        filename="dir-results.json",
        results=[],
    )
    await mod.run(
        {
            "url": "https://target.com/FUZZ",
            "wordlist": ["a"],
            "auto_calibrate": False,
        },
        ctx,
    )
    argv = captured_argv[0]
    assert "-ac" not in argv
    assert "-ach" not in argv


async def test_ffuf_dir_fuzz_per_host_calibration_overrides(make_ctx, monkeypatch):
    mod = load_handler("ffuf-dir-fuzz")
    captured_argv: list[list[str]] = []
    ctx = make_ctx()
    _install_ffuf_fake(
        monkeypatch,
        capture_argv=captured_argv,
        scan_dir=ctx.scan_dir,
        sub="dir",
        filename="dir-results.json",
        results=[],
    )
    await mod.run(
        {
            "url": "https://target.com/FUZZ",
            "wordlist": ["a"],
            "auto_calibrate_per_host": True,
        },
        ctx,
    )
    argv = captured_argv[0]
    assert "-ach" in argv
    assert "-ac" not in argv


# ---------------------------------------------------------------------------
# ffuf-vhost-fuzz
# ---------------------------------------------------------------------------


_VHOST_HITS = [
    {
        "url": "https://203.0.113.10",
        "input": {"FUZZ": "api"},
        "status": 200,
        "length": 9001,
        "words": 300,
        "lines": 60,
        "duration": 75_000_000,
        "content-type": "application/json",
        "redirectlocation": "",
        "host": "api.example.com",
    },
]


async def test_ffuf_vhost_fuzz_happy(make_ctx, monkeypatch):
    mod = load_handler("ffuf-vhost-fuzz")
    captured_argv: list[list[str]] = []
    ctx = make_ctx()
    _install_ffuf_fake(
        monkeypatch,
        capture_argv=captured_argv,
        scan_dir=ctx.scan_dir,
        sub="vhost",
        filename="vhost-results.json",
        results=_VHOST_HITS,
    )
    res = await mod.run(
        {
            "url": "https://203.0.113.10",
            "host_template": "FUZZ.example.com",
            "wordlist": ["www", "api", "dev"],
            "filter_sizes": "4242",
            "threads": 15,
        },
        ctx,
    )
    assert isinstance(res, SkillResult)
    vhosts = res.summary["vhosts"]
    assert vhosts[0]["host"] == "api"
    assert vhosts[0]["status"] == 200
    assert vhosts[0]["length"] == 9001
    assert vhosts[0]["url"] == "https://203.0.113.10"

    argv = captured_argv[0]
    assert "-u" in argv and "https://203.0.113.10" in argv
    assert "-H" in argv
    assert argv[argv.index("-H") + 1] == "Host: FUZZ.example.com"
    assert "-ac" in argv
    assert "-fs" in argv and argv[argv.index("-fs") + 1] == "4242"
    assert "-t" in argv and argv[argv.index("-t") + 1] == "15"
    # Vhost skill does NOT inject a default match_codes.
    assert "-mc" not in argv


async def test_ffuf_vhost_fuzz_raw_request(make_ctx, monkeypatch):
    mod = load_handler("ffuf-vhost-fuzz")
    captured_argv: list[list[str]] = []
    ctx = make_ctx()
    _install_ffuf_fake(
        monkeypatch,
        capture_argv=captured_argv,
        scan_dir=ctx.scan_dir,
        sub="vhost",
        filename="vhost-results.json",
        results=_VHOST_HITS,
    )
    raw = (
        "GET / HTTP/1.1\n"
        "Host: FUZZ.example.com\n"
        "Authorization: Bearer abcdef\n\n"
    )
    res = await mod.run(
        {"raw_request": raw, "wordlist": ["www", "api"]},
        ctx,
    )
    assert res.summary["vhosts"][0]["host"] == "api"

    argv = captured_argv[0]
    assert "--request" in argv
    assert "-u" not in argv


async def test_ffuf_vhost_fuzz_requires_fuzz_marker(make_ctx):
    mod = load_handler("ffuf-vhost-fuzz")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {
                "url": "https://203.0.113.10",
                "host_template": "static.example.com",
                "wordlist": ["www"],
            },
            make_ctx(),
        )


async def test_ffuf_vhost_fuzz_rejects_wordlist_with_space(make_ctx):
    mod = load_handler("ffuf-vhost-fuzz")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {
                "url": "https://203.0.113.10",
                "host_template": "FUZZ.example.com",
                "wordlist": ["has space"],
            },
            make_ctx(),
        )


async def test_ffuf_vhost_fuzz_rejects_both_modes(make_ctx):
    mod = load_handler("ffuf-vhost-fuzz")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {
                "url": "https://203.0.113.10",
                "host_template": "FUZZ.example.com",
                "raw_request": "GET / HTTP/1.1\nHost: FUZZ.x\n\n",
                "wordlist": ["a"],
            },
            make_ctx(),
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def test_shared_range_spec_validator():
    _ffuf.validate_range_spec("match_codes", "200,301-302,400-499")
    with pytest.raises(InvalidSkillArg):
        _ffuf.validate_range_spec("match_codes", "abc")


def test_shared_header_validator():
    _ffuf.validate_header("Authorization: Bearer abc")
    with pytest.raises(InvalidSkillArg):
        _ffuf.validate_header("not-a-header")
    with pytest.raises(InvalidSkillArg):
        _ffuf.validate_header("Bad Name: value")  # space in header name


def test_shared_cookie_validator():
    _ffuf.validate_cookie("session=abcdef")
    with pytest.raises(InvalidSkillArg):
        _ffuf.validate_cookie("no-equals-sign")


def test_shared_build_common_argv_defaults(tmp_path: Path):
    argv = _ffuf.build_common_argv({}, results_file=tmp_path / "r.json")
    # Default: ac on, threads=40, output as JSON+silent
    assert "-ac" in argv
    assert "-t" in argv and "40" in argv
    assert "-of" in argv and "json" in argv
    assert "-s" in argv


def test_shared_parse_results_json(tmp_path: Path):
    p = tmp_path / "r.json"
    p.write_text(
        json.dumps(
            {
                "commandline": "ffuf -u target",
                "results": [
                    {
                        "url": "u",
                        "input": {"FUZZ": "admin"},
                        "status": 200,
                        "length": 10,
                        "words": 2,
                        "lines": 1,
                        "duration": 1_000_000,
                        "content-type": "text/html",
                        "redirectlocation": "/next",
                        "host": "h",
                    }
                ],
            }
        )
    )
    entries, meta = _ffuf.parse_results_json(p)
    assert len(entries) == 1
    assert entries[0]["input"] == "admin"
    assert entries[0]["duration_ms"] == 1
    assert meta["total_hits"] == 1
    assert meta["command_line"].startswith("ffuf ")
