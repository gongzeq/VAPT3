"""WebSocket server channel: secbot acts as a WebSocket server and serves connected clients."""

from __future__ import annotations

import asyncio
import base64
import binascii
import email.utils
import hashlib
import hmac
import http
import json
import mimetypes
import re
import secrets
import shutil
import ssl
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger
from pydantic import Field, field_validator, model_validator
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from secbot.bus.events import OutboundMessage
from secbot.bus.queue import MessageBus
from secbot.channels.base import BaseChannel
from secbot.command.builtin import builtin_command_palette
from secbot.config.paths import get_media_dir
from secbot.config.schema import Base
from secbot.utils.helpers import safe_filename
from secbot.utils.media_decode import (
    FileSizeExceeded,
    save_base64_data_url,
)

if TYPE_CHECKING:
    from secbot.agent.subagent import SubagentManager
    from secbot.agents.registry import AgentRegistry
    from secbot.session.manager import SessionManager


def _strip_trailing_slash(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path or "/"


def _normalize_config_path(path: str) -> str:
    return _strip_trailing_slash(path)


def _append_buttons_as_text(text: str, buttons: list[list[str]]) -> str:
    labels = [label for row in buttons for label in row if label]
    if not labels:
        return text
    fallback = "\n".join(f"{index}. {label}" for index, label in enumerate(labels, 1))
    return f"{text}\n\n{fallback}" if text else fallback


# Display names for dashboard aggregation buckets. Kept server-side so the
# webui never has to ship a category→label dictionary (see
# dashboard-aggregation.md §2.3 / §2.4).
_VULN_CATEGORY_DISPLAY: dict[str, str] = {
    "injection": "注入",
    "auth": "认证缺陷",
    "xss": "XSS",
    "misconfig": "配置错误",
    "exposure": "敏感数据暴露",
    "weak_password": "弱口令",
    "cve": "CVE",
    "other": "其他",
}

# Main distribution order — always emitted, even with zero counts. ``cve`` and
# ``weak_password`` are appended only when their combined total ≥ 5 (spec §2.3
# anti-clutter rule); below that threshold they fold into ``other``.
_VULN_DISTRIBUTION_MAIN: tuple[str, ...] = (
    "injection",
    "auth",
    "xss",
    "misconfig",
    "exposure",
    "other",
)
_VULN_DISTRIBUTION_OPTIONAL: tuple[str, ...] = ("cve", "weak_password")
_VULN_FOLD_THRESHOLD = 5

_ASSET_TYPE_DISPLAY: dict[str, str] = {
    "web_app": "Web 应用",
    "api": "API 端点",
    "database": "数据库",
    "server": "服务器",
    "network": "网络设备",
    "other": "其他",
}
_ASSET_TYPE_ORDER: tuple[str, ...] = (
    "web_app",
    "api",
    "database",
    "server",
    "network",
    "other",
)

# WS broadcast throttle: at most 1 event / 1s per (event_name, scope_key). Per
# dashboard-aggregation.md §3.1.
_BROADCAST_MIN_INTERVAL_S = 1.0


class WebSocketConfig(Base):
    """WebSocket server channel configuration.

    Clients connect with URLs like ``ws://{host}:{port}{path}?client_id=...&token=...``.
    - ``client_id``: Used for ``allow_from`` authorization; if omitted, a value is generated and logged.
    - ``token``: If non-empty, the ``token`` query param may match this static secret; short-lived tokens
      from ``token_issue_path`` are also accepted.
    - ``token_issue_path``: If non-empty, **GET** (HTTP/1.1) to this path returns JSON
      ``{"token": "...", "expires_in": <seconds>}``; use ``?token=...`` when opening the WebSocket.
      Must differ from ``path`` (the WS upgrade path). If the client runs in the **same process** as
      secbot and shares the asyncio loop, use a thread or async HTTP client for GET—do not call
      blocking ``urllib`` or synchronous ``httpx`` from inside a coroutine.
    - ``token_issue_secret``: If non-empty, token requests must send ``Authorization: Bearer <secret>`` or
      ``X-Secbot-Auth: <secret>``.
    - ``websocket_requires_token``: If True, the handshake must include a valid token (static or issued and not expired).
    - Each connection has its own session: a unique ``chat_id`` maps to the agent session internally.
    - ``media`` field in outbound messages contains local filesystem paths; remote clients need a
      shared filesystem or an HTTP file server to access these files.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/"
    token: str = ""
    token_issue_path: str = ""
    token_issue_secret: str = ""
    token_ttl_s: int = Field(default=300, ge=30, le=86_400)
    websocket_requires_token: bool = True
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    # Default 36 MB, upper 40 MB: supports up to 4 images at ~6 MB each after
    # client-side Worker normalization (see webui Composer). 4 × 6 MB × 1.37
    # (base64 overhead) + envelope framing stays under 36 MB; the 40 MB ceiling
    # leaves a small margin for sender slop without opening a DoS avenue.
    max_message_bytes: int = Field(default=37_748_736, ge=1024, le=41_943_040)
    ping_interval_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ping_timeout_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""

    @field_validator("path")
    @classmethod
    def path_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError('path must start with "/"')
        return _normalize_config_path(value)

    @field_validator("token_issue_path")
    @classmethod
    def token_issue_path_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not value.startswith("/"):
            raise ValueError('token_issue_path must start with "/"')
        return _normalize_config_path(value)

    @model_validator(mode="after")
    def token_issue_path_differs_from_ws_path(self) -> Self:
        if not self.token_issue_path:
            return self
        if _normalize_config_path(self.token_issue_path) == _normalize_config_path(self.path):
            raise ValueError("token_issue_path must differ from path (the WebSocket upgrade path)")
        return self

    @model_validator(mode="after")
    def wildcard_host_requires_auth(self) -> Self:
        if self.host not in ("0.0.0.0", "::"):
            return self
        if self.token.strip() or self.token_issue_secret.strip():
            return self
        raise ValueError(
            "host is 0.0.0.0 (all interfaces) but neither token nor "
            "token_issue_secret is set — set one to prevent unauthenticated access"
        )


def _http_json_response(data: dict[str, Any], *, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", "application/json; charset=utf-8"),
        ]
    )
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, headers, body)


def _read_webui_model_name() -> str | None:
    """Return the configured default model for readonly webui display."""
    try:
        from secbot.config.loader import load_config

        model = load_config().agents.defaults.model.strip()
        return model or None
    except Exception as e:
        logger.debug("webui bootstrap could not load model name: {}", e)
        return None


def _mask_api_key(key: str | None) -> str:
    """Return a display-safe representation of *key*.

    Keeps a short prefix/suffix so users can visually confirm which key is
    saved without exposing the secret. Shape: ``sk-****abcd``. Returns empty
    string when no key is configured.
    """
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}****{key[-4:]}"


def _parse_request_path(path_with_query: str) -> tuple[str, dict[str, list[str]]]:
    """Parse normalized path and query parameters in one pass.

    ``keep_blank_values=True`` preserves explicitly empty values (``?foo=``) so
    callers can distinguish "key absent" from "key empty" — used by
    ``/api/settings/update`` for tri-state semantics (absent = keep,
    empty = clear, value = set).
    """
    parsed = urlparse("ws://x" + path_with_query)
    path = _strip_trailing_slash(parsed.path or "/")
    return path, parse_qs(parsed.query, keep_blank_values=True)


def _normalize_http_path(path_with_query: str) -> str:
    """Return the path component (no query string), with trailing slash normalized (root stays ``/``)."""
    return _parse_request_path(path_with_query)[0]


def _parse_query(path_with_query: str) -> dict[str, list[str]]:
    return _parse_request_path(path_with_query)[1]


def _query_first(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for *key*, or None."""
    values = query.get(key)
    return values[0] if values else None


def _parse_inbound_payload(raw: str) -> str | None:
    """Parse a client frame into text; return None for empty or unrecognized content."""
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            for key in ("content", "text", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return None
        return None
    return text


# Accept UUIDs and short scoped keys like "unified:default". Keeps the capability
# namespace small enough to rule out path traversal / quote injection tricks.
_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")


def _is_valid_chat_id(value: Any) -> bool:
    return isinstance(value, str) and _CHAT_ID_RE.match(value) is not None


def _parse_envelope(raw: str) -> dict[str, Any] | None:
    """Return a typed envelope dict if the frame is a new-style JSON envelope, else None.

    A frame qualifies when it parses as a JSON object with a string ``type`` field.
    Legacy frames (plain text, or ``{"content": ...}`` without ``type``) return None;
    callers should fall back to :func:`_parse_inbound_payload` for those.
    """
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    t = data.get("type")
    if not isinstance(t, str):
        return None
    return data


# Per-message media limits. The server-side guard is a touch looser than the
# client's ``Worker`` normalization target (6 MB) — tolerate client slop, but
# still cap total ingress at ``_MAX_IMAGES_PER_MESSAGE * _MAX_IMAGE_BYTES``
# which fits comfortably inside ``max_message_bytes``.
_MAX_IMAGES_PER_MESSAGE = 4
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_VIDEOS_PER_MESSAGE = 1
_MAX_VIDEO_BYTES = 20 * 1024 * 1024

# Image MIME whitelist — matches the Composer's ``accept`` list. SVG is
# explicitly excluded to avoid the XSS surface inside embedded scripts.
_IMAGE_MIME_ALLOWED: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

_VIDEO_MIME_ALLOWED: frozenset[str] = frozenset({
    "video/mp4",
    "video/webm",
    "video/quicktime",
})

_UPLOAD_MIME_ALLOWED: frozenset[str] = _IMAGE_MIME_ALLOWED | _VIDEO_MIME_ALLOWED

_DATA_URL_MIME_RE = re.compile(r"^data:([^;]+);base64,", re.DOTALL)


def _extract_data_url_mime(url: str) -> str | None:
    """Return the MIME type of a ``data:<mime>;base64,...`` URL, else ``None``."""
    if not isinstance(url, str):
        return None
    m = _DATA_URL_MIME_RE.match(url)
    if not m:
        return None
    return m.group(1).strip().lower() or None


_LOCALHOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Matches the legacy chat-id pattern but allows file-system-safe stems too,
# so the API can address sessions whose keys came from non-WebSocket channels.
_API_KEY_RE = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")


def _decode_api_key(raw_key: str) -> str | None:
    """Decode a percent-encoded API path segment, then validate the result."""
    key = unquote(raw_key)
    if _API_KEY_RE.match(key) is None:
        return None
    return key


def _is_localhost(connection: Any) -> bool:
    """Return True if *connection* originated from the loopback interface."""
    addr = getattr(connection, "remote_address", None)
    if not addr:
        return False
    host = addr[0] if isinstance(addr, tuple) else addr
    if not isinstance(host, str):
        return False
    # ``::ffff:127.0.0.1`` is loopback in IPv6-mapped form.
    if host.startswith("::ffff:"):
        host = host[7:]
    return host in _LOCALHOSTS


def _http_response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "text/plain; charset=utf-8",
    extra_headers: list[tuple[str, str]] | None = None,
) -> Response:
    headers = [
        ("Date", email.utils.formatdate(usegmt=True)),
        ("Connection", "close"),
        ("Content-Length", str(len(body))),
        ("Content-Type", content_type),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, Headers(headers), body)


def _http_error(status: int, message: str | None = None) -> Response:
    body = (message or http.HTTPStatus(status).phrase).encode("utf-8")
    return _http_response(body, status=status)


def _bearer_token(headers: Any) -> str | None:
    """Pull a Bearer token out of standard or query-style headers."""
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _is_websocket_upgrade(request: WsRequest) -> bool:
    """Detect an actual WS upgrade; plain HTTP GETs to the same path should fall through."""
    upgrade = request.headers.get("Upgrade") or request.headers.get("upgrade")
    connection = request.headers.get("Connection") or request.headers.get("connection")
    if not upgrade or "websocket" not in upgrade.lower():
        return False
    if not connection or "upgrade" not in connection.lower():
        return False
    return True


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 without padding — compact + friendly in URL paths."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Reverse of :func:`_b64url_encode`; caller handles ``ValueError``."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# Allowed MIME types we actually serve from the media endpoint. Anything
# outside this set is degraded to ``application/octet-stream`` so an
# attacker who somehow gets a signed URL for an unexpected file type can't
# trick the browser into sniffing executable content.
_MEDIA_ALLOWED_MIMES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
    "text/markdown",
})


