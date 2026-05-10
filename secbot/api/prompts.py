"""Quick-command prompts loader served by ``GET /api/prompts``.

Spec: ``.trellis/spec/backend/prompts-config.md``.

Design notes
------------

- **Source resolution** (first hit wins): ``$SECBOT_PROMPTS_FILE`` →
  ``~/.secbot/prompts.yaml`` → bundled ``secbot/config/prompts.yaml``. If
  none exist the handler serves ``{"prompts": []}`` and logs once.

- **Hot reload**: a single ``stat()`` per request is cheap; when ``mtime``
  changes, the YAML is re-parsed and the in-memory cache is replaced
  atomically.  Parse failures keep the previous known-good value so a
  half-saved edit can never clear the list in front of the user.

- **Dedupe**: duplicate ``key`` → first occurrence wins + warning logged.
  Unknown icons are passed through untouched — the frontend has a
  fallback map.

- **Process-local singleton**: ``get_loader()`` returns a shared instance
  so all handlers observe the same cache / log-once state; tests can
  ``reset_loader()`` to restart from a clean slate.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger

_BUNDLED_PATH = Path(__file__).resolve().parent.parent / "config" / "prompts.yaml"
_USER_OVERRIDE_PATH = Path.home() / ".secbot" / "prompts.yaml"

_ALLOWED_FIELDS = ("key", "title", "subtitle", "prefill", "icon")


def _resolve_source() -> Optional[Path]:
    """Return the highest-priority existing prompts YAML, or None."""
    env = os.environ.get("SECBOT_PROMPTS_FILE")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    if _USER_OVERRIDE_PATH.is_file():
        return _USER_OVERRIDE_PATH
    if _BUNDLED_PATH.is_file():
        return _BUNDLED_PATH
    return None


def _coerce_prompt(raw: Any) -> Optional[dict[str, str]]:
    """Coerce one YAML list entry to the canonical dict shape.

    Returns ``None`` when *raw* is not a dict or is missing any required
    field. Non-string field values are stringified so operator typos
    (``icon: 1`` → ``"1"``) do not crash the endpoint.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for field in _ALLOWED_FIELDS:
        value = raw.get(field)
        if value is None:
            return None
        out[field] = str(value)
    if not out["key"].strip():
        return None
    return out


class PromptsLoader:
    """mtime-cached YAML loader for the quick-commands list.

    Thread-safe: ``load()`` guards the cache swap with a lock so a burst of
    concurrent HTTP handlers all see a consistent snapshot.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached: list[dict[str, str]] = []
        self._cached_source: Optional[Path] = None
        self._cached_mtime: Optional[float] = None
        self._logged_missing: bool = False

    def load(self) -> list[dict[str, str]]:
        """Return the current prompts list, reloading if the source changed.

        On parse error the previously cached value is returned (never an
        empty list) so a transient syntax mistake does not blank the UI.
        """
        source = _resolve_source()
        if source is None:
            with self._lock:
                if not self._logged_missing:
                    logger.warning(
                        "prompts.yaml missing from all 3 locations; serving []"
                    )
                    self._logged_missing = True
                # Reset cache — otherwise a later recreated file keeps the
                # stale snapshot until the process restarts.
                self._cached = []
                self._cached_source = None
                self._cached_mtime = None
                return []

        try:
            mtime = source.stat().st_mtime
        except OSError as exc:
            logger.warning("prompts.reload_failed error={} source={}", exc, source)
            return list(self._cached)

        with self._lock:
            if (
                self._cached_source == source
                and self._cached_mtime is not None
                and mtime == self._cached_mtime
            ):
                return list(self._cached)

        # Re-parse outside the lock — the YAML is tiny but we still keep the
        # critical section minimal.
        try:
            with open(source, encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("prompts.reload_failed error={} source={}", exc, source)
            return list(self._cached)

        raw_list: list[Any]
        if isinstance(doc, dict) and isinstance(doc.get("prompts"), list):
            raw_list = doc["prompts"]
        elif isinstance(doc, list):
            # Tolerate YAML that is just a bare list at the top level —
            # less syntax for hand-authored overrides.
            raw_list = doc
        else:
            logger.warning(
                "prompts.reload_failed error=top-level `prompts` key missing source={}",
                source,
            )
            return list(self._cached)

        parsed: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in raw_list:
            prompt = _coerce_prompt(entry)
            if prompt is None:
                continue
            if prompt["key"] in seen:
                logger.warning(
                    "prompts.duplicate_key key={} source={}", prompt["key"], source
                )
                continue
            seen.add(prompt["key"])
            parsed.append(prompt)

        with self._lock:
            self._cached = parsed
            self._cached_source = source
            self._cached_mtime = mtime
            self._logged_missing = False
        logger.info("prompts.loaded count={} source={}", len(parsed), source)
        return list(parsed)


_loader: Optional[PromptsLoader] = None
_loader_lock = threading.Lock()


def get_loader() -> PromptsLoader:
    """Return the process-local singleton PromptsLoader."""
    global _loader
    if _loader is None:
        with _loader_lock:
            if _loader is None:
                _loader = PromptsLoader()
    return _loader


def reset_loader() -> None:
    """Drop the singleton; intended for tests only."""
    global _loader
    with _loader_lock:
        _loader = None


def load_prompts() -> list[dict[str, str]]:
    """Convenience wrapper used by the HTTP handler."""
    return get_loader().load()


__all__ = ["PromptsLoader", "get_loader", "load_prompts", "reset_loader"]
