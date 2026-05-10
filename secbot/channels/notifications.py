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
from datetime import datetime, timezone
from typing import Any, Deque, Iterable, Optional

from secbot.cmdb.repo import new_ulid

logger = logging.getLogger(__name__)

DEFAULT_BUFFER_SIZE = 500
_ENV_BUFFER_SIZE = "SECBOT_NOTIFICATION_BUFFER_SIZE"

# Allowed notification types — kept as a tuple (not an Enum) so callers
# stay lightweight and the wire format remains plain strings. Extending
# this list is a protocol change: update the PRD + websocket spec.
ALLOWED_TYPES: tuple[str, ...] = (
    "critical_vuln",
    "scan_failed",
    "scan_completed",
    "high_risk_confirm",
)


def _resolve_maxlen(param: Optional[int]) -> int:
    """Pick the effective ring-buffer capacity.

    Priority: env var > constructor param > module default. Invalid env
    values (non-integer, <=0) fall through with a warning; they never
    raise — we'd rather run with the default than refuse to start.
    """
    raw = os.environ.get(_ENV_BUFFER_SIZE)
    if raw is not None:
        try:
            value = int(raw)
            if value > 0:
                return value
            logger.warning(
                "notifications.invalid_buffer_env env=%s value=%s falling back",
                _ENV_BUFFER_SIZE,
                raw,
            )
        except ValueError:
            logger.warning(
                "notifications.invalid_buffer_env env=%s value=%s not an int",
                _ENV_BUFFER_SIZE,
                raw,
            )
    if param is not None and param > 0:
        return param
    return DEFAULT_BUFFER_SIZE


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
