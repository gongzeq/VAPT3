"""Maritime intelligence LLM extraction pipeline (P2).

Fetches unstructured content from IMO GISIS, UKMTO, and ReCAAP ISC,
extracts structured maritime events using LLM, and upserts as
MaritimeEvent records.

Confidence thresholds:
- >= 0.65: ingested, visible in overview "recent events"
- 0.4 - 0.65: ingested, only visible in review queue
- < 0.4: NOT ingested, counted as unmapped

All LLM-extracted events start with verification_status="unreviewed".
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from secbot.threat_intel.repo import (
    create_feed_pull_run,
    finish_feed_pull_run,
    upsert_maritime_event,
)

_logger = logging.getLogger(__name__)

UKMTO_URL = "https://www.ukmto.org/reports"
RECAAP_URL = "https://www.recaap.org/resources"

MARITIME_EXTRACTION_PROMPT = """You are a maritime security intelligence analyst.

Extract structured maritime security events from the following text. Each event should include:
- event_type: one of "piracy", "security_warning", "gnss_interference", "navigation_warning", "other"
- title: concise event title (max 100 chars)
- description: detailed description (max 500 chars)
- location: object with {lat, lon, region, description} (lat/lon may be null if not specified)
- severity: one of "critical", "high", "medium", "low"
- event_date: ISO 8601 datetime (if date is approximate, use the most specific date)
- source_url: URL if mentioned in the text

Return a JSON array of events. If no events found, return [].

Text:
---
{text}
---

Return ONLY valid JSON, no markdown formatting:
"""


def _compute_confidence(event: dict) -> float:
    """Compute extraction confidence based on field completeness."""
    score = 0.0
    required = ["event_type", "title", "event_date"]
    optional = ["description", "location", "severity"]

    for field in required:
        if event.get(field):
            score += 0.2

    for field in optional:
        if event.get(field):
            score += 0.1

    loc = event.get("location", {})
    if isinstance(loc, dict) and loc.get("lat") and loc.get("lon"):
        score += 0.1

    return min(score, 1.0)


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last line (fences)
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _parse_event_date(value: Any) -> Optional[datetime]:
    """Parse various date formats to datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


async def _fetch_ukmto(http: aiohttp.ClientSession) -> str:
    """Fetch UKMTO reports page as text."""
    async with http.get(UKMTO_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status != 200:
            raise RuntimeError(f"UKMTO fetch failed: HTTP {resp.status}")
        html = await resp.text()

    # Extract text content from HTML (basic extraction)
    # Remove script/style tags
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000]  # Limit text size


async def _fetch_recaap(http: aiohttp.ClientSession) -> str:
    """Fetch ReCAAP resources page as text."""
    async with http.get(RECAAP_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status != 200:
            raise RuntimeError(f"ReCAAP fetch failed: HTTP {resp.status}")
        html = await resp.text()

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000]


async def _extract_maritime_events(
    text_chunks: list[str],
    source: str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Extract structured maritime events from text using LLM.

    Falls back gracefully if LLM is not available.
    """
    all_events: list[dict[str, Any]] = []

    try:
        from secbot.config.loader import load_config
        from secbot.providers.factory import make_provider

        config = load_config()
        provider = make_provider(config)
    except Exception:
        _logger.warning("LLM provider not available, skipping maritime extraction")
        return all_events

    for chunk in text_chunks:
        if not chunk or len(chunk) < 50:
            continue

        prompt = MARITIME_EXTRACTION_PROMPT.format(text=chunk[:4000])
        try:
            response = await provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception as exc:
            _logger.warning("LLM call failed: %s", exc)
            continue

        content = response.content or ""
        try:
            events = json.loads(_strip_code_fences(content))
        except json.JSONDecodeError:
            _logger.warning("LLM returned invalid JSON for maritime extraction")
            continue

        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict):
                continue
            event["extraction_confidence"] = _compute_confidence(event)
            event["source"] = source
            event["source_url"] = source_url or event.get("source_url")
            all_events.append(event)

    return all_events


async def pull_maritime(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    source: str = "ukmto",
) -> dict[str, Any]:
    """Pull maritime intelligence from a source using LLM extraction.

    Args:
        source: One of "ukmto", "recaap", "imo"

    Returns a summary dict with inserted/updated/skipped/unmapped counts.
    """
    run = await create_feed_pull_run(session, source=source, trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg: Optional[str] = None
    metadata: dict[str, Any] = {}

    try:
        _logger.info("Maritime: fetching from source=%s", source)

        async with aiohttp.ClientSession() as http:
            if source == "ukmto":
                raw_content = await _fetch_ukmto(http)
                source_url = UKMTO_URL
            elif source == "recaap":
                raw_content = await _fetch_recaap(http)
                source_url = RECAAP_URL
            elif source == "imo":
                # IMO GISIS requires registration — placeholder for future
                raise RuntimeError("IMO GISIS requires authentication (not yet implemented)")
            else:
                raise ValueError(f"Unknown maritime source: {source}")

        # Split into chunks for LLM processing
        chunk_size = 4000
        text_chunks = [
            raw_content[i:i + chunk_size]
            for i in range(0, len(raw_content), chunk_size)
        ]
        metadata["text_chunks"] = len(text_chunks)

        # LLM extraction
        events = await _extract_maritime_events(text_chunks, source=source, source_url=source_url)
        metadata["extracted_events"] = len(events)

        # Filter + upsert
        for event in events:
            confidence = event.get("extraction_confidence", 0.0)
            if confidence < 0.4:
                unmapped += 1
                continue

            try:
                event_date = _parse_event_date(event.get("event_date"))
                if event_date is None:
                    unmapped += 1
                    continue

                _, created = await upsert_maritime_event(
                    session,
                    event_type=event.get("event_type", "other"),
                    title=event.get("title", "Untitled"),
                    description=event.get("description"),
                    location=event.get("location"),
                    severity=event.get("severity", "medium"),
                    event_date=event_date,
                    source=source,
                    source_url=event.get("source_url"),
                    extraction_confidence=confidence,
                    verification_status="unreviewed",
                    source_refs=[{
                        "source": source,
                        "url": event.get("source_url") or source_url,
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "confidence": confidence,
                        "metadata": {"llm_extracted": True},
                    }],
                )
                if created:
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                _logger.warning("Maritime upsert failed: %s", exc)
                unmapped += 1

    except Exception as exc:
        error_msg = str(exc)
        _logger.error("Maritime pull (%s) failed: %s", source, error_msg)

    status = "ok" if error_msg is None else "failed"
    if error_msg is None and unmapped > 0:
        status = "partial"

    await finish_feed_pull_run(
        session,
        run_id=run_id,
        status=status,
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        unmapped_count=unmapped,
        error_message=error_msg,
        metadata_json=metadata,
    )

    _logger.info(
        "Maritime pull (%s): inserted=%d updated=%d skipped=%d unmapped=%d status=%s",
        source, inserted, updated, skipped, unmapped, status,
    )

    return {
        "run_id": run_id,
        "source": source,
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unmapped": unmapped,
        "error": error_msg,
        "metadata": metadata,
    }
