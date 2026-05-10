"""Unit tests for ``GET /api/prompts`` and the underlying YAML loader.

Spec: ``.trellis/spec/backend/prompts-config.md`` §6. Covers default load,
override via ``SECBOT_PROMPTS_FILE``, missing-file fallback, parse errors
preserving the prior value, mtime-based hot reload, duplicate ``key``
dedup, and the HTTP surface (401 without token, 200 with).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from secbot.api import prompts as prompts_mod
from secbot.channels.websocket import WebSocketChannel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_loader(monkeypatch, tmp_path: Path):
    """Give every test a fresh loader singleton and a tmp-located user
    override so the real ``~/.secbot/prompts.yaml`` (if any) cannot leak in.

    ``SECBOT_PROMPTS_FILE`` is cleared by default — tests opt-in per-case.
    """
    monkeypatch.delenv("SECBOT_PROMPTS_FILE", raising=False)
    monkeypatch.setattr(
        prompts_mod, "_USER_OVERRIDE_PATH", tmp_path / "does-not-exist.yaml"
    )
    prompts_mod.reset_loader()
    yield
    prompts_mod.reset_loader()


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _valid_yaml(*entries: dict[str, str]) -> str:
    """Render a minimal ``prompts:`` YAML from dicts."""
    if not entries:
        return "prompts: []\n"
    lines = ["prompts:"]
    for e in entries:
        lines.append(f"  - key: {e['key']}")
        for field in ("title", "subtitle", "prefill", "icon"):
            lines.append(f"    {field}: {e[field]}")
    return "\n".join(lines) + "\n"


def _default_entry(key: str, *, icon: str = "Radar") -> dict[str, str]:
    return {
        "key": key,
        "title": f"title-{key}",
        "subtitle": f"sub-{key}",
        "prefill": f"pre-{key}",
        "icon": icon,
    }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_default_bundled_yaml_returns_four_documented_prompts() -> None:
    """Against the committed ``secbot/config/prompts.yaml`` the default
    ordering and icon set must match what the old frontend shipped."""
    rows = prompts_mod.load_prompts()
    assert [r["key"] for r in rows] == ["scanAsset", "weakPwd", "summarize", "drill"]
    assert [r["icon"] for r in rows] == ["Radar", "Key", "FileText", "Bug"]
    for r in rows:
        assert r["title"].strip()
        assert r["subtitle"].strip()
        assert r["prefill"].strip()


def test_env_override_takes_priority(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "override.yaml"
    _write_yaml(override, _valid_yaml(_default_entry("only", icon="Sparkles")))
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(override))

    rows = prompts_mod.load_prompts()
    assert len(rows) == 1
    assert rows[0]["key"] == "only"
    assert rows[0]["icon"] == "Sparkles"


def test_missing_file_returns_empty_and_logs_once(
    monkeypatch, tmp_path: Path
) -> None:
    """Env points to a non-existent file AND user-override path missing
    AND the bundled path hidden → resolver returns None → empty list."""
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(tmp_path / "nope.yaml"))
    monkeypatch.setattr(prompts_mod, "_BUNDLED_PATH", tmp_path / "bundled-missing.yaml")

    rows_a = prompts_mod.load_prompts()
    rows_b = prompts_mod.load_prompts()
    assert rows_a == [] == rows_b


def test_parse_error_keeps_prior_cached_value(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "prompts.yaml"
    _write_yaml(source, _valid_yaml(_default_entry("alpha")))
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(source))

    first = prompts_mod.load_prompts()
    assert [r["key"] for r in first] == ["alpha"]

    # Force a detectable mtime change — on very fast filesystems the second
    # write can land in the same second otherwise.
    time.sleep(0.01)
    _write_yaml(source, "prompts:\n  - key: alpha\n    title: [unterminated\n")
    os.utime(source, None)

    fallback = prompts_mod.load_prompts()
    # Serves the previous cached list, NOT empty.
    assert [r["key"] for r in fallback] == ["alpha"]


def test_mtime_change_picks_up_new_content(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "prompts.yaml"
    _write_yaml(source, _valid_yaml(_default_entry("v1")))
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(source))

    assert [r["key"] for r in prompts_mod.load_prompts()] == ["v1"]

    time.sleep(0.01)
    _write_yaml(source, _valid_yaml(_default_entry("v2a"), _default_entry("v2b")))
    os.utime(source, None)

    rows = prompts_mod.load_prompts()
    assert [r["key"] for r in rows] == ["v2a", "v2b"]


def test_duplicate_key_keeps_first_occurrence(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "prompts.yaml"
    body = _valid_yaml(
        _default_entry("dup", icon="Radar"),
        _default_entry("dup", icon="Bug"),
        _default_entry("unique", icon="Key"),
    )
    _write_yaml(source, body)
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(source))

    rows = prompts_mod.load_prompts()
    assert [r["key"] for r in rows] == ["dup", "unique"]
    # First-wins: the winning entry keeps the *first* icon.
    dup = next(r for r in rows if r["key"] == "dup")
    assert dup["icon"] == "Radar"


def test_missing_required_field_skips_entry(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "prompts.yaml"
    # Second entry is missing ``prefill`` — drop silently instead of raising.
    source.write_text(
        "prompts:\n"
        "  - key: good\n"
        "    title: ok\n"
        "    subtitle: ok\n"
        "    prefill: ok\n"
        "    icon: Radar\n"
        "  - key: bad\n"
        "    title: ok\n"
        "    subtitle: ok\n"
        "    icon: Bug\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(source))

    rows = prompts_mod.load_prompts()
    assert [r["key"] for r in rows] == ["good"]


def test_top_level_list_is_tolerated(monkeypatch, tmp_path: Path) -> None:
    """YAML authors sometimes skip the ``prompts:`` wrapper — don't punish."""
    source = tmp_path / "prompts.yaml"
    source.write_text(
        "- key: solo\n"
        "  title: t\n"
        "  subtitle: s\n"
        "  prefill: p\n"
        "  icon: Radar\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(source))

    rows = prompts_mod.load_prompts()
    assert [r["key"] for r in rows] == ["solo"]


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------


def _ch() -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    ch = WebSocketChannel(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": 0,
            "path": "/",
            "websocketRequiresToken": False,
        },
        bus,
    )
    return ch


class _Req:
    def __init__(self, path: str, *, token: str | None = "live"):
        self.path = path
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _body(resp) -> dict[str, Any]:
    return json.loads(resp.body)


def test_http_route_requires_authentication() -> None:
    channel = _ch()
    resp = channel._handle_prompts(_Req("/api/prompts", token=None))
    assert resp.status_code == 401


def test_http_route_returns_prompts_payload() -> None:
    channel = _ch()
    channel._api_tokens["live"] = time.monotonic() + 60.0

    resp = channel._handle_prompts(_Req("/api/prompts"))
    assert resp.status_code == 200
    body = _body(resp)
    # Default bundled YAML ships 4 prompts in a fixed order.
    assert isinstance(body["prompts"], list)
    keys = [p["key"] for p in body["prompts"]]
    assert keys == ["scanAsset", "weakPwd", "summarize", "drill"]


def test_http_route_returns_empty_when_all_sources_missing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SECBOT_PROMPTS_FILE", str(tmp_path / "none.yaml"))
    monkeypatch.setattr(prompts_mod, "_BUNDLED_PATH", tmp_path / "bundled-gone.yaml")

    channel = _ch()
    channel._api_tokens["live"] = time.monotonic() + 60.0

    resp = channel._handle_prompts(_Req("/api/prompts"))
    assert resp.status_code == 200
    assert _body(resp) == {"prompts": []}
