"""Threat Intel module — independent threat intelligence database.

The only legal entry points are:

- :func:`secbot.threat_intel.db.get_session` — async session context manager
- :mod:`secbot.threat_intel.repo` — high-level repository helpers (``upsert_*``, ``list_*``)
- :mod:`secbot.threat_intel.models` — ORM models

Direct use of ``sqlite3`` / raw SQL outside this package is forbidden.

This module is independent of :mod:`secbot.cmdb` — separate database file,
separate engine, separate migrations.  Threat Intel data MUST NOT be written
to the CMDB.
"""

from secbot.threat_intel.db import dispose_engine, get_engine, get_session, init_engine
from secbot.threat_intel.models import (
    DEFAULT_ACTOR,
    AptAlias,
    Base,
    FeedPullRun,
    IndustryCPE,
    MaritimeEvent,
    ThreatGroup,
    ThreatGroupVulnAssoc,
    ThreatInfraIP,
    ThreatMalwareFamily,
    ThreatVuln,
)

__all__ = [
    "DEFAULT_ACTOR",
    "AptAlias",
    "Base",
    "FeedPullRun",
    "IndustryCPE",
    "MaritimeEvent",
    "ThreatGroup",
    "ThreatGroupVulnAssoc",
    "ThreatInfraIP",
    "ThreatMalwareFamily",
    "ThreatVuln",
    "dispose_engine",
    "get_engine",
    "get_session",
    "init_engine",
]
