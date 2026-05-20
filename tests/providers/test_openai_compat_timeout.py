from unittest.mock import patch, sentinel

from secbot.providers.openai_compat_provider import OpenAICompatProvider
from secbot.providers.registry import ProviderSpec


def _assert_openai_compat_timeout(timeout) -> None:
    assert timeout == 120.0


def test_openai_compat_provider_sets_sdk_timeout() -> None:
    with patch("secbot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(kwargs["timeout"])
    assert kwargs["http_client"] is None


def test_openai_compat_provider_sets_timeout_on_local_http_client() -> None:
    spec = ProviderSpec(
        name="local",
        keywords=(),
        env_key="",
        is_local=True,
        default_api_base="http://127.0.0.1:11434/v1",
    )

    with (
        patch("secbot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai,
        patch(
            "secbot.providers.openai_compat_provider.httpx.AsyncClient",
            return_value=sentinel.http_client,
        ) as mock_http_client,
    ):
        OpenAICompatProvider(spec=spec)

    client_kwargs = mock_http_client.call_args.kwargs
    _assert_openai_compat_timeout(client_kwargs["timeout"])
    assert client_kwargs["limits"].keepalive_expiry == 0

    openai_kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(openai_kwargs["timeout"])
    assert openai_kwargs["http_client"] is sentinel.http_client


def test_openai_compat_provider_timeout_can_be_overridden_by_env(monkeypatch) -> None:
    monkeypatch.setenv("SECBOT_OPENAI_COMPAT_TIMEOUT_S", "45")

    with patch("secbot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    assert mock_async_openai.call_args.kwargs["timeout"] == 45.0


def test_openai_compat_provider_disables_keepalive_for_xiaomi_mimo() -> None:
    """MiMo cloud endpoint must not reuse pooled connections.

    Long-running tools (multi-minute scans) leave the connection idle
    much longer than MiMo tolerates; reusing such a connection on the
    next turn surfaces as ``APIConnectionError("Connection error.")``
    that consistently fails through every retry.
    """
    spec = ProviderSpec(
        name="xiaomi_mimo",
        keywords=("mimo",),
        env_key="XIAOMIMIMO_API_KEY",
        default_api_base="https://api.xiaomimimo.com/v1",
    )

    with (
        patch("secbot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai,
        patch(
            "secbot.providers.openai_compat_provider.httpx.AsyncClient",
            return_value=sentinel.http_client,
        ) as mock_http_client,
    ):
        OpenAICompatProvider(spec=spec)

    client_kwargs = mock_http_client.call_args.kwargs
    assert client_kwargs["limits"].keepalive_expiry == 0
    assert mock_async_openai.call_args.kwargs["http_client"] is sentinel.http_client


def test_handle_error_surfaces_chained_cause() -> None:
    """OpenAI ``APIConnectionError`` collapses every transport failure to
    the literal string ``"Connection error."``; the only way to see what
    actually broke (httpx ConnectError, RemoteProtocolError, SSL error,
    ...) is via ``__cause__``.  ``_handle_error`` must surface it so the
    user does not chase a phantom "connection error" when the real cause
    is e.g. a server-side disconnect.
    """
    underlying = RuntimeError("Server disconnected without sending a response")
    try:
        try:
            raise underlying
        except RuntimeError as inner:
            raise type("FakeConnectionError", (Exception,), {})("Connection error.") from inner
    except Exception as wrapped:
        result = OpenAICompatProvider._handle_error(wrapped)

    assert result.finish_reason == "error"
    assert "Connection error." in result.content
    assert "Server disconnected without sending a response" in result.content
    assert "RuntimeError" in result.content

