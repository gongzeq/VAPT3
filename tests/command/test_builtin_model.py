"""Tests for the ``/model`` slash command.

Covers the three branches users hit in practice:
1. ``/model`` with no endpoint configured → instructional error.
2. ``/model`` with endpoint + mocked ``/v1/models`` → buttons + cache.
3. ``/model <name>`` → writes ``defaults.model`` into config.json (hot-reload
   happens automatically via :class:`AgentLoop` signature check).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from secbot.bus.events import InboundMessage
from secbot.command import builtin
from secbot.command.builtin import cmd_model
from secbot.command.router import CommandContext
from secbot.config.loader import load_config, save_config
from secbot.config.schema import Config


def _make_ctx(raw: str, *, args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    return CommandContext(
        msg=msg,
        session=None,
        key=msg.session_key,
        raw=raw,
        args=args,
        loop=SimpleNamespace(),
    )


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """Clear the per-process models cache between tests to avoid cross-test leaks."""
    builtin._MODEL_LIST_CACHE.clear()
    yield
    builtin._MODEL_LIST_CACHE.clear()


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point ``load_config()`` at a fresh ``config.json`` under tmp_path."""
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("secbot.config.loader._current_config_path", config_path)
    return config_path


@pytest.mark.asyncio
async def test_model_list_without_endpoint_explains_how_to_set_one(isolated_config) -> None:
    ctx = _make_ctx("/model")
    result = await cmd_model(ctx)
    assert "No OpenAI-compatible endpoint configured" in result.content
    # Offer the manual fallback so advanced users aren't stuck.
    assert "/model <name>" in result.content
    assert result.buttons == []


@pytest.mark.asyncio
async def test_model_list_fetches_v1_models_and_renders_buttons(isolated_config) -> None:
    config = load_config()
    config.providers.custom.api_base = "https://api.example.com/v1"
    config.providers.custom.api_key = "sk-test"
    save_config(config)

    async def fake_fetch(base_url, api_key):
        # Verify the command forwards both credentials to the fetch helper.
        assert base_url == "https://api.example.com/v1"
        assert api_key == "sk-test"
        return ["gpt-4o", "gpt-4o-mini"]

    with patch.object(builtin, "_fetch_openai_models", side_effect=fake_fetch):
        result = await cmd_model(_make_ctx("/model"))

    assert result.buttons == [["/model gpt-4o"], ["/model gpt-4o-mini"]]
    # Current model + endpoint should be announced in the body text so users
    # on clients without button rendering still see the context.
    assert "anthropic/claude-opus-4-5" in result.content or "Current model" in result.content
    assert "api.example.com" in result.content


@pytest.mark.asyncio
async def test_model_list_caches_for_60s(isolated_config) -> None:
    """Two back-to-back invocations should trigger exactly one HTTP fetch."""
    config = load_config()
    config.providers.custom.api_base = "https://api.example.com/v1"
    config.providers.custom.api_key = "sk-test"
    save_config(config)

    fake = AsyncMock(return_value=["a", "b"])
    with patch.object(builtin, "_fetch_openai_models", fake):
        await cmd_model(_make_ctx("/model"))
        await cmd_model(_make_ctx("/model"))

    assert fake.call_count == 1


@pytest.mark.asyncio
async def test_model_list_surfaces_fetch_failure_with_manual_fallback(isolated_config) -> None:
    config = load_config()
    config.providers.custom.api_base = "https://broken.example.com/v1"
    save_config(config)

    async def fake_fetch(*_):
        raise RuntimeError("connection refused")

    with patch.object(builtin, "_fetch_openai_models", side_effect=fake_fetch):
        result = await cmd_model(_make_ctx("/model"))

    assert "connection refused" in result.content
    # Fallback hint is non-negotiable: users need a way forward even when
    # ``/v1/models`` is unreachable.
    assert "/model <name>" in result.content


@pytest.mark.asyncio
async def test_model_switch_writes_defaults_model_to_config(isolated_config) -> None:
    """``/model <name>`` must persist to ``config.json`` so AgentLoop's
    per-turn signature check rebuilds the provider on the next message."""
    result = await cmd_model(_make_ctx("/model gpt-4o", args="gpt-4o"))
    assert "Switched default model" in result.content
    assert "no restart required" in result.content

    # The persisted value is what AgentLoop will pick up on the next turn.
    reloaded = load_config()
    assert reloaded.agents.defaults.model == "gpt-4o"


@pytest.mark.asyncio
async def test_model_switch_strips_trailing_noise(isolated_config) -> None:
    """Clicking a quick-reply button may include extra label text; take
    the first token so the UX doesn't silently corrupt ``defaults.model``."""
    result = await cmd_model(
        _make_ctx("/model gpt-4o (recommended)", args="gpt-4o (recommended)")
    )
    assert "Switched default model to `gpt-4o`" in result.content
    assert load_config().agents.defaults.model == "gpt-4o"


@pytest.mark.asyncio
async def test_model_switch_is_idempotent_when_already_current(isolated_config) -> None:
    config = load_config()
    config.agents.defaults.model = "gpt-4o"
    save_config(config)

    result = await cmd_model(_make_ctx("/model gpt-4o", args="gpt-4o"))
    assert "already" in result.content
