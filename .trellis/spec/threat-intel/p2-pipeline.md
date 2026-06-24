# P2 Pipeline Spec: LLM Extraction, Maritime, Lifecycle & Review

> Spec for P2 features: maritime intelligence LLM extraction pipeline, maritime detail page, data expiry & archival, and low-confidence review queue.
> Source: `docs/prd-threat-intelligence.md` §4.5 (非结构化源处理) + §7.2 (海事动态详情页) + §8 P2.

---

## 1. Maritime LLM Extraction Pipeline

### 1.1 Overview

Three maritime sources have no structured API — they publish HTML pages or PDF reports. An LLM extracts structured event data from unstructured content.

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐     ┌───────────────┐
│  IMO GISIS  │     │              │     │                  │     │               │
│  (HTML)     │────▶│  Fetch +     │────▶│  LLM Extraction  │────▶│  MaritimeEvent│
│  UKMTO      │     │  Parse       │     │  (structured     │     │  upsert       │
│  (HTML/PDF) │────▶│  (aiohttp +  │     │   JSON output)   │     │  (repo.py)    │
│  ReCAAP     │     │  pdfplumber) │     │                  │     │               │
│  (PDF)      │────▶│              │     │                  │     │               │
└─────────────┘     └──────────────┘     └──────────────────┘     └───────────────┘
```

### 1.2 Data Sources

| Source | URL | Format | Coverage | Schedule |
|--------|-----|--------|----------|----------|
| IMO GISIS | https://gisis.imo.org/Public/Default.aspx | HTML (requires registration) | Global piracy/armed robbery | Weekly |
| UKMTO | https://www.ukmto.org/reports | HTML + PDF | Middle East / Indian Ocean / Red Sea / Gulf of Guinea | Weekly |
| ReCAAP ISC | https://www.recaap.org/resources | PDF reports | Asia (Malacca/Singapore/South China Sea/Sulu Sea) | Monthly |

> **Additional source**: JMIC (https://jmic.org) — Joint Maritime Information Center, publishes threat assessments as PDF. Can be added as P2 stretch.

### 1.3 Source-Specific Details

#### 1.3.1 IMO GISIS

- **URL**: https://gisis.imo.org/Public/Default.aspx (Piracy module)
- **Access**: Requires free IMO account registration. Session-based auth (cookies).
- **Content**: HTML table of piracy/armed robbery incidents with columns: Date, Location, Coordinates, Description, Severity.
- **Fetch approach**:
  ```python
  async def fetch_imo_gisis(session: aiohttp.ClientSession) -> list[dict]:
      """Fetch IMO GISIS piracy incidents as raw HTML."""
      # 1. Login with stored credentials (IMO_GISIS_USER, IMO_GISIS_PASS env vars)
      # 2. Navigate to piracy incidents page
      # 3. Fetch HTML table
      # 4. Return raw HTML for LLM extraction
  ```
- **Fallback**: If login fails, use public summary page (limited data).

#### 1.3.2 UKMTO

- **URL**: https://www.ukmto.org/reports
- **Access**: Public, no registration.
- **Content**: HTML reports page with recent security warnings and incident reports. Some linked as PDF.
- **Fetch approach**:
  ```python
  async def fetch_ukmto(session: aiohttp.ClientSession) -> list[dict]:
      """Fetch UKMTO reports page."""
      # 1. GET https://www.ukmto.org/reports
      # 2. Parse HTML for report links
      # 3. Fetch each linked PDF (if any)
      # 4. Return combined text content
  ```

#### 1.3.3 ReCAAP ISC

- **URL**: https://www.recaap.org/resources
- **Access**: Public, no registration.
- **Content**: PDF reports (monthly/quarterly/annual). Each report contains incident descriptions with location, date, and details.
- **Fetch approach**:
  ```python
  async def fetch_recaap(session: aiohttp.ClientSession) -> list[dict]:
      """Fetch ReCAAP ISC reports."""
      # 1. GET https://www.recaap.org/resources
      # 2. Parse HTML for PDF links (filter for "Incident" reports)
      # 3. Download each PDF
      # 4. Extract text with pdfplumber
      # 5. Return text chunks for LLM extraction
  ```

### 1.4 PDF Text Extraction

Use `pdfplumber` (add to `pyproject.toml` dependencies):

```python
import pdfplumber

