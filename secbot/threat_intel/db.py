"""Async SQLAlchemy engine + session factory for the Threat Intel database.

Default database path: ``~/.secbot/threat_intel.sqlite3`` (override with
``SECBOT_THREAT_INTEL_URL`` or by passing an explicit URL to :func:`init_engine`).

WAL mode is enabled on every new connection to support single-writer +
many-reader concurrency without "database is locked" errors on short writes.

This module is intentionally independent of :mod:`secbot.cmdb.db` so that
Threat Intel schema migrations do not affect VAPT scan data.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _default_db_path() -> Path:
    """Resolve the default SQLite file path for threat intel data."""

    base = os.environ.get("SECBOT_HOME")
    if base:
        return Path(base).expanduser() / "threat_intel.sqlite3"
    home = Path.home()
    secbot_home = home / ".secbot"
    if secbot_home.exists():
        return secbot_home / "threat_intel.sqlite3"
    return home / ".secbot" / "threat_intel.sqlite3"


def _default_url() -> str:
    env = os.environ.get("SECBOT_THREAT_INTEL_URL")
    if env:
        return env
    path = _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path}"


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Apply WAL + sane durability pragmas on every new connection.

    Matches the CMDB PRAGMA set: WAL, synchronous=NORMAL, foreign_keys=ON,
    busy_timeout=5000.
    """

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def init_engine(url: Optional[str] = None, *, echo: bool = False) -> AsyncEngine:
    """Initialise (or replace) the process-wide async engine.

    Safe to call multiple times: disposing the previous engine first.
    """

    global _engine, _sessionmaker

    if _engine is not None:
        _engine = None
        _sessionmaker = None

    resolved = url or _default_url()
    engine = create_async_engine(
        resolved,
        echo=echo,
        future=True,
        pool_pre_ping=True,
    )
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)

    _engine = engine
    _sessionmaker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    return engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async session context manager with commit-on-exit / rollback-on-error.

    This is the **only** legal way to read or write the Threat Intel DB.
    """

    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None

    session = _sessionmaker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Dispose the engine — primarily for tests and graceful shutdown."""

    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
