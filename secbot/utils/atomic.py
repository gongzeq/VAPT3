"""Atomic file writes with fsync durability.

Extracted from ``secbot.cron.service.CronService._atomic_write`` so other
persistence layers (cron, workflow, future session-like JSON stores) can
reuse the same temp-file + ``os.replace`` + ``fsync`` pattern.

Why this matters: without the pattern, a crash or SIGKILL mid-write can
leave the destination file truncated, and on next start the loader will
happily re-create an empty store — wiping every persisted entry.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically with fsync.

    Uses a temp-file + ``os.replace`` + ``fsync`` pattern so a crash or
    SIGKILL mid-write cannot leave the destination truncated or invalid.

    The parent directory is created if it does not exist. On Windows the
    directory-level ``fsync`` is skipped (NTFS journals metadata
    synchronously, so it would be a no-op).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        with suppress(PermissionError):
            fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def append_jsonl(path: Path, line: str) -> None:
    """Append a single JSON line to ``path`` with ``fsync`` after write.

    Not truly atomic (append can be partial on crash), but the JSONL
    consumer is expected to tolerate a trailing malformed row by skipping
    it. Parent directory is created on demand.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        if not line.endswith("\n"):
            line = line + "\n"
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
