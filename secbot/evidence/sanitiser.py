"""Redaction helpers for evidence raw bytes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

AUTO_HEADER_KEYS = frozenset({"authorization", "cookie", "set-cookie"})


def _redaction(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"***REDACTED:{len(text)}c***"


def _normalise_keys(keys: Iterable[str]) -> set[str]:
    return {str(key).lower() for key in keys if str(key)}


def _redact_json(value: Any, keys: set[str]) -> tuple[Any, bool]:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        changed = False
        for key, child in value.items():
            if str(key).lower() in keys:
                redacted[str(key)] = _redaction(child)
                changed = True
            else:
                redacted_child, child_changed = _redact_json(child, keys)
                redacted[str(key)] = redacted_child
                changed = changed or child_changed
        return redacted, changed
    if isinstance(value, list):
        redacted_items = []
        changed = False
        for item in value:
            redacted_item, item_changed = _redact_json(item, keys)
            redacted_items.append(redacted_item)
            changed = changed or item_changed
        return redacted_items, changed
    return value, False


def _redact_query_in_text(text: str, keys: set[str]) -> tuple[str, bool]:
    url_re = re.compile(r"https?://[^\s\"'<>]+")
    any_changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal any_changed
        url = match.group(0)
        parts = urlsplit(url)
        if not parts.query:
            return url
        query = []
        changed = False
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in keys:
                query.append((key, _redaction(value)))
                changed = True
            else:
                query.append((key, value))
        if not changed:
            return url
        any_changed = True
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    return url_re.sub(repl, text), any_changed


def _redact_headers(text: str) -> tuple[str, bool]:
    header_re = re.compile(
        r"(?im)^([ \t]*(?:Authorization|Cookie|Set-Cookie)[ \t]*:[ \t]*)(.*)$"
    )
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f"{match.group(1)}{_redaction(match.group(2).strip())}"

    return header_re.sub(repl, text), changed


def sanitise(content: bytes, keys: Iterable[str] = ()) -> bytes:
    """Return ``content`` with sensitive JSON fields, headers, and URL params redacted."""
    redacted, _ = sanitise_with_status(content, keys)
    return redacted


def sanitise_with_status(content: bytes, keys: Iterable[str] = ()) -> tuple[bytes, bool]:
    """Return redacted bytes and whether a redaction changed the content."""
    key_set = _normalise_keys(keys) | AUTO_HEADER_KEYS
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        decoded = content.decode("utf-8", errors="replace")

    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError:
        text, header_changed = _redact_headers(decoded)
        text, query_changed = _redact_query_in_text(text, key_set)
        changed = header_changed or query_changed
        return (text.encode("utf-8"), True) if changed else (content, False)

    redacted, changed = _redact_json(parsed, key_set)
    if not changed:
        return content, False
    return json.dumps(redacted, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), True