def _issue_route_secret_matches(headers: Any, configured_secret: str) -> bool:
    """Return True if the token-issue HTTP request carries credentials matching ``token_issue_secret``."""
    if not configured_secret:
        return True
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
        return hmac.compare_digest(supplied, configured_secret)
    header_token = headers.get("X-Secbot-Auth") or headers.get("x-secbot-auth")
    if not header_token:
        return False
    return hmac.compare_digest(header_token.strip(), configured_secret)


class WebSocketChannel(BaseChannel):
    """Run a local WebSocket server; forward text/JSON messages to the message bus."""

    name = "websocket"
    display_name = "WebSocket"

    # Last-constructed channel instance, exposed via ``get_active_instance``.
    # The agent-loop hook (``secbot/agent/loop.py::_LoopHook``) has no direct
    # reference to the channel that initiated the turn — its ``channel`` kwarg
    # is just a string tag ("websocket" / "cli"). Rather than plumb a new
    # ``channel`` kwarg through ``AgentLoop.run``, we expose the singleton here
    # (same flavour as ``secbot/api/prompts.py::PromptsLoader`` and
    # ``secbot/channels/notifications.py::get_notification_queue``) so the
    # hook can look up the live instance on demand. Tests reset it via
    # ``reset_active_instance`` to stay isolated.
    _active_instance: "WebSocketChannel | None" = None

    def __init__(
        self,
        config: Any,
        bus: MessageBus,
        *,
        session_manager: "SessionManager | None" = None,
        static_dist_path: Path | None = None,
        subagent_manager: "SubagentManager | None" = None,
        agent_registry: "AgentRegistry | None" = None,
    ):
        if isinstance(config, dict):
            config = WebSocketConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebSocketConfig = config
        # chat_id -> connections subscribed to it (fan-out target).
        self._subs: dict[str, set[Any]] = {}
        # connection -> chat_ids it is subscribed to (O(1) cleanup on disconnect).
        self._conn_chats: dict[Any, set[str]] = {}
        # connection -> default chat_id for legacy frames that omit routing.
        self._conn_default: dict[Any, str] = {}
        # chat_ids whose turn is currently in flight on the backend. Populated
        # when the WebUI submits a ``message`` envelope and cleared as soon as
        # the matching ``turn_end`` is emitted (whether the turn finished
        # naturally or was aborted by ``/stop``). This is the authoritative
        # source of truth the WebUI uses to decide whether to render the
        # Stop button after a refresh or chat switch, replacing the older
        # ``hasPendingToolCalls`` heuristic that inspected persisted history.
        self._active_turns: set[str] = set()
        # Single-use tokens consumed at WebSocket handshake.
        self._issued_tokens: dict[str, float] = {}
        # Multi-use tokens for the embedded webui's REST surface; checked but not consumed.
        self._api_tokens: dict[str, float] = {}
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._session_manager = session_manager
        self._subagent_manager = subagent_manager
        self._agent_registry = agent_registry
        # Throttle state for WS broadcasts (per spec: 1 update / 1s per key).
        # Maps ``(event, scope)`` → monotonic timestamp of last emission.
        self._broadcast_last_emit: dict[tuple[str, str], float] = {}
        self._static_dist_path: Path | None = (
            static_dist_path.resolve() if static_dist_path is not None else None
        )
        # Process-local secret used to HMAC-sign media URLs. The signed URL is
        # the capability — anyone who holds a valid URL can fetch that one
        # file, nothing else. The secret regenerates on restart so links
        # become self-expiring (callers just refresh the session list).
        self._media_secret: bytes = secrets.token_bytes(32)
        # Register as the last-constructed instance so ``_LoopHook`` can find
        # us without taking a direct channel reference. Multiple channels in
        # the same process isn't a supported topology (``ChannelManager``
        # instantiates one per config) so clobbering is fine.
        WebSocketChannel._active_instance = self

    @classmethod
    def get_active_instance(cls) -> "WebSocketChannel | None":
        """Return the most-recently-constructed channel or ``None`` in tests."""
        return cls._active_instance

    @classmethod
    def reset_active_instance(cls) -> None:
        """Test helper: drop the cached singleton reference."""
        cls._active_instance = None

    # -- Subscription bookkeeping -------------------------------------------

    def _attach(self, connection: Any, chat_id: str) -> None:
        """Idempotently subscribe *connection* to *chat_id*."""
        self._subs.setdefault(chat_id, set()).add(connection)
        self._conn_chats.setdefault(connection, set()).add(chat_id)

    def _cleanup_connection(self, connection: Any) -> None:
        """Remove *connection* from every subscription set; safe to call multiple times."""
        chat_ids = self._conn_chats.pop(connection, set())
        for cid in chat_ids:
            subs = self._subs.get(cid)
            if subs is None:
                continue
            subs.discard(connection)
            if not subs:
                self._subs.pop(cid, None)
        self._conn_default.pop(connection, None)

    async def _send_event(self, connection: Any, event: str, **fields: Any) -> None:
        """Send a control event (attached, error, ...) to a single connection."""
        payload: dict[str, Any] = {"event": event}
        payload.update(fields)
        raw = json.dumps(payload, ensure_ascii=False)
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._cleanup_connection(connection)
        except Exception as e:
            self.logger.warning("failed to send {} event: {}", event, e)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebSocketConfig().model_dump(by_alias=True)

    def _expected_path(self) -> str:
        return _normalize_config_path(self.config.path)

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        cert = self.config.ssl_certfile.strip()
        key = self.config.ssl_keyfile.strip()
        if not cert and not key:
            return None
        if not cert or not key:
            raise ValueError(
                "ssl_certfile and ssl_keyfile must both be set for WSS, or both left empty"
            )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    _MAX_ISSUED_TOKENS = 10_000

    def _purge_expired_issued_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._issued_tokens.items()):
            if now > expiry:
                self._issued_tokens.pop(token_key, None)

    def _take_issued_token_if_valid(self, token_value: str | None) -> bool:
        """Validate and consume one issued token (single use per connection attempt).

        Uses single-step pop to minimize the window between lookup and removal;
        safe under asyncio's single-threaded cooperative model.
        """
        if not token_value:
            return False
        self._purge_expired_issued_tokens()
        expiry = self._issued_tokens.pop(token_value, None)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            return False
        return True

    def _handle_token_issue_http(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            self.logger.warning(
                "token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        self._purge_expired_issued_tokens()
        if len(self._issued_tokens) >= self._MAX_ISSUED_TOKENS:
            self.logger.error(
                "too many outstanding issued tokens ({}), rejecting issuance",
                len(self._issued_tokens),
            )
            return _http_json_response({"error": "too many outstanding tokens"}, status=429)
        token_value = f"nbwt_{secrets.token_urlsafe(32)}"
        self._issued_tokens[token_value] = time.monotonic() + float(self.config.token_ttl_s)

        return _http_json_response(
            {"token": token_value, "expires_in": self.config.token_ttl_s}
        )

    # -- HTTP dispatch ------------------------------------------------------

    async def _dispatch_http(self, connection: Any, request: WsRequest) -> Any:
        """Route an inbound HTTP request to a handler or to the WS upgrade path."""
        got, query = _parse_request_path(request.path)

        # 1. Token issue endpoint (legacy, optional, gated by configured secret).
        if self.config.token_issue_path:
            issue_expected = _normalize_config_path(self.config.token_issue_path)
            if got == issue_expected:
                return self._handle_token_issue_http(connection, request)

        # 2. WebUI bootstrap: mints tokens for the embedded UI.
        if got == "/webui/bootstrap":
            return self._handle_webui_bootstrap(connection, request)

        # 3. REST surface for the embedded UI.
        if got == "/api/sessions":
            return self._handle_sessions_list(request)

        if got == "/api/settings":
            return self._handle_settings(request)

        if got == "/api/commands":
            return self._handle_commands(request)

        if got == "/api/settings/update":
            return self._handle_settings_update(request)

        if got == "/api/settings/models":
            return await self._handle_settings_models(request)

        # Dashboard aggregation endpoints (see
        # .trellis/spec/backend/dashboard-aggregation.md). All read-only,
        # filtered by the local ``actor_id``. Missing DB data yields zeroed
        # responses, never 500.
        if got == "/api/dashboard/summary":
            return await self._handle_dashboard_summary(request)

        if got == "/api/dashboard/vuln-trend":
            return await self._handle_dashboard_vuln_trend(request)

        if got == "/api/dashboard/vuln-distribution":
            return await self._handle_dashboard_vuln_distribution(request)

        if got == "/api/dashboard/asset-distribution":
            return await self._handle_dashboard_asset_distribution(request)

        if got == "/api/dashboard/asset-cluster":
            return await self._handle_dashboard_asset_cluster(request)

        # Report metadata surface (spec: `.trellis/spec/backend/report-meta.md`).
        # List + single-row detail endpoints read from the ``report_meta`` table
        # populated by the report skill handlers.
        if got == "/api/reports":
            return await self._handle_reports_list(request)

        m = re.match(r"^/api/reports/([^/]+)$", got)
        if m:
            return await self._handle_report_detail(request, m.group(1))

        # Expert-agent registry + optional runtime status. Backwards compatible
        # when called without ``include_status=true``.
        if got == "/api/agents":
            return self._handle_agents(request)

        # Quick-command prompts (P1/R3). Spec:
        # `.trellis/spec/backend/prompts-config.md`. YAML-backed, hot-reloaded
        # on mtime change, never 500 — see secbot/api/prompts.py for the
        # resolution order and fallback behaviour.
        if got == "/api/prompts":
            return self._handle_prompts(request)

        # Notification center (P2/R1). In-memory ring buffer backed by
        # :mod:`secbot.channels.notifications`. ``/read-all`` MUST be matched
        # BEFORE the ``/{id}/read`` regex — else ``read-all`` would be parsed
        # as an id of ``read-all``. All three endpoints are GET due to the
        # same ``websockets`` HTTP parser constraint documented on ``/delete``
        # and ``/archive`` above.
        if got == "/api/notifications":
            return self._handle_notifications_list(request)

        if got == "/api/notifications/read-all":
            return self._handle_notifications_read_all(request)

        m = re.match(r"^/api/notifications/([^/]+)/read$", got)
        if m:
            return self._handle_notification_read(request, m.group(1))

        # Activity event stream (P2/R2). Rolling 5-minute window by default;
        # ``?since=<ISO-8601>`` narrows the window, ``?limit=<1..500>``
        # clamps the response. Shares the singleton style with notifications.
        if got == "/api/events":
            return self._handle_events_list(request)

        m = re.match(r"^/api/sessions/([^/]+)/messages$", got)
        if m:
            return self._handle_session_messages(request, m.group(1))

        # NOTE: websockets' HTTP parser only accepts GET, so we cannot expose a
        # true ``DELETE`` verb. The action is folded into the path instead.
        m = re.match(r"^/api/sessions/([^/]+)/delete$", got)
        if m:
            return self._handle_session_delete(request, m.group(1))

        # Archive toggle (P1/R2). Same GET-only constraint as ``/delete`` —
        # the desired archived state rides on ``?archived=0|1`` instead of a
        # JSON body. Idempotent and scoped to websocket: sessions.
        m = re.match(r"^/api/sessions/([^/]+)/archive$", got)
        if m:
            return self._handle_session_archive(request, m.group(1))

        # Signed media fetch: ``<sig>`` is an HMAC over ``<payload>``; the
        # payload decodes to a path inside :func:`get_media_dir`. See
        # :meth:`_sign_media_path` for the inverse direction used to build
        # these URLs when replaying a session.
        m = re.match(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self._handle_media_fetch(m.group(1), m.group(2))

        # 4. WebSocket upgrade (the channel's primary purpose). Only run the
        # handshake gate on requests that actually ask to upgrade; otherwise
        # a bare ``GET /`` from the browser would be rejected as an
        # unauthorized WS handshake instead of serving the SPA's index.html.
        expected_ws = self._expected_path()
        if got == expected_ws and _is_websocket_upgrade(request):
            client_id = _query_first(query, "client_id") or ""
            if len(client_id) > 128:
                client_id = client_id[:128]
            if not self.is_allowed(client_id):
                return connection.respond(403, "Forbidden")
            return self._authorize_websocket_handshake(connection, query)

        # 5. Static SPA serving (only if a build directory was wired in).
        if self._static_dist_path is not None:
            response = self._serve_static(got)
            if response is not None:
                return response

        return connection.respond(404, "Not Found")

    # -- HTTP route handlers ------------------------------------------------

    def _check_api_token(self, request: WsRequest) -> bool:
        """Validate a request against the API token pool (multi-use, TTL-bound)."""
        self._purge_expired_api_tokens()
        token = _bearer_token(request.headers) or _query_first(
            _parse_query(request.path), "token"
        )
        if not token:
            return False
        expiry = self._api_tokens.get(token)
        if expiry is None or time.monotonic() > expiry:
            self._api_tokens.pop(token, None)
            return False
        return True

    def _purge_expired_api_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._api_tokens.items()):
            if now > expiry:
                self._api_tokens.pop(token_key, None)

    def _handle_webui_bootstrap(self, connection: Any, request: Any) -> Response:
        # When a secret is configured (token_issue_secret or static token),
        # validate it regardless of source IP.  This secures deployments
        # behind a reverse proxy where all connections appear as localhost.
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return _http_error(401, "Unauthorized")
        elif not _is_localhost(connection):
            # No secret configured: only allow localhost (local dev mode).
            return _http_error(403, "webui bootstrap is localhost-only")
        # Cap outstanding tokens to avoid runaway growth from a misbehaving client.
        self._purge_expired_issued_tokens()
        self._purge_expired_api_tokens()
        if (
            len(self._issued_tokens) >= self._MAX_ISSUED_TOKENS
            or len(self._api_tokens) >= self._MAX_ISSUED_TOKENS
        ):
            return _http_response(
                json.dumps({"error": "too many outstanding tokens"}).encode("utf-8"),
                status=429,
                content_type="application/json; charset=utf-8",
            )
        token = f"nbwt_{secrets.token_urlsafe(32)}"
        expiry = time.monotonic() + float(self.config.token_ttl_s)
        # Same string registered in both pools: the WS handshake consumes one copy
        # while the REST surface keeps validating the other until TTL expiry.
        self._issued_tokens[token] = expiry
        self._api_tokens[token] = expiry
        return _http_json_response(
            {
                "token": token,
                "ws_path": self._expected_path(),
                "expires_in": self.config.token_ttl_s,
                "model_name": _read_webui_model_name(),
            }
        )

    def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        sessions = self._session_manager.list_sessions()
        # The webui is only meaningful for websocket-channel chats — CLI /
        # Slack / Lark / Discord sessions can't be resumed from the browser,
        # so leaking them into the sidebar is just noise. Filter to the
        # ``websocket:`` prefix and strip absolute paths on the way out.
        cleaned = [
            {k: v for k, v in s.items() if k != "path"}
            for s in sessions
            if isinstance(s.get("key"), str) and s["key"].startswith("websocket:")
        ]

        # R2 extensions (P1). Existing clients that don't pass any of ``q /
        # archived / limit / offset`` still see the original response shape —
        # we only *add* a ``total`` field and per-row ``archived`` (which is
        # already injected upstream by SessionManager.list_sessions).
        query = _parse_query(request.path)
        q = (_query_first(query, "q") or "").strip().lower()
        archived_raw = _query_first(query, "archived")
        try:
            limit = int(_query_first(query, "limit") or "50")
            offset = int(_query_first(query, "offset") or "0")
        except ValueError:
            return _http_error(400, "limit/offset must be integers")
        # Cap ``limit`` to keep responses bounded; mirrors /api/reports.
        limit = max(0, min(limit, 500))
        offset = max(0, offset)

        # ``archived`` filter: ``0`` → only un-archived, ``1`` → only archived,
        # anything else (including missing) → all rows. Treating missing as
        # "all" preserves the legacy response where archived rows were mixed
        # in with active ones.
        if archived_raw == "0":
            cleaned = [s for s in cleaned if not s.get("archived")]
        elif archived_raw == "1":
            cleaned = [s for s in cleaned if s.get("archived")]

        if q:
            def _match(row: dict[str, Any]) -> bool:
                hay = " ".join(
                    str(row.get(k) or "") for k in ("title", "preview", "key")
                ).lower()
                return q in hay
            cleaned = [s for s in cleaned if _match(s)]

        total = len(cleaned)
        if offset:
            cleaned = cleaned[offset:]
        if limit:
            cleaned = cleaned[:limit]

        return _http_json_response(
            {
                "sessions": cleaned,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def _settings_payload(self, *, requires_restart: bool = False) -> dict[str, Any]:
        from secbot.config.loader import get_config_path, load_config
        from secbot.providers.registry import PROVIDERS, find_by_name

        config = load_config()
        defaults = config.agents.defaults
        provider_name = config.get_provider_name(defaults.model) or defaults.provider
        provider = config.get_provider(defaults.model)
        selected_provider = provider_name
        if defaults.provider != "auto":
            spec = find_by_name(defaults.provider)
            selected_provider = spec.name if spec else provider_name
        # Mirror whichever provider slot AgentLoop will actually hit
        # (``providers.openai`` / ``providers.openrouter`` / ...) so the
        # baseUrl + apiKey already persisted in config.json show up in the UI
        # instead of forcing the user to re-enter them. Falls back to
        # ``providers.custom`` only on a blank / first-run config.
        custom = provider or config.providers.custom
        # Per-provider config snapshot: lets the UI swap Base URL / API Key
        # instantly when the Provider dropdown changes, without waiting for a
        # round-trip. ``default_api_base`` carries the spec fallback so the
        # UI can show e.g. ``https://api.deepseek.com`` even when the user
        # hasn't overridden ``api_base`` in config.
        provider_configs: dict[str, dict[str, Any]] = {}
        for spec in PROVIDERS:
            slot = getattr(config.providers, spec.name, None)
            if slot is None:
                continue
            provider_configs[spec.name] = {
                "api_base": slot.api_base or "",
                "default_api_base": spec.default_api_base or "",
                "api_key_masked": _mask_api_key(slot.api_key),
                "has_api_key": bool(slot.api_key),
            }
        return {
            "agent": {
                "model": defaults.model,
                "provider": selected_provider,
                "resolved_provider": provider_name,
                "has_api_key": bool(provider and provider.api_key),
            },
            "providers": [
                {"name": "auto", "label": "Auto"}
            ] + [
                {"name": spec.name, "label": spec.label}
                for spec in PROVIDERS
            ],
            "custom": {
                # Active provider slot — the one AgentLoop will hit on the
                # next turn. ``api_base`` is non-sensitive so we return it
                # plain; the key is masked (last 4 visible).
                "api_base": custom.api_base or "",
                "api_key_masked": _mask_api_key(custom.api_key),
                "has_api_key": bool(custom.api_key),
            },
            "provider_configs": provider_configs,
            "runtime": {
                "config_path": str(get_config_path().expanduser()),
            },
            # Hot reload is always available: AgentLoop re-reads config and
            # rebuilds the provider snapshot at the start of every turn.
            "requires_restart": False,
        }

    def _handle_settings(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(self._settings_payload())

    def _handle_commands(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response({"commands": builtin_command_palette()})

    def _handle_settings_update(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.config.loader import load_config, save_config
        from secbot.providers.registry import find_by_name

        query = _parse_query(request.path)
        config = load_config()
        defaults = config.agents.defaults
        changed = False

        model = _query_first(query, "model")
        if model is not None:
            model = model.strip()
            if not model:
                return _http_error(400, "model is required")
            if defaults.model != model:
                defaults.model = model
                changed = True

        provider = _query_first(query, "provider")
        if provider is not None:
            provider = provider.strip() or "auto"
            if provider != "auto" and find_by_name(provider) is None:
                return _http_error(400, "unknown provider")
            if defaults.provider != provider:
                defaults.provider = provider
                changed = True

        # Pick the target slot AFTER applying model/provider updates so the
        # write lands on the slot AgentLoop will now use. Pydantic models are
        # returned by reference, so assigning to ``custom.api_key`` mutates
        # the matching ``config.providers.<name>`` entry in place. Falls back
        # to ``providers.custom`` only when nothing else is configured.
        custom = config.get_provider(defaults.model) or config.providers.custom

        # ``api_base`` is non-sensitive — allowed in URL query.
        # Semantics: key absent = keep; empty string = clear; non-empty = set.
        api_base_raw = _query_first(query, "api_base")
        if api_base_raw is not None:
            new_api_base = api_base_raw.strip() or None
            if custom.api_base != new_api_base:
                custom.api_base = new_api_base
                changed = True

        # ``api_key`` is sensitive — MUST come via the custom request header
        # so it never lands in URL query strings, access logs, or browser
        # history. Same tri-state semantics as api_base.
        if "X-Settings-Api-Key" in request.headers:
            api_key_raw = request.headers.get("X-Settings-Api-Key") or ""
            new_api_key = api_key_raw.strip() or None
            if custom.api_key != new_api_key:
                custom.api_key = new_api_key
                changed = True

        if changed:
            save_config(config)
        return _http_json_response(self._settings_payload(requires_restart=changed))

    async def _handle_settings_models(self, request: WsRequest) -> Response:
        """List models from the user-supplied OpenAI-compatible endpoint.

        The client sends the draft ``api_base`` as a query param and the
        draft ``api_key`` via the ``X-Settings-Api-Key`` header (same
        channel as :meth:`_handle_settings_update` so the key never lands
        in URL query strings or access logs). If the header is absent we
        fall back to the persisted key so the user can re-query without
        re-entering an already-saved key.
        """
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.command.builtin import _fetch_openai_models
        from secbot.config.loader import load_config

        query = _parse_query(request.path)
        api_base = (_query_first(query, "api_base") or "").strip()
        if not api_base:
            return _http_error(400, "api_base is required")

        if "X-Settings-Api-Key" in request.headers:
            api_key = (request.headers.get("X-Settings-Api-Key") or "").strip()
        else:
            # Fall back to whichever provider slot is currently active, not
            # just ``providers.custom`` — otherwise a user whose key is saved
            # under e.g. ``providers.openai`` gets a spurious
            # ``api_key is required`` when clicking "Fetch models".
            cfg = load_config()
            slot = cfg.get_provider() or cfg.providers.custom
            api_key = (slot.api_key or "").strip()
        if not api_key:
            return _http_error(400, "api_key is required")

        try:
            ids = await _fetch_openai_models(api_base, api_key)
        except Exception as exc:
            return _http_error(502, f"failed to fetch models: {exc}")
        return _http_json_response({"models": ids})

    # -- Dashboard aggregation handlers -------------------------------------
    #
    # All dashboard endpoints share these invariants (spec
    # `.trellis/spec/backend/dashboard-aggregation.md`):
    #
    # - Require a valid API token (same pool as the rest of the webui REST
    #   surface).
    # - Read-only; operate on the single-tenant ``DEFAULT_ACTOR`` for now.
    # - On DB failure fall back to zeroed payload + 500 log, never leak
    #   internal errors to the browser.

    async def _handle_dashboard_summary(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        try:
            async with get_session() as session:
                counts = await repo.summary_counts(session, DEFAULT_ACTOR)
        except Exception:
            self.logger.exception("dashboard.summary: db error")
            return _http_error(500, "dashboard summary unavailable")

        # ``agents_online`` lives in-memory on the SubagentManager rather than
        # the CMDB (spec §2.1). Falling back to zero keeps the endpoint usable
        # before the manager is wired in.
        agents_online = 0
        if self._subagent_manager is not None:
            try:
                agents_online = len(self._subagent_manager._task_statuses)
            except Exception:
                agents_online = 0

        payload: dict[str, Any] = dict(counts)
        payload["agents_online"] = {"value": agents_online, "delta": 0}
        # ISO 8601 with timezone offset so the client can parse without
        # guessing UTC vs local. Matches dashboard-aggregation.md §2.1 sample.
        now_local = datetime.now().astimezone()
        payload["generated_at"] = now_local.isoformat(timespec="seconds")
        return _http_json_response(payload)

    async def _handle_dashboard_vuln_trend(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        query = _parse_query(request.path)
        range_ = (_query_first(query, "range") or "30d").strip() or "30d"
        try:
            async with get_session() as session:
                data = await repo.vuln_trend(session, DEFAULT_ACTOR, range_=range_)
        except ValueError as exc:
            # Unknown ``?range=`` value — surface a 400, not 500.
            return _http_error(400, str(exc))
        except Exception:
            self.logger.exception("dashboard.vuln_trend: db error")
            return _http_error(500, "vuln trend unavailable")
        return _http_json_response(data)

    async def _handle_dashboard_vuln_distribution(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        try:
            async with get_session() as session:
                counts = await repo.vuln_distribution(session, DEFAULT_ACTOR)
        except Exception:
            self.logger.exception("dashboard.vuln_distribution: db error")
            return _http_error(500, "vuln distribution unavailable")

        cve_total = counts.get("cve", 0) + counts.get("weak_password", 0)
        fold_into_other = cve_total < _VULN_FOLD_THRESHOLD

        buckets: list[dict[str, Any]] = []
        for cat in _VULN_DISTRIBUTION_MAIN:
            count = counts.get(cat, 0)
            if cat == "other" and fold_into_other:
                count += cve_total
            buckets.append(
                {
                    "category": cat,
                    "name": _VULN_CATEGORY_DISPLAY[cat],
                    "count": int(count),
                }
            )
        if not fold_into_other:
            for cat in _VULN_DISTRIBUTION_OPTIONAL:
                buckets.append(
                    {
                        "category": cat,
                        "name": _VULN_CATEGORY_DISPLAY[cat],
                        "count": int(counts.get(cat, 0)),
                    }
                )
        return _http_json_response({"buckets": buckets})

    async def _handle_dashboard_asset_distribution(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        try:
            async with get_session() as session:
                counts = await repo.asset_type_distribution(session, DEFAULT_ACTOR)
        except Exception:
            self.logger.exception("dashboard.asset_distribution: db error")
            return _http_error(500, "asset distribution unavailable")

        buckets = [
            {
                "type": t,
                "name": _ASSET_TYPE_DISPLAY[t],
                "count": int(counts.get(t, 0)),
            }
            for t in _ASSET_TYPE_ORDER
        ]
        return _http_json_response({"buckets": buckets})

    async def _handle_dashboard_asset_cluster(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        try:
            async with get_session() as session:
                cluster = await repo.asset_cluster(session, DEFAULT_ACTOR)
        except Exception:
            self.logger.exception("dashboard.asset_cluster: db error")
            return _http_error(500, "asset cluster unavailable")

        clusters = [
            {
                "system": system,
                "high": int(levels.get("high", 0)),
                "medium": int(levels.get("medium", 0)),
                "low": int(levels.get("low", 0)),
            }
            for system, levels in cluster.items()
        ]
        return _http_json_response({"clusters": clusters})

    # -- Report metadata surface --------------------------------------------
    #
    # Spec: `.trellis/spec/backend/report-meta.md`. The table is populated by
    # report skill handlers (markdown/docx/pdf); these two HTTP endpoints are
    # read-only, ``actor_id``-scoped, and surface the list + single-row detail
    # consumed by the dashboard's "Recent Reports" module.

    def _serialise_report_row(
        self, row: Any, *, include_download_url: bool
    ) -> dict[str, Any]:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        payload: dict[str, Any] = {
            "id": row.id,
            "scan_id": row.scan_id,
            "title": row.title,
            "type": row.type,
            "status": row.status,
            "critical_count": int(row.critical_count or 0),
            "author": row.author,
            "created_at": created_at.astimezone().isoformat(timespec="seconds"),
        }
        if include_download_url:
            # Detail endpoint exposes the download route even when no file is
            # attached; 404 surfaces later at fetch time.
            payload["download_url"] = f"/api/reports/{row.id}/download"
        return payload

    async def _handle_reports_list(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        query = _parse_query(request.path)
        range_ = (_query_first(query, "range") or "30d").strip() or "30d"
        type_ = _query_first(query, "type") or None
        status = _query_first(query, "status") or None

        try:
            limit = int(_query_first(query, "limit") or "50")
            offset = int(_query_first(query, "offset") or "0")
        except ValueError:
            return _http_error(400, "limit/offset must be integers")
        # Cap ``limit`` at a generous but finite value to keep responses bounded.
        limit = max(0, min(limit, 500))
        offset = max(0, offset)

        try:
            async with get_session() as session:
                rows, total = await repo.list_reports(
                    session,
                    DEFAULT_ACTOR,
                    range_=range_,
                    type=type_,
                    status=status,
                    limit=limit,
                    offset=offset,
                )
        except ValueError as exc:
            return _http_error(400, str(exc))
        except Exception:
            self.logger.exception("reports.list: db error")
            return _http_error(500, "reports unavailable")

        items = [
            self._serialise_report_row(r, include_download_url=False) for r in rows
        ]
        return _http_json_response(
            {"items": items, "total": total, "limit": limit, "offset": offset}
        )

    async def _handle_report_detail(
        self, request: WsRequest, report_id: str
    ) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from secbot.cmdb import repo
        from secbot.cmdb.db import get_session
        from secbot.cmdb.models import DEFAULT_ACTOR

        try:
            async with get_session() as session:
                row = await repo.get_report(session, DEFAULT_ACTOR, report_id)
        except Exception:
            self.logger.exception("reports.detail: db error")
            return _http_error(500, "report unavailable")
        if row is None:
            return _http_error(404, "report not found")
        return _http_json_response(
            self._serialise_report_row(row, include_download_url=True)
        )

    # -- Agent registry + runtime status ------------------------------------

    def _handle_agents(self, request: WsRequest) -> Response:
        """Expose expert-agent registry; optionally append runtime status.

        Without ``?include_status=true``, returns the static registry payload
        (see dashboard-aggregation.md §2.6). With the flag, each entry is
        enriched with ``status / current_task_id / progress / last_heartbeat_at``.
        When the :class:`SubagentManager` is not attached, every agent reports
        ``offline`` — an explicit fallback called out in the spec, so the
        surface stays stable even before the manager wiring lands.
        """

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        registry = self._load_agent_registry_cached()
        agents_payload: list[dict[str, Any]] = []
        for spec in registry:
            agents_payload.append(
                {
                    "name": spec.name,
                    "display_name": spec.display_name,
                    "description": spec.description,
                    "scoped_skills": list(spec.scoped_skills),
                    # PR3 availability contract: required/missing binaries
                    # default to empty tuples when the registry is loaded
                    # without ``skills_root``; ``available`` then stays True.
                    "available": spec.available,
                    "required_binaries": list(spec.required_binaries),
                    "missing_binaries": list(spec.missing_binaries),
                }
            )

        query = _parse_query(request.path)
        include_status_raw = (_query_first(query, "include_status") or "").lower()
        include_status = include_status_raw in {"1", "true", "yes"}
        if include_status:
            for entry in agents_payload:
                entry.update(
                    {
                        "status": "offline",
                        "current_task_id": None,
                        "progress": None,
                        "last_heartbeat_at": None,
                    }
                )
        return _http_json_response({"agents": agents_payload})

    def _load_agent_registry_cached(self) -> "AgentRegistry":
        """Return the injected registry, or lazy-load from ``secbot/agents/``.

        Production initialisation is expected to inject an ``AgentRegistry``
        through ``ChannelManager``. Tests and ad-hoc runs fall back to a
        filesystem load — tolerating a missing / broken directory by returning
        an empty registry rather than 500 (spec §2.6 permits empty list).
        """

        if self._agent_registry is not None:
            return self._agent_registry
        try:
            from secbot.agents.registry import AgentRegistry, load_agent_registry

            # Repo layout: ``secbot/agents/*.yaml``. Resolve from this module.
            agents_dir = Path(__file__).resolve().parents[1] / "agents"
            skills_dir = Path(__file__).resolve().parents[1] / "skills"
            if not agents_dir.is_dir():
                self._agent_registry = AgentRegistry()
            else:
                # ``skill_names=None`` skips scoped-skill cross-checking; we
                # only need display metadata here, not tool-surface generation.
                # ``skills_root`` is passed so the payload can advertise
                # per-agent binary availability (PR3 §/api/agents contract).
                self._agent_registry = load_agent_registry(
                    agents_dir,
                    skill_names=None,
                    skills_root=skills_dir if skills_dir.is_dir() else None,
                )
        except Exception:
            # Any registry error MUST NOT bring down the dashboard — the UI
            # surfaces an empty agents list if the YAMLs are missing or
            # invalid. Logs carry the detail for operators.
            self.logger.exception("failed to load agent registry; returning empty")
            from secbot.agents.registry import AgentRegistry

            self._agent_registry = AgentRegistry()
        return self._agent_registry

    # -- Quick-command prompts ---------------------------------------------

    def _handle_prompts(self, request: WsRequest) -> Response:
        """Return the quick-command prompts list.

        Spec: ``.trellis/spec/backend/prompts-config.md``. Never 500 — any
        YAML failure falls back to the last cached value or an empty list so
        the frontend chip row stays stable.
        """
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        try:
            from secbot.api.prompts import load_prompts

            prompts = load_prompts()
        except Exception:
            self.logger.exception("prompts: unexpected load failure; serving empty")
            prompts = []
        return _http_json_response({"prompts": prompts})

    # ------------------------------------------------------------------
    # Notification center (P2/R1)
    # ------------------------------------------------------------------
    def _handle_notifications_list(self, request: WsRequest) -> Response:
        """List notifications from the in-memory ring buffer.

        Query params:
          * ``unread=0|1`` — filter by read flag (absent = all)
          * ``limit`` — 0..500, default 50
          * ``offset`` — >=0, default 0

        Response shape mirrors P1 R2 ``/api/sessions`` pagination
        (``items / total / limit / offset``) with an extra ``unread_count``
        for the Navbar bell badge. ``unread_count`` is computed over the
        whole queue *before* the ``unread`` filter — the badge must reflect
        the full tray regardless of which tab the UI is currently showing.
        """
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        from secbot.channels.notifications import get_notification_queue

        query = _parse_query(request.path)
        unread_raw = _query_first(query, "unread")
        try:
            limit = int(_query_first(query, "limit") or "50")
            offset = int(_query_first(query, "offset") or "0")
        except ValueError:
            return _http_error(400, "limit/offset must be integers")
        limit = max(0, min(limit, 500))
        offset = max(0, offset)

        queue = get_notification_queue()
        all_items = queue.snapshot()
        unread_count = sum(1 for entry in all_items if not entry["read"])

        if unread_raw == "1":
            filtered = [entry for entry in all_items if not entry["read"]]
        elif unread_raw == "0":
            filtered = [entry for entry in all_items if entry["read"]]
        else:
            filtered = all_items
        total = len(filtered)

        if offset:
            filtered = filtered[offset:]
        if limit:
            filtered = filtered[:limit]

        return _http_json_response(
            {
                "items": filtered,
                "total": total,
                "limit": limit,
                "offset": offset,
                "unread_count": unread_count,
            }
        )

    def _handle_notification_read(self, request: WsRequest, notification_id: str) -> Response:
        """Mark a single notification as read. 404 when id is unknown."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        from secbot.channels.notifications import get_notification_queue

        queue = get_notification_queue()
        updated = queue.mark_read(notification_id)
        if updated is None:
            return _http_error(404, "notification not found")
        return _http_json_response({"id": notification_id, "read": True})

    def _handle_notifications_read_all(self, request: WsRequest) -> Response:
        """Mark every unread notification as read. Idempotent — returns the
        count of rows actually flipped this call (``0`` when already clean)."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        from secbot.channels.notifications import get_notification_queue

        queue = get_notification_queue()
        updated = queue.mark_all_read()
        return _http_json_response({"updated": updated})

    # ------------------------------------------------------------------
    # Activity event stream (P2/R2)
    # ------------------------------------------------------------------
    def _handle_events_list(self, request: WsRequest) -> Response:
        """Return buffered activity events.

        Query params:
          * ``since`` — ISO-8601 timestamp; only events with
            ``timestamp >= since`` are returned. Accepts the same shapes
            Python's ``datetime.fromisoformat`` accepts, including the
            ``+08:00`` offset the agent loop emits. Invalid input → 400.
          * ``limit`` — 1..500, default 50.

        When ``since`` is omitted, the buffer's default 5-minute window
        applies (see :data:`DEFAULT_EVENTS_WINDOW_SECONDS`).
        """
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        from secbot.channels.notifications import get_event_buffer

        query = _parse_query(request.path)
        since_raw = (_query_first(query, "since") or "").strip()
        try:
            limit = int(_query_first(query, "limit") or "50")
        except ValueError:
            return _http_error(400, "limit must be an integer")
        limit = max(1, min(limit, 500))

        since_dt = None
        if since_raw:
            # URL decoding drops the '+' in ``+08:00`` offsets unless the
            # caller pre-encoded it to ``%2B``; ``parse_qs`` then hands us
            # a space in its place. Normalise before parsing so both forms
            # are accepted.
            normalised = since_raw.replace(" ", "+")
            try:
                since_dt = datetime.fromisoformat(normalised)
            except ValueError:
                return _http_error(400, "since must be an ISO-8601 timestamp")

        items = get_event_buffer().filter(since=since_dt, limit=limit)
        return _http_json_response({"items": items})

    # -- WebSocket event broadcasts (task_update / blackboard_update) -------

    def _should_throttle_broadcast(self, event: str, scope: str) -> bool:
        """Return True when the caller must drop this broadcast to respect 1/s.

        Side-effect: if it returns False (emission allowed), the last-emit
        timestamp is updated in place. This keeps the caller branch-free.
        """

        now = time.monotonic()
        key = (event, scope)
        last = self._broadcast_last_emit.get(key)
        if last is not None and (now - last) < _BROADCAST_MIN_INTERVAL_S:
            return True
        self._broadcast_last_emit[key] = now
        return False

    async def broadcast_task_update(
        self,
        *,
        task_id: str,
        scan_id: str,
        status: str,
        progress: float | None = None,
        kpi: dict[str, Any] | None = None,
        chat_id: str | None = None,
    ) -> bool:
        """Emit a ``task_update`` frame to every (or one) subscriber.

        Returns True when the frame was dispatched, False when throttled /
        there were no subscribers. Throttle scope is per-``task_id``.
        """

        if self._should_throttle_broadcast("task_update", task_id):
            return False
        body: dict[str, Any] = {
            "event": "task_update",
            "task_id": task_id,
            "scan_id": scan_id,
            "status": status,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if progress is not None:
            body["progress"] = float(progress)
        if kpi:
            body["kpi"] = dict(kpi)
        return await self._broadcast_frame(body, chat_id=chat_id)

    async def broadcast_blackboard_update(
        self,
        *,
        chat_id: str,
        stats: dict[str, Any],
    ) -> bool:
        """Emit a ``blackboard_update`` frame scoped to ``chat_id``.

        Throttle scope is per-``chat_id``. Returns True on dispatch, False when
        throttled or no subscribers.
        """

        if self._should_throttle_broadcast("blackboard_update", chat_id):
            return False
        body = {
            "event": "blackboard_update",
            "chat_id": chat_id,
            "stats": dict(stats),
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        return await self._broadcast_frame(body, chat_id=chat_id)

    async def broadcast_activity_event(
        self,
        *,
        category: str,
        agent: str,
        step: str,
        chat_id: str,
        duration_ms: int | None = None,
    ) -> bool:
        """Emit an ``activity_event`` frame scoped to ``chat_id``.

        Contract: see ``.trellis/tasks/05-10-p2-notification-activity/prd.md``
        §5 (WebSocket event). Throttle scope is per-``chat_id`` — agents can
        burst several tool-calls per second but the dashboard only needs one
        point per second per conversation.
        """

        if self._should_throttle_broadcast("activity_event", chat_id):
            return False
        body: dict[str, Any] = {
            "event": "activity_event",
            "chat_id": chat_id,
            "category": category,
            "agent": agent,
            "step": step,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if duration_ms is not None:
            body["duration_ms"] = int(duration_ms)
        return await self._broadcast_frame(body, chat_id=chat_id)

    async def broadcast_agent_event(
        self,
        *,
        chat_id: str,
        type: str,
        payload: dict[str, Any],
    ) -> bool:
        """Emit a unified ``agent_event`` frame scoped to ``chat_id``.

        This is the single wire format for thought, subagent lifecycle,
        and blackboard entry events.  Consumers on the chat surface
        receive it via the per-chat dispatch path, so it scrolls inline
        with the conversation.

        Throttle policy is left to the caller; this method does NOT
        throttle so that high-signal events (first thought, subagent
        spawn/done) are never dropped.
        """
        body: dict[str, Any] = {
            "event": "agent_event",
            "chat_id": chat_id,
            "type": type,
            "payload": dict(payload),
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        return await self._broadcast_frame(body, chat_id=chat_id)

    async def _broadcast_frame(
        self, body: dict[str, Any], *, chat_id: str | None
    ) -> bool:
        """Serialise *body* and send to every connection, or a specific chat.

        When *chat_id* is supplied, only connections subscribed to that chat
        receive the frame (scoped events). Otherwise the frame fans out to
        every live connection (global events like dashboard KPI bumps).
        """

        if chat_id is not None:
            conns = list(self._subs.get(chat_id, ()))
        else:
            conns = list(self._conn_chats.keys())
        if not conns:
            return False
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=f" {body.get('event', '')} ")
        return True

    @staticmethod
    def _is_webui_session_key(key: str) -> bool:
        """Return True when *key* belongs to the webui's websocket-only surface."""
        return key.startswith("websocket:")

    def _handle_session_messages(self, request: WsRequest, key: str) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        # The embedded webui only understands websocket-channel sessions. Keep
        # its read surface aligned with ``/api/sessions`` instead of letting a
        # caller probe arbitrary CLI / Slack / Lark history by handcrafted URL.
        if not self._is_webui_session_key(decoded_key):
            return _http_error(404, "session not found")
        data = self._session_manager.read_session_file(decoded_key)
        if data is None:
            return _http_error(404, "session not found")
        # Decorate persisted user messages with signed media URLs so the
        # client can render previews. The raw on-disk ``media`` paths are
        # stripped on the way out — they leak server filesystem layout and
        # the client never needs them once it has the signed fetch URL.
        self._augment_media_urls(data)
        return _http_json_response(data)

    def _augment_media_urls(self, payload: dict[str, Any]) -> None:
        """Mutate *payload* in place: each message's ``media`` path list is
        replaced by a parallel ``media_urls`` list of signed fetch URLs.

        Messages without media or with non-string path entries are left
        untouched. Paths that no longer live inside ``media_dir`` (e.g. the
        file was deleted, or the dir was relocated) are silently skipped;
        the client falls back to the historical-replay placeholder tile.
        """
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            media = msg.get("media")
            if not isinstance(media, list) or not media:
                continue
            urls: list[dict[str, str]] = []
            for entry in media:
                if not isinstance(entry, str) or not entry:
                    continue
                signed = self._sign_media_path(Path(entry))
                if signed is None:
                    continue
                urls.append({"url": signed, "name": Path(entry).name})
            if urls:
                msg["media_urls"] = urls
            # Always drop the raw paths from the wire payload.
            msg.pop("media", None)

    def _sign_media_path(self, abs_path: Path) -> str | None:
        """Return a ``/api/media/<sig>/<payload>`` URL for *abs_path*, or
        ``None`` when the path does not resolve inside the media root.

        The URL is self-authenticating: the signature binds the payload to
        this process's ``_media_secret``, so only paths we chose to sign can
        be fetched. The returned path is relative to the server origin; the
        client joins it against the existing webui base.
        """
        try:
            media_root = get_media_dir().resolve()
            rel = abs_path.resolve().relative_to(media_root)
        except (OSError, ValueError):
            return None
        payload = _b64url_encode(rel.as_posix().encode("utf-8"))
        mac = hmac.new(
            self._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        return f"/api/media/{_b64url_encode(mac)}/{payload}"

    def stage_media_path(self, path: Path) -> Path | None:
        """Ensure *path* lives inside the media directory; return the staged path.

        Paths already resolvable under ``get_media_dir`` are returned as-is
        (no copy). Anything else is copied into the websocket media bucket so
        later signed fetch URLs can address the file without exposing arbitrary
        filesystem paths. Returns ``None`` when the file does not exist or the
        copy fails.

        Exposed so out-of-band writers (e.g. session history persistence for
        MessageTool deliveries) can pin a stable path before the live ``send``
        path stages its own copy.
        """
        try:
            abs_path = path.resolve()
            media_root = get_media_dir().resolve()
            abs_path.relative_to(media_root)
            return abs_path
        except (OSError, ValueError):
            pass
        try:
            if not path.is_file():
                return None
            media_dir = get_media_dir("websocket")
            safe_name = safe_filename(path.name) or "attachment"
            staged = media_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"
            shutil.copyfile(path, staged)
            return staged.resolve()
        except OSError as exc:
            self.logger.warning("failed to stage outbound media {}: {}", path, exc)
            return None

    def _sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        """Return a signed media URL payload for *path*.

        Persisted inbound media already lives under ``get_media_dir`` and can
        be signed directly. Outbound bot-generated files may live anywhere on
        disk; copy those into the websocket media bucket first so the browser
        can fetch them through the existing signed media route without
        exposing arbitrary filesystem paths.
        """
        staged = self.stage_media_path(path)
        if staged is None:
            return None
        signed = self._sign_media_path(staged)
        if signed is None:
            return None
        return {"url": signed, "name": path.name}

    def _handle_media_fetch(self, sig: str, payload: str) -> Response:
        """Serve a single media file previously signed via
        :meth:`_sign_media_path`. Validates the signature, decodes the
        payload to a relative path, and streams the file bytes with a
        long-lived immutable cache header (the URL already encodes the
        file identity, so caches can be aggressive)."""
        try:
            provided_mac = _b64url_decode(sig)
        except (ValueError, binascii.Error):
            return _http_error(401, "invalid signature")
        expected_mac = hmac.new(
            self._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        if not hmac.compare_digest(expected_mac, provided_mac):
            return _http_error(401, "invalid signature")
        try:
            rel_bytes = _b64url_decode(payload)
            rel_str = rel_bytes.decode("utf-8")
        except (ValueError, binascii.Error, UnicodeDecodeError):
            return _http_error(400, "invalid payload")
        # An attacker who somehow bypassed the HMAC check would still need
        # the resolved path to escape the media root; guard defensively.
        try:
            media_root = get_media_dir().resolve()
            candidate = (media_root / rel_str).resolve()
            candidate.relative_to(media_root)
        except (OSError, ValueError):
            return _http_error(404, "not found")
        if not candidate.is_file():
            return _http_error(404, "not found")
        try:
            body = candidate.read_bytes()
        except OSError:
            return _http_error(500, "read error")
        mime, _ = mimetypes.guess_type(candidate.name)
        if mime not in _MEDIA_ALLOWED_MIMES:
            mime = "application/octet-stream"
        return _http_response(
            body,
            content_type=mime,
            extra_headers=[
                ("Cache-Control", "private, max-age=31536000, immutable"),
                # Paired with the MIME whitelist above: prevents browsers from
                # MIME-sniffing an octet-stream fallback into executable HTML.
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    def _handle_session_delete(self, request: WsRequest, key: str) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        # Same boundary as ``_handle_session_messages``: the webui may only
        # mutate websocket sessions, and deletion really does unlink the local
        # JSONL, so keep the blast radius narrow and explicit.
        if not self._is_webui_session_key(decoded_key):
            return _http_error(404, "session not found")
        deleted = self._session_manager.delete_session(decoded_key)
        return _http_json_response({"deleted": bool(deleted)})

    def _handle_session_archive(self, request: WsRequest, key: str) -> Response:
        """Flip the ``archived`` flag on a websocket session.

        Spec: ``GET /api/sessions/{key}/archive?archived=0|1`` (GET-only due
        to the websockets HTTP parser; the PRD lists it as POST). Default is
        ``archived=1`` so the minimal call archives. Idempotent: re-archiving
        an already-archived session returns 200 with the same payload. 404 on
        missing sessions keeps parity with ``/messages`` and ``/delete``.
        """
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not self._is_webui_session_key(decoded_key):
            return _http_error(404, "session not found")

        query = _parse_query(request.path)
        raw = (_query_first(query, "archived") or "1").strip().lower()
        if raw in ("1", "true", "yes"):
            archived = True
        elif raw in ("0", "false", "no"):
            archived = False
        else:
            return _http_error(400, "archived must be 0 or 1")

        ok = self._session_manager.set_archived(decoded_key, archived)
        if not ok:
            return _http_error(404, "session not found")
        return _http_json_response({"key": decoded_key, "archived": archived})

    def _serve_static(self, request_path: str) -> Response | None:
        """Resolve *request_path* against the built SPA directory; SPA fallback to index.html."""
        assert self._static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        # Reject path-traversal attempts and absolute targets.
        if ".." in rel.split("/") or rel.startswith("/"):
            return _http_error(403, "Forbidden")
        candidate = (self._static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self._static_dist_path)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not candidate.is_file():
            # SPA history-mode fallback: unknown routes serve index.html so the
            # client-side router can render them.
            index = self._static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        try:
            body = candidate.read_bytes()
        except OSError as e:
            self.logger.warning("static: failed to read {}: {}", candidate, e)
            return _http_error(500, "Internal Server Error")
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        # Hash-named build assets are cache-friendly; index.html must stay fresh.
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return _http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache)],
        )

    def _authorize_websocket_handshake(self, connection: Any, query: dict[str, list[str]]) -> Any:
        supplied = _query_first(query, "token")
        static_token = self.config.token.strip()

        if static_token:
            if supplied and hmac.compare_digest(supplied, static_token):
                return None
            if supplied and self._take_issued_token_if_valid(supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if self.config.websocket_requires_token:
            if supplied and self._take_issued_token_if_valid(supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if supplied:
            self._take_issued_token_if_valid(supplied)
        return None

    async def start(self) -> None:
        self._running = True
        self._stop_event = asyncio.Event()

        ssl_context = self._build_ssl_context()
        scheme = "wss" if ssl_context else "ws"

        async def process_request(
            connection: ServerConnection,
            request: WsRequest,
        ) -> Any:
            return await self._dispatch_http(connection, request)

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

        self.logger.info(
            "WebSocket server listening on {}://{}:{}{}",
            scheme,
            self.config.host,
            self.config.port,
            self.config.path,
        )
        if self.config.token_issue_path:
            self.logger.info(
                "WebSocket token issue route: {}://{}:{}{}",
                scheme,
                self.config.host,
                self.config.port,
                _normalize_config_path(self.config.token_issue_path),
            )

        async def runner() -> None:
            async with serve(
                handler,
                self.config.host,
                self.config.port,
                process_request=process_request,
                max_size=self.config.max_message_bytes,
                ping_interval=self.config.ping_interval_s,
                ping_timeout=self.config.ping_timeout_s,
                ssl=ssl_context,
            ):
                assert self._stop_event is not None
                await self._stop_event.wait()

        self._server_task = asyncio.create_task(runner())
        await self._server_task

    async def _connection_loop(self, connection: Any) -> None:
        request = connection.request
        path_part = request.path if request else "/"
        _, query = _parse_request_path(path_part)
        client_id_raw = _query_first(query, "client_id")
        client_id = client_id_raw.strip() if client_id_raw else ""
        if not client_id:
            client_id = f"anon-{uuid.uuid4().hex[:12]}"
        elif len(client_id) > 128:
            self.logger.warning("client_id too long ({} chars), truncating", len(client_id))
            client_id = client_id[:128]

        default_chat_id = str(uuid.uuid4())

        try:
            await connection.send(
                json.dumps(
                    {
                        "event": "ready",
                        "chat_id": default_chat_id,
                        "client_id": client_id,
                    },
                    ensure_ascii=False,
                )
            )
            # Register only after ready is successfully sent to avoid out-of-order sends
            self._conn_default[connection] = default_chat_id
            self._attach(connection, default_chat_id)

            async for raw in connection:
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        self.logger.warning("ignoring non-utf8 binary frame")
                        continue

                envelope = _parse_envelope(raw)
                if envelope is not None:
                    await self._dispatch_envelope(connection, client_id, envelope)
                    continue

                content = _parse_inbound_payload(raw)
                if content is None:
                    continue
                await self._handle_message(
                    sender_id=client_id,
                    chat_id=default_chat_id,
                    content=content,
                    metadata={"remote": getattr(connection, "remote_address", None)},
                )
        except Exception as e:
            self.logger.debug("connection ended: {}", e)
        finally:
            self._cleanup_connection(connection)

    @staticmethod
    def _save_envelope_media(
        media: list[Any],
    ) -> tuple[list[str], str | None]:
        """Decode and persist ``media`` items from a ``message`` envelope.

        Returns ``(paths, None)`` on success or ``([], reason)`` on the first
        failure — the caller is expected to surface ``reason`` to the client
        and skip publishing so no half-formed message ever reaches the agent.
        On failure, any files already written to disk earlier in the same
        call are unlinked so partial ingress doesn't leak orphan files.
        ``reason`` is a short, stable token suitable for UI localization.

        Shape: ``list[{"data_url": str, "name"?: str | None}]``.
        """
        image_count = 0
        video_count = 0
        for item in media:
            mime = _extract_data_url_mime(item.get("data_url", "")) if isinstance(item, dict) else None
            if mime in _VIDEO_MIME_ALLOWED:
                video_count += 1
            elif mime in _IMAGE_MIME_ALLOWED:
                image_count += 1
        if image_count > _MAX_IMAGES_PER_MESSAGE:
            return [], "too_many_images"
        if video_count > _MAX_VIDEOS_PER_MESSAGE:
            return [], "too_many_videos"

        media_dir = get_media_dir("websocket")
        paths: list[str] = []

        def _abort(reason: str) -> tuple[list[str], str]:
            for p in paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError as exc:
                    self.logger.warning(
                        "failed to unlink partial media {}: {}", p, exc
                    )
            return [], reason

        for item in media:
            if not isinstance(item, dict):
                return _abort("malformed")
            data_url = item.get("data_url")
            if not isinstance(data_url, str) or not data_url:
                return _abort("malformed")
            mime = _extract_data_url_mime(data_url)
            if mime is None:
                return _abort("decode")
            if mime not in _UPLOAD_MIME_ALLOWED:
                return _abort("mime")
            is_video = mime in _VIDEO_MIME_ALLOWED
            max_bytes = _MAX_VIDEO_BYTES if is_video else _MAX_IMAGE_BYTES
            try:
                saved = save_base64_data_url(
                    data_url, media_dir, max_bytes=max_bytes,
                )
            except FileSizeExceeded:
                return _abort("size")
            except Exception as exc:
                self.logger.warning("media decode failed: {}", exc)
                return _abort("decode")
            if saved is None:
                return _abort("decode")
            paths.append(saved)
        return paths, None

    async def _dispatch_envelope(
        self,
        connection: Any,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        """Route one typed inbound envelope (``new_chat`` / ``attach`` / ``message``)."""
        t = envelope.get("type")
        if t == "new_chat":
            new_id = str(uuid.uuid4())
            self._attach(connection, new_id)
            await self._send_event(connection, "attached", chat_id=new_id)
            return
        if t == "attach":
            cid = envelope.get("chat_id")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            self._attach(connection, cid)
            # ``active_turn`` lets the webui seed its streaming flag from the
            # authoritative backend state: after a browser refresh or a chat
            # switch, the Stop button must appear iff the server is still
            # processing a turn for this chat. Stale persisted tool_calls no
            # longer influence the UI.
            await self._send_event(
                connection,
                "attached",
                chat_id=cid,
                active_turn=cid in self._active_turns,
            )
            return
        if t == "stop":
            # Silent cancel request from the WebUI composer — route it as an
            # internal /stop inbound so the existing cancellation path runs,
            # but keep ``silent`` set so no "Stopped N task(s)." reply is
            # echoed back to the chat history.
            cid = envelope.get("chat_id")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            self._attach(connection, cid)
            metadata: dict[str, Any] = {
                "remote": getattr(connection, "remote_address", None),
                "webui": True,
                "silent": True,
            }
            await self._handle_message(
                sender_id=client_id,
                chat_id=cid,
                content="/stop",
                metadata=metadata,
            )
            return
        if t == "message":
            cid = envelope.get("chat_id")
            content = envelope.get("content")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            if not isinstance(content, str):
                await self._send_event(connection, "error", detail="missing content")
                return

            raw_media = envelope.get("media")
            media_paths: list[str] = []
            if raw_media is not None:
                if not isinstance(raw_media, list):
                    await self._send_event(
                        connection, "error",
                        detail="image_rejected", reason="malformed",
                    )
                    return
                media_paths, reason = self._save_envelope_media(raw_media)
                if reason is not None:
                    await self._send_event(
                        connection, "error",
                        detail="image_rejected", reason=reason,
                    )
                    return

            # Allow image-only turns (content may be empty when media is attached).
            if not content.strip() and not media_paths:
                await self._send_event(connection, "error", detail="missing content")
                return

            # Auto-attach on first use so clients can one-shot without a separate attach.
            self._attach(connection, cid)
            metadata: dict[str, Any] = {"remote": getattr(connection, "remote_address", None)}
            if envelope.get("webui") is True:
                metadata["webui"] = True
            # Mark this chat as having an in-flight turn only after all
            # envelope validation has passed. A forthcoming ``turn_end`` is
            # the authoritative cue to clear it again (whether the turn
            # completes naturally or is aborted by ``/stop``). Concurrent
            # ``attach`` probes (e.g. a second browser tab) can therefore
            # read this set to decide whether to show the Stop button even
            # before the first outbound frame arrives.
            self._active_turns.add(cid)
            await self._handle_message(
                sender_id=client_id,
                chat_id=cid,
                content=content,
                media=media_paths or None,
                metadata=metadata,
            )
            return
        await self._send_event(connection, "error", detail=f"unknown type: {t!r}")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except Exception as e:
                self.logger.warning("server task error during shutdown: {}", e)
            self._server_task = None
        self._subs.clear()
        self._conn_chats.clear()
        self._conn_default.clear()
        self._issued_tokens.clear()
        self._api_tokens.clear()

    async def _safe_send_to(self, connection: Any, raw: str, *, label: str = "") -> None:
        """Send a raw frame to one connection, cleaning up on ConnectionClosed."""
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._cleanup_connection(connection)
            self.logger.warning("connection gone{}", label)
        except Exception:
            self.logger.exception("send failed{}", label)
            raise

    async def send(self, msg: OutboundMessage) -> None:
        # Snapshot the subscriber set so ConnectionClosed cleanups mid-iteration are safe.
        conns = list(self._subs.get(msg.chat_id, ()))
        if not conns:
            self.logger.warning("no active subscribers for chat_id={}", msg.chat_id)
            return
        # Signal that the agent has fully finished processing the current turn.
        if msg.metadata.get("_turn_end"):
            await self.send_turn_end(msg.chat_id)
            return
        if msg.metadata.get("_session_updated"):
            await self.send_session_updated(msg.chat_id)
            return
        text = msg.content
        if msg.buttons:
            text = _append_buttons_as_text(text, msg.buttons)
        payload: dict[str, Any] = {
            "event": "message",
            "chat_id": msg.chat_id,
            "text": text,
        }
        if msg.buttons:
            payload["buttons"] = msg.buttons
            payload["button_prompt"] = msg.content
        if msg.media:
            payload["media"] = msg.media
            urls: list[dict[str, str]] = []
            for entry in msg.media:
                signed = self._sign_or_stage_media_path(Path(entry))
                if signed is not None:
                    urls.append(signed)
            if urls:
                payload["media_urls"] = urls
        if msg.reply_to:
            payload["reply_to"] = msg.reply_to
        # Mark intermediate agent breadcrumbs (tool-call hints, generic
        # progress strings) so WS clients can render them as subordinate
        # trace rows rather than conversational replies.
        if msg.metadata.get("_tool_hint"):
            payload["kind"] = "tool_hint"
        elif msg.metadata.get("_progress"):
            payload["kind"] = "progress"
        raw = json.dumps(payload, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" ")

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        meta = metadata or {}
        if meta.get("_stream_end"):
            body: dict[str, Any] = {"event": "stream_end", "chat_id": chat_id}
        else:
            body = {
                "event": "delta",
                "chat_id": chat_id,
                "text": delta,
            }
        if meta.get("_stream_id") is not None:
            body["stream_id"] = meta["_stream_id"]
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" stream ")

    async def send_turn_end(self, chat_id: str) -> None:
        """Signal that the agent has fully finished processing the current turn."""
        # Clear the active-turn marker regardless of whether there are still
        # subscribers attached: the turn really did end on the backend, and a
        # client that reconnects later must not resurrect the Stop button.
        self._active_turns.discard(chat_id)
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {"event": "turn_end", "chat_id": chat_id}
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_end ")

    async def send_session_updated(self, chat_id: str) -> None:
        """Notify clients that session metadata changed outside the main turn."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {"event": "session_updated", "chat_id": chat_id}
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" session_updated ")
