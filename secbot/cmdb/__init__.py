"""Local CMDB (asset / service / vulnerability / scan inventory).

Authoritative contract: `.trellis/spec/backend/cmdb-schema.md`.

The only legal entry points are:

- :func:`secbot.cmdb.db.get_session` — async session context manager
- :mod:`secbot.cmdb.repo` — high-level repository helpers (`upsert_*`, `list_*`)

Direct use of `sqlite3` / raw SQL outside this package is forbidden.
"""

from secbot.cmdb.db import get_engine, get_session, init_engine
from secbot.cmdb.models import Asset, Base, Scan, Service, Vulnerability

__all__ = [
    "Asset",
    "Base",
    "Scan",
    "Service",
    "Vulnerability",
    "get_engine",
    "get_session",
    "init_engine",
]
