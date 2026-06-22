# Threat Intel Development Guidelines

> Spec for the Threat Intel module (`secbot/threat_intel/`, `webui/src/pages/threat-intel/`).
> Source: `docs/prd-threat-intelligence.md` + P0 implementation baseline.
> Covers **P1 and P2** only — P0 is already shipped.

---

## Scope

These guidelines bind every PR that touches `secbot/threat_intel/**`, `secbot/api/threat_intel_routes.py`, or `webui/src/pages/threat-intel/**`. They define **non-negotiable contracts** for data source integration, graph API, detail pages, and LLM extraction pipelines.

---

## P0 Architecture Baseline (already shipped — do not break)

The following patterns are **established in P0** and MUST be followed by all P1/P2 code:

### Storage

- **Independent DB**: `~/.secbot/threat_intel.sqlite3` (override via `SECBOT_THREAT_INTEL_URL`).
- **ORM**: SQLAlchemy 2.x async, `DeclarativeBase` in `secbot/threat_intel/models.py`.
- **Session entry**: `secbot/threat_intel/db.py::get_session()` — the **only** legal session context.
- **PRAGMA**: WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`.
- **10 tables**: `threat_group`, `threat_infra_ip`, `threat_vuln`, `threat_group_vuln_assoc`, `threat_malware_family`, `maritime_event`, `watchlist`, `industry_cpe`, `apt_alias`, `feed_pull_run`.

### Primary Keys & Multi-Tenant

- **ULID** (26-char Crockford base32) for all business tables except `watchlist`, `industry_cpe`, `apt_alias` (auto-increment int).
- `generate_ulid()` in `repo.py` — standalone implementation, no external dep.
- **`actor_id`** on every business table, `NOT NULL DEFAULT 'local'`. Watchlist is scoped by `actor_id`; all other tables are global shared.

### Upsert Pattern (CRITICAL)

Every write uses upsert — duplicate Feed pulls MUST NOT create semantic duplicates:

| Entity | Upsert Key |
|--------|-----------|
| ThreatGroup | `mitre_id` (if set), else `lower(name)` |
| ThreatInfraIP | `(group_id, ip_address, ip_type)` |
| ThreatVuln | `cve_id` |
| ThreatGroupVulnAssoc | `(group_id, vulnerability_id, relationship_type)` |
| ThreatMalwareFamily | `(group_id, lower(family_name))` |
| MaritimeEvent | `(source, source_url, event_date)` or `(source, title, event_date)` |
| Watchlist | `(actor_id, group_id)` |
| AptAlias | `(lower(alias_name), naming_org)` |

Upsert functions return `tuple[Model, bool]` where `bool` = `created`.

### Feed Pull Lifecycle (CRITICAL)

Every Feed puller MUST follow this exact flow:

```
1. create_feed_pull_run(session, source=<source>, trigger=<trigger>)
2. Fetch data (aiohttp, timeout=60s default)
3. For each record:
   a. Parse + validate
   b. Map to ThreatGroup (skip if unmapped → unmapped_count++)
   c. Call upsert_*() → track inserted vs updated
   d. On per-record exception → unmapped_count++
4. finish_feed_pull_run(session, run_id=..., status=..., counts=...)
5. Return summary dict {run_id, source, status, inserted, updated, skipped, unmapped, error, metadata}
```

**Status determination**:
- `error_msg is None and unmapped == 0` → `"ok"`
- `error_msg is None and unmapped > 0` → `"partial"`
- `error_msg is not None` → `"failed"`

### API Layer

- **Framework**: aiohttp, all routes under `/api/threat-intel/`.
- **Lazy engine init**: `_ensure_engine()` calls `get_engine()` (not `init_engine()`) on every request.
- **Error format**: `{"error": {"code": "<prefix.detail>", "message": "<human>"}}`.
- **Pagination**: `_paginate(page, page_size)` clamps to `max 100`. Response: `{items, page, page_size, total}`.
- **Route registration**: `register_routes(app)` in `threat_intel_routes.py`.

### Scheduler

- **Cron prefix**: `__threat_intel__:<source>` (distinct from `__workflow__:`).
- **Daily schedule**: `0 8 * * *` UTC (16:00 Beijing).
- **Callback**: `handle_cron_threat_intel(source)` in `scheduler.py`.
- **Idempotent**: `register_system_job` replaces existing job with same ID.

### Frontend

- **Layout**: `ThreatIntelLayout` applies `bg-slate-50 text-slate-900` (light style).
- **API client**: `webui/src/lib/threat-intel-client.ts` — `request<T>()` generic wrapper with Bearer token.
- **Types**: Mirror backend response shapes exactly.
- **Visual style**: Light background `#F5F7FA`, dual-color gradient nodes, 14-16px rounded cards.

---

## P1/P2 Feature Matrix

