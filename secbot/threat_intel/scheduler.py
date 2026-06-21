"""Threat Intel cron job scheduler.

Registers daily cron jobs for CISA KEV and ThreatFox feed pulls.
Jobs use the ``__threat_intel__:`` message prefix to distinguish them
from workflow dispatch messages (``__workflow__:``).

Called during application startup to register system jobs idempotently.
"""

from __future__ import annotations

import logging
from typing import Any

from secbot.cron.types import CronJob, CronPayload, CronSchedule

_logger = logging.getLogger(__name__)

THREAT_INTEL_MSG_PREFIX = "__threat_intel__:"

# Daily schedule: 08:00 UTC (16:00 Beijing time)
_DAILY_CRON = "0 8 * * *"
_TZ = "UTC"


def _build_cron_job(
    job_id: str,
    name: str,
    source: str,
    cron_expr: str = _DAILY_CRON,
) -> CronJob:
    """Build a CronJob for a threat intel feed pull."""
    return CronJob(
        id=job_id,
        name=name,
        enabled=True,
        schedule=CronSchedule(kind="cron", expr=cron_expr, tz=_TZ),
        payload=CronPayload(
            kind="system_event",
            message=f"{THREAT_INTEL_MSG_PREFIX}{source}",
        ),
    )


def register_threat_intel_cron_jobs(cron_service: Any) -> None:
    """Register daily threat intel feed pull jobs (idempotent).

    Jobs:
    - ``threat-intel-cisa-kev`` — daily CISA KEV pull
    - ``threat-intel-threatfox`` — daily ThreatFox pull

    Safe to call multiple times — ``register_system_job`` replaces
    any existing job with the same ID.
    """
    jobs = [
        _build_cron_job(
            job_id="threat-intel-cisa-kev",
            name="Daily CISA KEV Pull",
            source="cisa_kev",
        ),
        _build_cron_job(
            job_id="threat-intel-threatfox",
            name="Daily ThreatFox Pull",
            source="threatfox",
        ),
    ]

    for job in jobs:
        cron_service.register_system_job(job)
        _logger.info("Registered threat intel cron job: %s (%s)", job.name, job.id)


def is_threat_intel_cron_message(message: str) -> bool:
    """Check if a cron message is a threat intel dispatch."""
    return isinstance(message, str) and message.startswith(THREAT_INTEL_MSG_PREFIX)


def decode_threat_intel_source(message: str) -> str:
    """Extract the feed source from a threat intel cron message."""
    if not message.startswith(THREAT_INTEL_MSG_PREFIX):
        raise ValueError(f"Not a threat intel message: {message[:50]}")
    return message[len(THREAT_INTEL_MSG_PREFIX):]


async def handle_cron_threat_intel(source: str) -> dict[str, Any]:
    """Execute a threat intel feed pull triggered by cron.

    This is called from the cron callback when a ``__threat_intel__:`` message
    is received. It runs the appropriate feed puller with ``trigger="schedule"``.
    """
    from secbot.threat_intel.db import get_session, init_engine
    from secbot.threat_intel.feeds import (
        import_mitre_groups,
        pull_cisa_kev,
        pull_threatfox,
    )

    init_engine()

    async with get_session() as session:
        if source == "cisa_kev":
            result = await pull_cisa_kev(session, trigger="schedule")
        elif source == "threatfox":
            result = await pull_threatfox(session, trigger="schedule")
        elif source == "mitre":
            result = await import_mitre_groups(session, trigger="schedule")
        else:
            _logger.warning("Unknown threat intel source: %s", source)
            return {"error": f"Unknown source: {source}"}

    _logger.info(
        "Threat intel cron: source=%s status=%s inserted=%d updated=%d",
        source, result.get("status"), result.get("inserted"), result.get("updated"),
    )
    return result
