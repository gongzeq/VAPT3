# Report Meta

> Authoritative contract for persistent report metadata (the `report_meta` table) and `/api/reports` endpoints.
> Complements the render pipeline described in [report-pipeline.md](./report-pipeline.md).

---

## 1. Scope & boundary

`report-pipeline.md` handles **how** a report is built (Markdown canonical → DOCX/PDF render, severity colour binding). This spec handles **how report existence is tracked** — i.e. the row written *after* a build succeeds and the read endpoints that surface it to the dashboard's "Recent Reports" module.

```text
build_report_model()                ← report-pipeline.md
        │
        ▼
  render → files on disk            ← report-pipeline.md
        │
        ▼
  insert_report_meta(row)           ← THIS SPEC
        │
        ▼
  GET /api/reports                  ← THIS SPEC
```

---

## 2. Data model

See [cmdb-schema.md §2.5](./cmdb-schema.md#25-report_meta). Recapped here for convenience:

| Column | Type | Constraint |
|--------|------|-----------|
| `id` | TEXT | PK, display format `RPT-YYYY-MMDD-<seq>` |
| `scan_id` | TEXT | NOT NULL, FK → `scan.id` |
| `title` | TEXT | NOT NULL |
| `type` | TEXT | NOT NULL, enum `{compliance_monthly, vuln_summary, asset_inventory, custom}` |
| `status` | TEXT | NOT NULL, enum `{published, pending_review, editing, archived}`, default `published` |
| `critical_count` | INTEGER | NOT NULL DEFAULT 0 |
| `author` | TEXT | NOT NULL (actor_id) |
| `download_path` | TEXT | nullable |
| `actor_id` | TEXT | NOT NULL DEFAULT `'local'` |
| `created_at` | DATETIME | NOT NULL UTC |

Indexes: `(actor_id, status, created_at DESC)`, `(scan_id)`.

---

## 3. Lifecycle rules

### 3.1 Write path

- **One row per successful render.** Callers (Orchestrator / CLI `report` command) invoke `secbot/cmdb/repo.py::insert_report_meta(row)` **after** `build_report_model` finishes and files are flushed to `~/.secbot/reports/`.
- **Never write from inside `build_report_model`.** The builder remains pure; persistence is the caller's concern.
- **Best effort.** If the insert fails, the report files MUST still be considered valid; log a `logger.warning` with `scan_id` and `title`. Do not roll back the render.
- **No implicit re-generation.** Re-running the same scan's report builder creates a new row (new `id`, same `scan_id`). There is no upsert.

### 3.2 `id` format

- Storage: opaque ULID-like TEXT primary key. SQLite does not need the display prefix.
- Display: handler wraps as `RPT-{YYYY}-{MMDD}-{seq}` where `seq` is the 3-digit sequence of reports built on that day for that `actor_id`. Sequence is computed at insert time via `COUNT(*) WHERE DATE(created_at)=today`.
- Clients should treat the display string as opaque.

### 3.3 Status transitions

Allowed transitions (enforced at repo layer; no direct SQL updates):

```
          ┌─ pending_review ─┐
          │                  ▼
editing ──┼─────────→ published ─→ archived
          │                  ▲
          └──────────────────┘
```

- `published ↔ archived` is reversible.
- `editing → published` is the default shortcut for auto-generated reports.
- No transition skips are allowed; use `repo.update_report_status(id, new_status)` which asserts the source state.

### 3.4 Deletion

Hard delete not exposed via API in v1. An operator may manually mark `status='archived'`; true deletion is DB-only for now.

---

## 4. Repo API

`secbot/cmdb/repo.py` gains:

```python
async def insert_report_meta(
    actor_id: str,
    *,
    scan_id: str,
    title: str,
    type: Literal["compliance_monthly","vuln_summary","asset_inventory","custom"],
    status: Literal["published","pending_review","editing","archived"] = "published",
    critical_count: int = 0,
    author: str,
    download_path: str | None = None,
) -> str:
    """Insert a report_meta row, return the new id."""

async def list_reports(
    actor_id: str,
    *,
    range: Literal["7d","30d","all"] = "all",
    type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ReportMeta], int]:
    """(items, total_count)."""

async def get_report(actor_id: str, report_id: str) -> ReportMeta | None: ...

async def update_report_status(actor_id: str, report_id: str, new_status: str) -> None: ...
```

---

## 5. HTTP endpoints

### 5.1 `GET /api/reports?range=7d|30d|all&type=&status=&limit=50&offset=0`

```json
{
  "items": [ { /* see 5.3 */ } ],
  "total": 28,
  "limit": 50,
  "offset": 0
}
```

Defaults: `range=30d`, `limit=50`, `offset=0`. `range` accepts only the 3 listed values; other values → 400.

### 5.2 `GET /api/reports/{id}`

Returns a single row enriched with `download_url`:

```json
{
  "id": "RPT-2026-0510-014",
  "scan_id": "01JS...",
  "title": "DC-IDC-A 段月报",
  "type": "compliance_monthly",
  "status": "published",
  "critical_count": 7,
  "author": "shan",
  "created_at": "2026-05-10T08:00:00+08:00",
  "download_url": "/api/reports/RPT-2026-0510-014/download"
}
```

404 when `actor_id` mismatch or id does not exist.

### 5.3 Item shape (used by 5.1)

Same as 5.2 but **without** `download_url`. Clients call 5.2 when a download is needed.

### 5.4 `GET /api/reports/{id}/download`

Streams the file at `download_path` (relative to `~/.secbot/reports/`) with correct `Content-Type` (`application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, or `text/markdown`). 404 if file missing; the row itself is kept (orphan record) and logged.

---

## 6. Testing

`tests/cmdb/test_report_meta.py` MUST cover:

- Insert → list → get round trip.
- Filter by `range` / `type` / `status` with combinations.
- Pagination: `limit=1, offset=1` returns the 2nd row.
- Status transition enforcement: invalid transitions raise `ValueError`.
- `list_reports` is scoped by `actor_id`: another actor's rows invisible.

`tests/api/test_reports.py`:

- 200 / 400 / 404 paths.
- Empty DB → `{"items": [], "total": 0}`.
- `range=invalid` → 400.

---

## Origin

- `.trellis/tasks/05-10-p1-report-session-prompts/prd.md`
- `webui/src/gap/dashboard-data.md` — "历史报告表格" requirements
- [report-pipeline.md](./report-pipeline.md) — render path this spec complements