def extract_pdf_text(pdf_path: str) -> list[str]:
    """Extract text from PDF, return page-by-page text chunks."""
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                chunks.append(text)
    return chunks
```

### 1.5 LLM Extraction Prompt

The LLM extracts structured maritime events from unstructured text:

```python
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
```

### 1.6 LLM Call Implementation

```python
async def extract_maritime_events(
    text_chunks: list[str],
    source: str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Extract structured maritime events from text using LLM.
    
    Returns list of event dicts ready for upsert_maritime_event().
    """
    from secbot.providers import get_llm_client  # Reuse existing provider

    llm = get_llm_client()
    all_events = []

    for chunk in text_chunks:
        prompt = MARITIME_EXTRACTION_PROMPT.format(text=chunk)
        response = await llm.complete(prompt, temperature=0.1)

        # Parse JSON response (strip markdown code fences if present)
        try:
            events = json.loads(_strip_code_fences(response))
        except json.JSONDecodeError:
            _logger.warning("LLM returned invalid JSON for maritime extraction")
            continue

        for event in events:
            # Compute extraction confidence based on field completeness
            event["extraction_confidence"] = _compute_confidence(event)
            event["source"] = source
            event["source_url"] = source_url or event.get("source_url")
            all_events.append(event)

    return all_events


def _compute_confidence(event: dict) -> float:
    """Compute extraction confidence based on field completeness."""
    score = 0.0
    required = ["event_type", "title", "event_date"]
    optional = ["description", "location", "severity"]

    for field in required:
        if event.get(field):
            score += 0.2  # 0.6 total for required fields

    for field in optional:
        if event.get(field):
            score += 0.1  # 0.3 total for optional fields

    # Bonus for valid coordinates
    loc = event.get("location", {})
    if loc.get("lat") and loc.get("lon"):
        score += 0.1

    return min(score, 1.0)
```

### 1.7 Confidence Threshold

- `extraction_confidence >= 0.65`: Event is ingested with `verification_status="unreviewed"`, appears in overview "recent events" count.
- `extraction_confidence < 0.65`: Event is ingested with `verification_status="unreviewed"` but does NOT appear in overview "recent events" count. Only visible in the review queue.
- `extraction_confidence < 0.4`: Event is NOT ingested. Counted as `unmapped_count` in Feed Pull Run.

### 1.8 Feed Pull Flow

```python
async def pull_maritime(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    source: str = "imo",  # "imo" | "ukmto" | "recaap"
) -> dict[str, Any]:
    """Pull maritime intelligence from a source using LLM extraction."""
    run = await create_feed_pull_run(session, source=source, trigger=trigger)
    run_id = run.id

    inserted = 0
    updated = 0
    skipped = 0
    unmapped = 0
    error_msg = None
    metadata = {}

    try:
        # 1. Fetch raw content (HTML/PDF)
        async with aiohttp.ClientSession() as http:
            if source == "imo":
                raw_content = await fetch_imo_gisis(http)
            elif source == "ukmto":
                raw_content = await fetch_ukmto(http)
            elif source == "recaap":
                raw_content = await fetch_recaap(http)
            else:
                raise ValueError(f"Unknown maritime source: {source}")

        # 2. Extract text chunks
        text_chunks = _normalize_content(raw_content)
        metadata["text_chunks"] = len(text_chunks)

        # 3. LLM extraction
        events = await extract_maritime_events(text_chunks, source=source, source_url=...)
        metadata["extracted_events"] = len(events)

        # 4. Filter + upsert
        for event in events:
            confidence = event.get("extraction_confidence", 0.0)
            if confidence < 0.4:
                unmapped += 1
                continue

            try:
                _, created = await upsert_maritime_event(
                    session,
                    event_type=event["event_type"],
                    title=event["title"],
                    description=event.get("description"),
                    location=event.get("location"),
                    severity=event.get("severity", "medium"),
                    event_date=_parse_event_date(event.get("event_date")),
                    source=source,
                    source_url=event.get("source_url"),
                    extraction_confidence=confidence,
                    verification_status="unreviewed",
                    source_refs=[{
                        "source": source,
                        "url": event.get("source_url"),
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "confidence": confidence,
                        "metadata": {"llm_extracted": True}
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

    # Status determination (same as other feeds)
    status = "ok" if error_msg is None else "failed"
    if error_msg is None and unmapped > 0:
        status = "partial"

    await finish_feed_pull_run(
        session, run_id=run_id, status=status,
        inserted_count=inserted, updated_count=updated,
        skipped_count=skipped, unmapped_count=unmapped,
        error_message=error_msg, metadata_json=metadata,
    )

    return {
        "run_id": run_id, "source": source, "status": status,
        "inserted": inserted, "updated": updated,
        "skipped": skipped, "unmapped": unmapped,
        "error": error_msg, "metadata": metadata,
    }
```

### 1.9 Scheduler

| Job ID | Source | Schedule | Notes |
|--------|--------|----------|-------|
| `threat-intel-maritime-imo` | `imo` | `0 6 * * 1` (weekly Mon 06:00 UTC) | IMO GISIS weekly |
| `threat-intel-maritime-ukmto` | `ukmto` | `0 6 * * 2` (weekly Tue 06:00 UTC) | UKMTO weekly |
| `threat-intel-maritime-recaap` | `recaap` | `0 6 1 * *` (1st of month 06:00 UTC) | ReCAAP monthly |

### 1.10 Good/Base/Bad

- **Good**: UKMTO page yields 3 text chunks, LLM extracts 5 events, 4 with confidence ≥0.65, 1 with confidence 0.5 → 5 ingested (4 visible in overview, 1 in review queue only).
- **Base**: Source page has no new content since last pull → 0 events extracted, status `ok`.
- **Bad**: LLM API timeout during extraction → status `failed`, `error_message` contains timeout hint, 0 events ingested.

### 1.11 Wrong vs Correct

**Wrong**: Storing the full LLM response text in `MaritimeEvent.description` — bloats DB with unstructured text.

**Correct**: LLM extracts a concise `description` (max 500 chars). The full source page URL is stored in `source_url` for human verification.

**Wrong**: Setting `verification_status="confirmed"` for high-confidence LLM extractions — confidence ≠ verification.

**Correct**: All LLM-extracted events start as `verification_status="unreviewed"`. Only human review can set `confirmed` or `dismissed`.

---

## 2. Maritime Detail Page

### 2.1 Route

`/threat-intel/maritime` — registered in `webui/src/App.tsx`.

### 2.2 Component: `MaritimePage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ 海事安全事件                              │
│                                          │
│ [事件类型▾] [严重性▾] [时间范围] [状态▾] │
│                                          │
│ ┌──────────────────────────────────────┐ │
│ │ 🏴‍☠️ 海盗袭击 - 几内亚湾               │ │
│ │ 2026-06-15 14:30 | 严重 | 待审        │ │
│ │ 描述: 一艘散货船在拉各斯西南...        │ │
│ │ 位置: 几内亚湾 (6°N 3°E)              │ │
│ │ 来源: UKMTO → https://www.ukmto.org  │ │
│ │ [确认] [驳回]                         │ │
│ ├──────────────────────────────────────┤ │
│ │ ⚠️ GNSS干扰 - 东海                    │ │
│ │ 2026-06-10 08:00 | 中等 | 已确认      │ │
│ │ ...                                  │ │
│ └──────────────────────────────────────┘ │
│                                          │
│ 分页: < 1 2 3 >                          │
└──────────────────────────────────────────┘
```

### 2.3 Features

| Feature | Implementation |
|---------|---------------|
| List events | `GET /maritime` (P0, already supports filters) |
| Filter by type | `event_type` param: piracy/security_warning/gnss_interference/navigation_warning |
| Filter by severity | `severity` param: critical/high/medium/low |
| Filter by date range | `from` + `to` params |
| Filter by verification status | `verification_status` param: unreviewed/confirmed/dismissed |
| Source link | Each event shows `source_url` as clickable external link |
| Review action | `PATCH /maritime/:id` to update `verification_status` (NEW) |
| Event type icon | lucide-react: `Skull` (piracy), `AlertTriangle` (warning), `Radio` (gnss), `Compass` (navigation) |

### 2.4 Review Action API (NEW)

```
PATCH /api/threat-intel/maritime/:id
Content-Type: application/json

{
  "verification_status": "confirmed"  // or "dismissed"
}
```

**Handler**:
```python
async def handle_review_maritime(request: web.Request) -> web.Response:
    """PATCH /api/threat-intel/maritime/{id} — update verification status."""
    await _ensure_engine()
    event_id = request.match_info["id"]
    body = await request.json()
    new_status = body.get("verification_status")

    valid_statuses = {"unreviewed", "confirmed", "dismissed"}
    if new_status not in valid_statuses:
        return _error(400, "invalid_status",
            f"verification_status must be one of: {', '.join(sorted(valid_statuses))}")

    async with get_session() as session:
        result = await session.execute(
            select(MaritimeEvent).where(MaritimeEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return _error(404, "not_found", f"Maritime event {event_id} not found")
        event.verification_status = new_status

    return web.json_response({
        "id": event_id,
        "verification_status": new_status,
        "updated": True,
    })
```

### 2.5 Overview Integration

The Overview API (`get_overview()`) already returns `maritime_events` card data. P2 adds:
- `recent_count` should only count events with `extraction_confidence >= 0.65` AND `verification_status != "dismissed"`.
- `latest` should be the most recent event with `extraction_confidence >= 0.65`.

```python
# Update in get_overview():
recent_maritime = (await session.execute(
    select(MaritimeEvent)
    .where(
        and_(
            MaritimeEvent.event_date >= seven_days_ago,
            MaritimeEvent.extraction_confidence >= 0.65,
            MaritimeEvent.verification_status != "dismissed",
        )
    )
    .order_by(MaritimeEvent.event_date.desc())
    .limit(1)
)).scalar_one_or_none()
```

---

## 3. Data Expiry & Archival

### 3.1 Policy

| Entity | Expiry Rule | Action |
|--------|------------|--------|
| ThreatInfraIP | `status="inactive"` AND `last_seen < now - 90 days` | Set `status="archived"` (new enum value) or delete |
| ThreatInfraIP | `status="active"` AND `last_seen < now - 180 days` | Auto-set `status="inactive"` then archive after 90 more days |
| ThreatInfraURL | `status="active"` AND `last_seen < now - 180 days` | Auto-set `status="inactive"` |
| ThreatInfraURL | `status="inactive"` AND `last_seen < now - 90 days` | Set `status="archived"` |
| RansomwareEvent | `breach_date < now - 365 days` | Delete (all events, regardless of severity) |
| MaritimeEvent | `event_date < now - 365 days` AND `verification_status="dismissed"` | Delete |
| FeedPullRun | `started_at < now - 90 days` | Delete (keep recent 90 days) |

### 3.2 Archive vs Delete

**ThreatInfraIP**: Use `status="archived"` (add to `IP_STATUSES` enum). Archived IPs are excluded from:
- Overview `active_c2_ips` count
- Graph API (unless explicitly filtered)
- List API default view (unless `status=archived` filter is passed)

**MaritimeEvent**: Hard delete for dismissed events >1 year old. Confirmed events are never deleted.

**ThreatInfraURL**: Same 3-stage lifecycle as ThreatInfraIP (active → inactive at 180d → archived at 90d more). Archived URLs excluded from overview, graph, and list API default view.

**RansomwareEvent**: Hard delete for all events >1 year old. Ransomware events are time-sensitive threat intelligence; historical data beyond 1 year has limited operational value.

**FeedPullRun**: Hard delete. Historical data is not needed beyond 90 days.

### 3.3 Implementation: Expiry Job

```python
async def run_expiry_sweep(session: AsyncSession) -> dict[str, int]:
    """Run data expiry sweep. Returns counts of archived/deleted records."""
    now = _utcnow()
    archived_ips = 0
    auto_inactive_ips = 0
    deleted_maritime = 0
    deleted_runs = 0

    # 1. Auto-inactive: active IPs not seen in 180 days
    result = await session.execute(
        select(ThreatInfraIP).where(
            and_(
                ThreatInfraIP.status == "active",
                ThreatInfraIP.last_seen < now - timedelta(days=180),
            )
        )
    )
    for ip in result.scalars():
        ip.status = "inactive"
        auto_inactive_ips += 1

    # 2. Archive: inactive IPs not seen in 90 days
    result = await session.execute(
        select(ThreatInfraIP).where(
            and_(
                ThreatInfraIP.status == "inactive",
                ThreatInfraIP.last_seen < now - timedelta(days=90),
            )
        )
    )
    for ip in result.scalars():
        ip.status = "archived"
        archived_ips += 1

    # 3. Delete old dismissed maritime events
    result = await session.execute(
        select(MaritimeEvent).where(
            and_(
                MaritimeEvent.event_date < now - timedelta(days=365),
                MaritimeEvent.verification_status == "dismissed",
            )
        )
    )
    for event in result.scalars():
        await session.delete(event)
        deleted_maritime += 1

    # 4. Delete old feed runs
    result = await session.execute(
        select(FeedPullRun).where(
            FeedPullRun.started_at < now - timedelta(days=90)
        )
    )
    for run in result.scalars():
        await session.delete(run)
        deleted_runs += 1

    # 5. Auto-inactive URLs not seen in 180 days (P3)
    # 6. Archive inactive URLs not seen in 90 days (P3)
    # 7. Delete ransomware events >1 year old (P3)
    # ... (same pattern as IP expiry for URLs, hard delete for ransomware)

    return {
        "auto_inactive_ips": auto_inactive_ips,
        "archived_ips": archived_ips,
        "deleted_maritime": deleted_maritime,
        "deleted_runs": deleted_runs,
        "auto_inactive_urls": auto_inactive_urls,
        "archived_urls": archived_urls,
        "deleted_ransomware": deleted_ransomware,
    }
```

### 3.4 Scheduler

| Job ID | Source | Schedule |
|--------|--------|----------|
| `threat-intel-expiry-sweep` | `expiry` | `0 2 * * 0` (weekly Sun 02:00 UTC) |

### 3.5 Enum Update

In `models.py`:
```python
IP_STATUSES = ("active", "inactive", "archived")  # Add "archived"
```

### 3.6 API List Filter Update

In `repo.py::list_threat_infra_ips()`:
```python
if status:
    stmt = stmt.where(ThreatInfraIP.status == status)
else:
    # Default: exclude archived
    stmt = stmt.where(ThreatInfraIP.status != "archived")
```

---

## 4. Low-Confidence Review Queue

### 4.1 Purpose

Records with low mapping confidence (e.g., ThreatFox IOCs with `confidence < 0.5`, maritime events with `extraction_confidence < 0.65`) need human review before being trusted.

### 4.2 Review Queue API (NEW)

```
GET /api/threat-intel/review-queue?type=<entity_type>&page=1&page_size=20
```

**Parameters**:
| Param | Values | Description |
|-------|--------|-------------|
| `type` | `ip` / `malware` / `maritime` / `vuln_assoc` | Entity type to review |
| `min_confidence` | float (default 0.0) | Lower bound (inclusive) |
| `max_confidence` | float (default 0.65) | Upper bound (exclusive) — records below this need review |

**Response**:
```json
{
  "items": [
    {
      "id": "01HQ...",
      "entity_type": "ip",
      "label": "192.168.1.1",
      "confidence": 0.3,
      "group_id": "01HQ...",
      "group_name": "APT41 (low conf.)",
      "source": "threatfox",
      "source_refs": [...],
      "review_action": "confirm_mapping"  // or "remap" or "dismiss"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 45
}
```

### 4.3 Review Actions

```
POST /api/threat-intel/review-queue/:id/action
Content-Type: application/json

{
  "action": "confirm_mapping",   // Confirm current group mapping is correct
  "note": "Verified via OSINT research"
}
```

**Actions**:
| Action | Effect |
|--------|--------|
| `confirm_mapping` | Set `confidence` to `max(confidence, 0.8)`, mark as reviewed |
| `remap` | Body includes `new_group_id` — update `group_id`, set `confidence` to 0.8 |
| `dismiss` | For maritime events: set `verification_status="dismissed"`. For IPs: set `status="archived"` |

### 4.4 Implementation

```python
async def handle_review_queue_list(request: web.Request) -> web.Response:
    """GET /api/threat-intel/review-queue — list low-confidence records."""
    await _ensure_engine()
    entity_type = _query_param(request, "type", "ip")
    max_conf = float(_query_param(request, "max_confidence", "0.65"))
    page = _int_param(request, "page", 1)
    page_size = _int_param(request, "page_size", 20)

    async with get_session() as session:
        items = await get_review_queue(
            session, entity_type=entity_type,
            max_confidence=max_conf, page=page, page_size=page_size,
        )
    return web.json_response(items)


async def handle_review_action(request: web.Request) -> web.Response:
    """POST /api/threat-intel/review-queue/{id}/action — perform review action."""
    await _ensure_engine()
    item_id = request.match_info["id"]
    body = await request.json()
    action = body.get("action")

    async with get_session() as session:
        result = await apply_review_action(
            session, item_id=item_id, action=action, body=body,
        )
    if result is None:
        return _error(404, "not_found", f"Review item {item_id} not found")
    return web.json_response(result)
```

### 4.5 Frontend: Review Queue Page

**Route**: `/threat-intel/review`

**Component**: `ReviewQueuePage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ 低置信度复核队列                          │
│                                          │
│ [IP▾] [置信度 < 0.65]      共 45 条待审   │
│                                          │
│ ┌──────────────────────────────────────┐ │
│ │ 192.168.1.1  置信度: 0.3              │ │
│ │ 当前关联: APT41 (来源: ThreatFox)     │ │
│ │ 来源: https://threatfox.abuse.ch/... │ │
│ │                                      │ │
│ │ [确认关联] [重新关联▾] [驳回归档]     │ │
│ │ 备注: [输入备注...]                   │ │
│ ├──────────────────────────────────────┤ │
│ │ 🏴‍☠️ 海事事件: "海盗袭击"  置信度: 0.5  │ │
│ │ 来源: UKMTO → https://...             │ │
│ │ [确认事件] [驳回]                     │ │
│ └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### 4.6 Review Queue Query Logic

```python
async def get_review_queue(
    session: AsyncSession,
    *,
    entity_type: str = "ip",
    max_confidence: float = 0.65,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Get low-confidence records for human review."""
    limit, offset = _paginate(page, page_size)
    items = []

    if entity_type == "ip":
        stmt = (
            select(ThreatInfraIP, ThreatGroup.name)
            .join(ThreatGroup, ThreatInfraIP.group_id == ThreatGroup.id)
            .where(ThreatInfraIP.confidence < max_confidence)
            .where(ThreatInfraIP.status != "archived")
            .order_by(ThreatInfraIP.confidence.asc())
        )
    elif entity_type == "maritime":
        stmt = (
            select(MaritimeEvent)
            .where(MaritimeEvent.extraction_confidence < max_confidence)
            .where(MaritimeEvent.verification_status == "unreviewed")
            .order_by(MaritimeEvent.extraction_confidence.asc())
        )
    # ... other entity types

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    result = await session.execute(stmt.limit(limit).offset(offset))
    # Build response items...
    return {"items": items, "page": page, "page_size": page_size, "total": total}
```

---

## 5. Dependency Requirements

### 5.1 New Python Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
threat-intel-p2 = [
    "pdfplumber>=0.11.0",  # PDF text extraction for ReCAAP/UKMTO
]
```

### 5.2 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IMO_GISIS_USER` | — | IMO GISIS account username (for piracy module access) |
| `IMO_GISIS_PASS` | — | IMO GISIS account password |
| `OTX_API_KEY` | — | AlienVault OTX API key (P1, also used in P2 for cross-reference) |

---

## 6. Route Registration Summary

New routes for P2:

```python
# Maritime review (P2)
router.add_patch("/api/threat-intel/maritime/{id}", handle_review_maritime)

# Review queue (P2)
router.add_get("/api/threat-intel/review-queue", handle_review_queue_list)
router.add_post("/api/threat-intel/review-queue/{id}/action", handle_review_action)

# Expiry sweep trigger (P2, admin)
router.add_post("/api/threat-intel/expiry-sweep", handle_trigger_expiry_sweep)
```

---

## 7. Forbidden Patterns

| Pattern | Why Forbidden | Do Instead |
|---------|--------------|------------|
| Auto-confirming high-confidence LLM events | Confidence ≠ verification | All LLM events start `unreviewed` |
| Storing full source page text in DB | Bloats DB, duplicates source | Store `source_url` only; LLM extracts concise fields |
| Hard-deleting archived IPs | Loses audit trail | Use `status="archived"`, exclude from default views |
| Deleting confirmed maritime events | Loses verified intelligence | Only delete dismissed events >1 year old |
| Running expiry sweep without scheduler | Could run during peak usage | Schedule weekly at 02:00 UTC |
| LLM extraction without confidence scoring | No way to filter noise | Compute `_compute_confidence()` for every event |
| Batching LLM calls without chunking | Token limit exceeded | Split text into chunks (<4000 chars each) |

---

## 8. Tests Required

### Backend

- [ ] **Maritime extraction**: Mock HTML/PDF → LLM mock returns JSON → events upserted with correct confidence.
- [ ] **Confidence threshold**: Events with confidence <0.4 are not ingested (`unmapped_count` increases).
- [ ] **Overview filter**: Recent maritime count excludes confidence <0.65 and dismissed events.
- [ ] **Review action**: `PATCH /maritime/:id` updates `verification_status`.
- [ ] **Expiry sweep**: IPs inactive >90 days archived, dismissed maritime >1yr deleted.
- [ ] **Review queue**: Low-confidence IPs and maritime events appear in queue.
- [ ] **Review action**: `confirm_mapping` boosts confidence to 0.8.

### Frontend

- [ ] **Maritime page**: Events list with filters, source links, review buttons.
- [ ] **Review queue page**: Low-confidence records with action buttons.
- [ ] **Expiry**: Archived IPs hidden from default list view.

---

## Origin

Source: `docs/prd-threat-intelligence.md` §4.5 (非结构化源处理) + §7.2 (海事动态详情页) + §8 P2 + `开源情报.md` §六 (海事与地理空间情报源).