| Feature | Phase | Spec File | Key Deliverables |
|---------|-------|-----------|-----------------|
| NVD CVSS≥7.0 feed | P1 | [feed-integration.md](./feed-integration.md) | Daily pull, CVSS/CPE supplement to KEV vulns, rate-limit handling |
| MalwareBazaar feed | P1 | [feed-integration.md](./feed-integration.md) | Sample hashes → ThreatMalwareFamily, group mapping |
| Feodo Tracker feed | P1 | [feed-integration.md](./feed-integration.md) | Botnet C2 IPs → ThreatInfraIP |
| AlienVault OTX feed | P1 | [feed-integration.md](./feed-integration.md) | Industry pulse search, IOC extraction |
| Exploit-DB PoC | P1 | [feed-integration.md](./feed-integration.md) | Git diff, `has_poc`/`exploit_available` marking |
| Industry CPE matching | P1 | [feed-integration.md](./feed-integration.md) | `is_supply_chain` flag, source_refs evidence |
| Graph aggregation API | P1 | [graph-contract.md](./graph-contract.md) | `GET /graph`, nodes+edges, cluster expand |
| Global knowledge graph | P1 | [graph-contract.md](./graph-contract.md) | reactflow force-directed, search/filter/cluster |
| Group detail local graph | P1 | [graph-contract.md](./graph-contract.md) | Radial layout, single-group view |
| Vuln/IP/Malware detail pages | P1 | [detail-and-management.md](./detail-and-management.md) | `GET /vulns/:id`, `/ips/:id`, `/malware/:id` + frontend |
| Watchlist management UI | P1 | [detail-and-management.md](./detail-and-management.md) | Batch view, add/remove, notes |
| APT alias management UI | P1 | [detail-and-management.md](./detail-and-management.md) | CRUD + batch import |
| Feed failure notification | P1 | [detail-and-management.md](./detail-and-management.md) | WebSocket event on failed pull |
| Maritime LLM extraction | P2 | [p2-pipeline.md](./p2-pipeline.md) | IMO GISIS / UKMTO / ReCAAP → MaritimeEvent |
| Maritime detail page | P2 | [p2-pipeline.md](./p2-pipeline.md) | Timeline list, source links, review status |
| Data expiry & archival | P2 | [p2-pipeline.md](./p2-pipeline.md) | Inactive C2 >90d archival |
| Low-confidence review queue | P2 | [p2-pipeline.md](./p2-pipeline.md) | Manual review workflow |

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Feed Integration](./feed-integration.md) | P1 data source contracts: NVD, MalwareBazaar, Feodo, OTX, Exploit-DB + CPE matching | Active |
| [Graph Contract](./graph-contract.md) | Knowledge graph: backend aggregation API + frontend reactflow + interaction + clustering | Active |
| [Detail & Management](./detail-and-management.md) | Detail page APIs + frontend components + Watchlist/Alias management UI + feed notifications | Active |
| [P2 Pipeline](./p2-pipeline.md) | Maritime LLM extraction pipeline + expiry strategy + review queue | Active |
| [Gap Fixes](./gap-fixes.md) | 13 gaps from P1/P2 code review: 3 P0 + 7 P1 + 3 P2 fixes with acceptance criteria | Active |

---

## Pre-Implementation Checklist

Before writing P1/P2 code:

- [ ] Read the relevant spec file(s) listed above.
- [ ] Confirmed upsert key matches P0 pattern (see §Upsert Pattern).
- [ ] Feed puller follows the exact lifecycle (create_feed_pull_run → fetch → upsert → finish_feed_pull_run).
- [ ] New API endpoints follow `/api/threat-intel/` prefix and use `_ensure_engine()` + `get_session()`.
- [ ] Frontend types mirror backend response shapes in `threat-intel-client.ts`.
- [ ] Frontend pages use light style (`bg-slate-50`), not dark VAPT theme.
- [ ] No direct `sqlite3` / raw SQL outside `secbot/threat_intel/`.
- [ ] No writes to CMDB tables from Threat Intel code.
- [ ] `actor_id` parameter present on all Watchlist operations.
- [ ] Source URLs preserved in `source_refs` for human verification.
- [ ] Rate-limit handling (429 response) implemented for external APIs.
- [ ] Tests cover upsert idempotency + unmapped counting + empty/partial/failed states.

---

## Cross-Layer Contracts

These backend specs are consumed by the frontend:

| Contract | Why frontend cares |
|----------|--------------------|
| [feed-integration.md §Feed Pull Response](./feed-integration.md#feed-pull-response-format) | Feed runs page displays counts and status |
| [graph-contract.md §Graph API Response](./graph-contract.md#api-response-structure) | reactflow renders nodes+edges directly |
| [detail-and-management.md §Detail API Response](./detail-and-management.md#detail-api-response-shapes) | Detail pages render response fields |

---

## Authoring Conventions

- **Language**: English for guideline prose; Chinese allowed for product/brand terms (e.g. 海莲花, 威胁情报) or quoted decisions.
- **Examples**: Code examples reference actual P0 files (`secbot/threat_intel/feeds/cisa_kev.py` etc.).
- **Updates**: Use `trellis-update-spec` when a debugging session or code review changes any rule here.

---

## Origin

Source: `docs/prd-threat-intelligence.md` §8 (MVP分期) + P0 implementation baseline (`secbot/threat_intel/`).
