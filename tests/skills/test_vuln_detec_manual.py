"""Tests for the vuln-detec-manual skill handler."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secbot.skills.types import SkillContext

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "secbot" / "skills"


def _load_handler(name: str):
    mod_name = f"_secbot_skill_{name.replace('-', '_')}_handler"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, _SKILLS_ROOT / name / "handler.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_handler = _load_handler("vuln-detec-manual")
run = _handler.run
_findings_to_cmdb_writes = _handler._findings_to_cmdb_writes
_host_from_url = _handler._host_from_url
_is_ip = _handler._is_ip
_snippet = _handler._snippet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(text: str, status_code: int = 200, elapsed_ms: float = 100) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.elapsed.total_seconds.return_value = elapsed_ms / 1000
    return resp


@pytest.fixture
def ctx(tmp_path: Any) -> SkillContext:
    return SkillContext(
        scan_id="test-scan",
        scan_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# Unit tests for pure helpers
# ---------------------------------------------------------------------------


def test_host_from_url() -> None:
    assert _host_from_url("https://example.com:8443/api") == "example.com"
    assert _host_from_url("http://10.0.0.1/") == "10.0.0.1"


def test_is_ip() -> None:
    assert _is_ip("10.0.0.1") is True
    assert _is_ip("example.com") is False


def test_snippet() -> None:
    assert _snippet("short") == "short"
    long_text = "x" * 300
    assert len(_snippet(long_text)) <= 260  # 256 + "..."


def test_findings_to_cmdb_writes_only_high() -> None:
    findings = [
        {"test_name": "SQL Error Probe", "confidence": "high", "url": "http://t/api"},
        {"test_name": "XSS Reflection", "confidence": "medium", "url": "http://t/api"},
    ]
    writes = _findings_to_cmdb_writes(findings)
    assert len(writes) == 1
    assert writes[0]["data"]["category"] == "injection"
    assert writes[0]["data"]["severity"] == "high"


# ---------------------------------------------------------------------------
# Integration-style tests with mocked httpx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_targets(ctx: SkillContext) -> None:
    """Empty targets list is prevented by schema, but handler should not crash."""
    with patch("httpx.AsyncClient") as mock_client:
        client = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await run({"targets": []}, ctx)
        assert result.summary["targets"] == 0
        assert result.findings == []


@pytest.mark.asyncio
async def test_run_xss_reflection_positive(ctx: SkillContext) -> None:
    """XSS reflection detected when marker appears unescaped."""
    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("random.randint", return_value=1234),
    ):
        client = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        # Sweep order: baseline → special_char → xss_marker → xss_script → sql → time → numeric → template → command
        responses = [
            _make_response("<html>normal</html>"),                    # baseline
            _make_response("<html>normal</html>"),                    # special char (same length → no flag)
            _make_response("<html>secbot1234</html>"),                # XSS marker reflected
            _make_response("<html><script>alert(1)</script></html>"), # XSS script test (raw)
            _make_response("clean response"),                         # SQL error (no keyword)
            _make_response("ok"),                                     # time sqli
            _make_response("1"),                                      # numeric
            _make_response("{{7*7}}"),                                # template (no 49)
            _make_response(";id"),                                    # command
        ]
        client.get = AsyncMock(side_effect=responses)

        result = await run(
            {"targets": [{"url": "http://target/page", "params": {"q": "1"}}]},
            ctx,
        )

        xss_findings = [f for f in result.findings if f["test_name"] == "XSS Reflection"]
        assert len(xss_findings) == 1
        assert xss_findings[0]["confidence"] == "high"
        assert xss_findings[0]["result"] == "positive"


@pytest.mark.asyncio
async def test_run_sql_error_positive(ctx: SkillContext) -> None:
    """SQL error probe detects MySQL syntax error."""
    with patch("httpx.AsyncClient") as mock_client:
        client = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        # Sweep order: baseline → special_char → xss_marker (no match → 1 req only) → sql → time → numeric → template → command
        responses = [
            _make_response("<html>ok</html>"),                       # baseline
            _make_response("<html>ok</html>"),                       # special char (same len → no flag)
            _make_response("<html>no marker</html>"),                # XSS marker probe (no match)
            _make_response("You have an error in your SQL syntax; check the manual that corresponds to your MySQL server"),  # SQL error
            _make_response("ok"),                                    # time sqli
            _make_response("1"),                                     # numeric
            _make_response("{{7*7}}"),                               # template
            _make_response(";id"),                                   # command
        ]
        client.get = AsyncMock(side_effect=responses)

        result = await run(
            {"targets": [{"url": "http://target/page", "params": {"id": "1"}}]},
            ctx,
        )

        sql_findings = [f for f in result.findings if f["test_name"] == "SQL Error Probe"]
        assert len(sql_findings) == 1
        assert sql_findings[0]["confidence"] == "high"
        assert sql_findings[0]["result"] == "positive"
        # cmdb_writes should include this high-confidence finding
        assert len(result.cmdb_writes) >= 1


@pytest.mark.asyncio
async def test_run_template_injection_positive(ctx: SkillContext) -> None:
    """Template injection detected when 49 appears in response."""
    with patch("httpx.AsyncClient") as mock_client:
        client = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        # Sweep order: baseline → special_char → xss_marker (no match) → sql → time → numeric → template → command
        responses = [
            _make_response("<html>ok</html>"),           # baseline
            _make_response("<html>ok</html>"),           # special char (same len)
            _make_response("<html>marker</html>"),       # XSS marker (no match)
            _make_response("no sql errors here"),        # SQL error
            _make_response("ok"),                        # time sqli
            _make_response("1"),                         # numeric
            _make_response("result: 49"),                # template injection!
            _make_response(";id"),                       # command
        ]
        client.get = AsyncMock(side_effect=responses)

        result = await run(
            {"targets": [{"url": "http://target/page", "params": {"name": "bob"}}]},
            ctx,
        )

        tmpl_findings = [
            f for f in result.findings if f["test_name"] == "Template Injection"
        ]
        assert len(tmpl_findings) == 1
        assert tmpl_findings[0]["confidence"] == "high"
        assert tmpl_findings[0]["result"] == "positive"


@pytest.mark.asyncio
async def test_run_no_vulnerabilities(ctx: SkillContext) -> None:
    """Clean target produces zero findings."""
    with patch("httpx.AsyncClient") as mock_client:
        client = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        # All responses are clean → no findings (use non-numeric param to skip numeric arithmetic probe)
        client.get = AsyncMock(return_value=_make_response("<html>clean</html>"))

        result = await run(
            {"targets": [{"url": "http://target/page", "params": {"q": "abc"}}]},
            ctx,
        )

        assert result.summary["targets"] == 1
        assert result.summary["findings"] == 0
        assert result.summary["high_confidence"] == 0
        assert result.cmdb_writes == []


@pytest.mark.asyncio
async def test_run_multiple_targets(ctx: SkillContext) -> None:
    """Two targets swept in one call."""
    with patch("httpx.AsyncClient") as mock_client:
        client = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

        client.get = AsyncMock(return_value=_make_response("clean"))

        result = await run(
            {
                "targets": [
                    {"url": "http://t1/page", "params": {"q": "abc"}},
                    {"url": "http://t2/api", "params": {"q": "x"}},
                ]
            },
            ctx,
        )

        assert result.summary["targets"] == 2
        assert result.findings == []
