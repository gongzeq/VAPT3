"""Alembic environment for the local CMDB.

Run with::

    alembic -c secbot/cmdb/alembic.ini upgrade head

The DB URL falls back through, in order:

1. ``-x url=...`` argument
2. ``SECBOT_CMDB_URL`` / ``SECBOT_CMDB_URL`` env var
3. ``sqlite:///~/.secbot/cmdb.sqlite3`` (sync driver for offline migrations)
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from secbot.cmdb.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if "url" in x_args:
        return x_args["url"]
    env_url = os.environ.get("SECBOT_CMDB_URL") or os.environ.get("SECBOT_CMDB_URL")
    if env_url:
        # Strip async driver for sync alembic execution.
        return env_url.replace("+aiosqlite", "")
    home = Path.home()
    base = home / ".secbot" if (home / ".secbot").exists() else home / ".secbot"
    base.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{base / 'cmdb.sqlite3'}"


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
