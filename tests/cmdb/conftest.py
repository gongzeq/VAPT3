"""CMDB test fixtures.

Spec hard rule (cmdb-schema.md §5): every CMDB-touching test MUST use
``tmp_cmdb`` to get an isolated SQLite with the full schema applied.

We use a per-test file (``tmp_path``) rather than ``:memory:`` so multiple
connections share state — aiosqlite spawns a new connection per session and
``:memory:`` would hand each connection a fresh, empty DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb import db as cmdb_db
from secbot.cmdb.models import Base


@pytest_asyncio.fixture
async def tmp_cmdb(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    await cmdb_db.dispose_engine()

    db_file = tmp_path / "cmdb.sqlite3"
    engine = cmdb_db.init_engine(f"sqlite+aiosqlite:///{db_file}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with cmdb_db.get_session() as session:
        yield session

    await cmdb_db.dispose_engine()
