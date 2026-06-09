"""Tests for the CMDB auto-flush converters in AssetPushTool.

PR ``06-06-fix-report-pipeline``: when kind is ``vuln``, ``credential``,
or ``tech``, ``asset_push`` auto-persists to the CMDB so ``report-html``
can render a complete report without a separate flush step.
"""

from __future__ import annotations

from secbot.agent.tools.asset_feed import (
    _credential_to_cmdb_write,
    _host_from_url,
    _normalise_category,
    _tech_to_cmdb_write,
    _vuln_to_cmdb_write,
)

# ---------------------------------------------------------------------------
# _host_from_url
# ---------------------------------------------------------------------------


def test_host_from_url_with_port() -> None:
    assert _host_from_url("http://1.2.3.4:8080/vul/rce.php") == "1.2.3.4:8080"


def test_host_from_url_default_http_port() -> None:
    assert _host_from_url("http://example.com/path") == "example.com"


def test_host_from_url_default_https_port() -> None:
    assert _host_from_url("https://example.com:443/path") == "example.com"


def test_host_from_url_fallback_on_garbage() -> None:
    # Invalid URL should return the raw string.
    result = _host_from_url("not-a-url")
    assert result  # non-empty fallback


# ---------------------------------------------------------------------------
# _vuln_to_cmdb_write
# ---------------------------------------------------------------------------


def test_vuln_to_cmdb_write_with_url() -> None:
    payload = {
        "url": "http://111.228.2.47:8080/vul/rce/rce_ping.php",
        "param": "ipaddress",
        "type": "rce",
        "severity": "critical",
        "evidence": "POST ipaddress=127.0.0.1;id returns uid=1000(www-data)",
    }
    write = _vuln_to_cmdb_write(payload)
    assert write is not None
    assert write["table"] == "vulnerabilities"
    assert write["op"] == "upsert"
    data = write["data"]
    assert data["target"] == "111.228.2.47:8080"
    assert data["severity"] == "critical"
    assert data["category"] == "injection"  # rce → injection
    assert "rce_ping" in data["title"].lower() or "rce" in data["title"].lower()
    assert "www-data" in data["evidence"]


def test_vuln_to_cmdb_write_with_explicit_target() -> None:
    payload = {"target": "myhost", "severity": "high", "type": "sqli"}
    write = _vuln_to_cmdb_write(payload)
    assert write is not None
    assert write["data"]["target"] == "myhost"


def test_vuln_to_cmdb_write_returns_none_when_no_target() -> None:
    # Empty payload → no target → returns None.
    assert _vuln_to_cmdb_write({}) is None


def test_vuln_to_cmdb_write_uses_host_fallback() -> None:
    payload = {"host": "db.internal", "type": "info_leak", "severity": "low"}
    write = _vuln_to_cmdb_write(payload)
    assert write is not None
    assert write["data"]["target"] == "db.internal"


# ---------------------------------------------------------------------------
# _credential_to_cmdb_write
# ---------------------------------------------------------------------------


def test_credential_to_cmdb_write_full() -> None:
    payload = {
        "host": "111.228.2.47",
        "port": 3306,
        "username": "root",
        "password": "",
        "db": "pikachu",
        "type": "mysql",
        "note": "Empty root password",
    }
    write = _credential_to_cmdb_write(payload)
    assert write is not None
    data = write["data"]
    assert data["target"] == "111.228.2.47:3306"
    assert data["severity"] == "critical"
    assert data["category"] == "weak_password"
    assert "root" in data["evidence"]
    assert "Empty root password" in data["evidence"]


def test_credential_to_cmdb_write_no_port() -> None:
    payload = {"host": "api.internal", "username": "admin", "password": "admin"}
    write = _credential_to_cmdb_write(payload)
    assert write is not None
    assert write["data"]["target"] == "api.internal"


def test_credential_to_cmdb_write_returns_none_when_no_host() -> None:
    assert _credential_to_cmdb_write({"username": "x"}) is None


# ---------------------------------------------------------------------------
# _tech_to_cmdb_write
# ---------------------------------------------------------------------------


def test_tech_to_cmdb_write_with_url() -> None:
    payload = {
        "url": "http://111.228.2.47:8080",
        "server": "Apache/2.4.29 (Ubuntu)",
        "platform": "Pikachu",
        "os": "Linux (Docker container)",
    }
    write = _tech_to_cmdb_write(payload)
    assert write is not None
    assert write["table"] == "assets"
    data = write["data"]
    assert data["target"] == "111.228.2.47:8080"
    assert data["tags"]["server"] == "Apache/2.4.29 (Ubuntu)"
    assert data["os_guess"] == "Linux (Docker container)"


def test_tech_to_cmdb_write_returns_none_when_no_target() -> None:
    assert _tech_to_cmdb_write({"server": "nginx"}) is None


# ---------------------------------------------------------------------------
# _normalise_category
# ---------------------------------------------------------------------------


def test_normalise_category_passthrough() -> None:
    """Valid CMDB categories pass through unchanged."""
    for cat in ("injection", "xss", "auth", "misconfig", "exposure",
                "weak_password", "cve", "other"):
        assert _normalise_category(cat) == cat


def test_normalise_category_sql_injection() -> None:
    assert _normalise_category("sql_injection") == "injection"
    assert _normalise_category("sqli") == "injection"


def test_normalise_category_rce() -> None:
    assert _normalise_category("rce") == "injection"


def test_normalise_category_ssrf() -> None:
    assert _normalise_category("ssrf") == "misconfig"


def test_normalise_category_unknown_falls_to_other() -> None:
    assert _normalise_category("something_weird") == "other"
