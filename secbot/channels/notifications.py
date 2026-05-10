"""In-memory notification queue for the Navbar bell dropdown.

Spec: ``.trellis/tasks/05-10-p2-notification-activity/prd.md``.

Design notes
------------
* The queue is a bounded :class:`collections.deque` with ``maxlen`` sourced
  from (1) the ``SECBOT_NOTIFICATION_BUFFER_SIZE`` env var, (2) the
  constructor parameter, (3) the module default of ``500``. Overflow drops
  the oldest item, matching the PRD's "ring buffer, newest-wins" semantic.
* Thread-safe: every mutating operation and snapshot is guarded by a
  :class:`threading.Lock`. The critical section is tiny (deque ops only)
  so contention stays negligible even under WS burst.
* Persistence is intentionally out of scope (see PRD §"Out of Scope") —
  a process restart clears the queue.
* Singleton accessor :func:`get_notification_queue` mirrors the range-and
  reset style established by :mod:`secbot.api.prompts` so tests can
  substitute a clean queue via :func:`reset_queue`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Iterable, Optional

from secbot.cmdb.repo import new_ulid

logger = logging.getLogger(__name__)

DEFAULT_BUFFER_SIZE = 500
_ENV_BUFFER_SIZE = "SECBOT_NOTIFICATION_BUFFER_SIZE"
_ENV_EVENTS_BUFFER_SIZE = "SECBOT_EVENTS_BUFFER_SIZE"
_ENV_EVENTS_WINDOW_SECONDS = "SECBOT_EVENTS_WINDOW_SECONDS"
DEFAULT_EVENTS_WINDOW_SECONDS = 300  # last 5 minutes, per PRD §Contracts §4

# Allowed notification types — kept as a tuple (not an Enum) so callers
# stay lightweight and the wire format remains plain strings. Extending
# this list is a protocol change: update the PRD + websocket spec.
ALLOWED_TYPES: tuple[str, ...] = (
    "critical_vuln",
    "scan_failed",
    "scan_completed",
    "high_risk_confirm",
)

# Activity event vocabulary — sourced from the PRD §Contracts §4 example.
# Same forward-compat contract as ``ALLOWED_TYPES``: unknown values are
# logged but not rejected.
ALLOWED_EVENT_LEVELS: tuple[str, ...] = ("critical", "warning", "info", "ok")
ALLOWED_EVENT_SOURCES: tuple[str, ...] = (
    "weak_password",
    "port_scan",
    "asset_discovery",
    "report",
    "orchestrator",
)


def _resolve_maxlen(
    param: Optional[int],
    *,
    env: str = _ENV_BUFFER_SIZE,
    default: int = DEFAULT_BUFFER_SIZE,
) -> int:
    """Pick the effective ring-buffer capacity.

    Priority: env var > constructor param > module default. Invalid env
    values (non-integer, <=0) fall through with a warning; they never
    raise — we'd rather run with the default than refuse to start.
    """
    raw = os.environ.get(env)
    if raw is not None:
        try:
            value = int(raw)
            if value > 0:
                return value
            logger.warning(
                "notifications.invalid_buffer_env env=%s value=%s falling back",
                env,
                raw,
            )
        except ValueError:
            logger.warning(
                "notifications.invalid_buffer_env env=%s value=%s not an int",
                env,
                raw,
            )
    if param is not None and param > 0:
        return param
    return default


def _resolve_window_seconds(param: Optional[int]) -> int:
    """Same resolution model as :func:`_resolve_maxlen` but for the
    events default window. Invalid env/param fall back to 300 s."""
    raw = os.environ.get(_ENV_EVENTS_WINDOW_SECONDS)
    if raw is not None:
        try:
            value = int(raw)
            if value > 0:
                return value
            logger.warning(
                "notifications.invalid_window_env env=%s value=%s falling back",
                _ENV_EVENTS_WINDOW_SECONDS,
                raw,
            )
        except ValueError:
            logger.warning(
                "notifications.invalid_window_env env=%s value=%s not an int",
                _ENV_EVENTS_WINDOW_SECONDS,
                raw,
            )
    if param is not None and param > 0:
        return param
    return DEFAULT_EVENTS_WINDOW_SECONDS


def _utcnow_iso() -> str:
    """ISO-8601 timestamp with explicit UTC offset (``+00:00``)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotificationQueue:
    """Bounded in-memory FIFO with random-access by id for read flags.

    Storage order: ``appendleft`` places the newest entry at index 0.
    When ``maxlen`` is reached, the deque drops from the right, so the
    oldest item is evicted — matching the PRD's "drop oldest" wording.
    """

    def __init__(self, maxlen: Optional[int] = None) -> None:
        self._maxlen = _resolve_maxlen(maxlen)
        self._items: Deque[dict[str, Any]] = deque(maxlen=self._maxlen)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------
    def publish(
        self,
        *,
        type: str,
        title: str,
        body: str = "",
        link: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append a new notification and return the stored row.

        ``type`` must be one of :data:`ALLOWED_TYPES` — unknown types are
        still accepted (for forward-compat) but logged once per call so
        integration mistakes surface in the journal.
        """
        if type not in ALLOWED_TYPES:
            logger.warning("notifications.unknown_type type=%s", type)
        item: dict[str, Any] = {
            "id": f"n-{new_ulid()}",
            "type": type,
            "title": title,
            "body": body or "",
            "read": False,
            "created_at": _utcnow_iso(),
            "link": link,
        }
        with self._lock:
            self._items.appendleft(item)
        return dict(item)

    def mark_read(self, notification_id: str) -> Optional[dict[str, Any]]:
        """Flip ``read=True`` on a single entry. Returns the stored row,
        or ``None`` when the id is unknown (evicted or never existed)."""
        with self._lock:
            for entry in self._items:
                if entry["id"] == notification_id:
                    entry["read"] = True
                    return dict(entry)
        return None

    def mark_all_read(self) -> int:
        """Flip every unread entry. Returns the number of rows changed."""
        updated = 0
        with self._lock:
            for entry in self._items:
                if not entry["read"]:
                    entry["read"] = True
                    updated += 1
        return updated

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        """Return a shallow copy of every stored item, newest-first."""
        with self._lock:
            return [dict(entry) for entry in self._items]

    def unread_count(self) -> int:
        with self._lock:
            return sum(1 for entry in self._items if not entry["read"])

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def __len__(self) -> int:  # pragma: no cover - trivial
        with self._lock:
            return len(self._items)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------
    def extend_raw(self, entries: Iterable[dict[str, Any]]) -> None:
        """Bulk-insert pre-formed entries (tests only).

        The deque still respects ``maxlen``; the entries are inserted in
        the given order so that iteration order stays newest-first when
        the caller orders the input newest-first.
        """
        with self._lock:
            for entry in entries:
                self._items.appendleft(dict(entry))


# ---------------------------------------------------------------------------
# Singleton accessors — mirror secbot.api.prompts style.
# ---------------------------------------------------------------------------
_queue: Optional[NotificationQueue] = None
_queue_lock = threading.Lock()


def get_notification_queue() -> NotificationQueue:
    """Return the process-local singleton NotificationQueue.

    Uses double-checked locking so the first access from a burst of WS
    handlers still constructs at most one queue.
    """
    global _queue
    if _queue is None:
        with _queue_lock:
            if _queue is None:
                _queue = NotificationQueue()
    return _queue


def reset_queue() -> None:
    """Drop the singleton; intended for tests only."""
    global _queue
    with _queue_lock:
        _queue = None


# ---------------------------------------------------------------------------
# Activity event stream (P2/R2)
# ---------------------------------------------------------------------------
class EventBuffer:
    """Bounded in-memory ring buffer for activity events.

    Stores ``(timestamp_dt, payload)`` tuples so ``since`` filtering is a
    single datetime compare per entry — no per-request string parsing.
    The public :meth:`snapshot` and :meth:`filter` methods return plain
    dicts; the parsed timestamp is an implementation detail.
    """

    def __init__(
        self,
        maxlen: Optional[int] = None,
        default_window_seconds: Optional[int] = None,
    ) -> None:
        self._maxlen = _resolve_maxlen(
            maxlen, env=_ENV_EVENTS_BUFFER_SIZE, default=DEFAULT_BUFFER_SIZE
        )
        self._default_window_seconds = _resolve_window_seconds(default_window_seconds)
        self._items: Deque[tuple[datetime, dict[str, Any]]] = deque(maxlen=self._maxlen)
        self._lock = threading.Lock()

    # -- write path ----------------------------------------------------
    def publish(
        self,
        *,
        level: str,
        source: str,
        message: str,
        task_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Append a new event row. Timestamp defaults to ``now(UTC)``.

        Unknown ``level`` / ``source`` values are logged once per call
        but still accepted (forward-compat with agent-specific tags).
        """
        if level not in ALLOWED_EVENT_LEVELS:
            logger.warning("events.unknown_level level=%s", level)
        if source not in ALLOWED_EVENT_SOURCES:
            logger.warning("events.unknown_source source=%s", source)
        ts_dt = timestamp or datetime.now(timezone.utc)
        if ts_dt.tzinfo is None:
            # Normalise naive datetimes to UTC so filter() compares apples
            # to apples. Callers that want local time should pass a tz-aware
            # datetime explicitly.
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        entry: dict[str, Any] = {
            "id": f"evt-{new_ulid()}",
            "timestamp": ts_dt.isoformat(timespec="seconds"),
            "level": level,
            "source": source,
            "task_id": task_id,
            "message": message,
        }
        with self._lock:
            self._items.appendleft((ts_dt, entry))
        return dict(entry)

    # -- read path -----------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        """Newest-first list of every buffered event (copies)."""
        with self._lock:
            return [dict(entry) for _, entry in self._items]

    def filter(
        self, *, since: Optional[datetime] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return events whose timestamp is ``>= since``, newest-first.

        When ``since`` is ``None``, the default 5-minute window is applied
        (configurable via :data:`DEFAULT_EVENTS_WINDOW_SECONDS` or the env
        override). ``limit`` clamps the response size — values <=0 return
        an empty list.
        """
        if limit <= 0:
            return []
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(
                seconds=self._default_window_seconds
            )
        elif since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        with self._lock:
            picks: list[dict[str, Any]] = []
            # Iterate newest-first; break early once we drop below ``since``
            # because insertion order = descending timestamp.
            for ts_dt, entry in self._items:
                if ts_dt < since:
                    break
                picks.append(dict(entry))
                if len(picks) >= limit:
                    break
        return picks

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def default_window_seconds(self) -> int:
        return self._default_window_seconds

    def __len__(self) -> int:  # pragma: no cover - trivial
        with self._lock:
            return len(self._items)


_event_buffer: Optional[EventBuffer] = None
_event_buffer_lock = threading.Lock()


def get_event_buffer() -> EventBuffer:
    """Return the process-local singleton EventBuffer."""
    global _event_buffer
    if _event_buffer is None:
        with _event_buffer_lock:
            if _event_buffer is None:
                _event_buffer = EventBuffer()
    return _event_buffer


def reset_event_buffer() -> None:
    """Drop the singleton; intended for tests only."""
    global _event_buffer
    with _event_buffer_lock:
        _event_buffer = None
