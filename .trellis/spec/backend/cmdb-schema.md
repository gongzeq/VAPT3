# CMDB Schema

> Authoritative schema for the local CMDB (asset / service / vulnerability inventory).
> Implementation: SQLite via SQLAlchemy 2.x async, files under `secbot/cmdb/`.

---

## 1. Storage

- Engine: SQLite (`~/.secbot/cmdb.sqlite3`), single-writer, WAL mode ON.
- Migrations: Alembic, versions under `secbot/cmdb/migrations/versions/`.
- Connection helper: `secbot/cmdb/db.py::get_session()` — the **only** legal entry to the CMDB.

Direct `sqlite3` / raw SQL outside `secbot/cmdb/` is forbidden.

---

## 2. Tables

### 2.1 `asset`

Represents a host or domain discovered by `asset_discovery`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | autoincrement |
| `scan_id` | TEXT NOT NULL | foreign key → `scan.id`, the scan that first discovered it |
| `target` | TEXT NOT NULL | IP / domain / CIDR as supplied by user |
| `ip` | TEXT | resolved IPv4/IPv6, may be NULL for un-resolved domain |
| `hostname` | TEXT | reverse DNS or supplied hostname |
| `os_guess` | TEXT | from nmap `-O` or banner heuristic |
| `tags` | JSON | free-form list, e.g. `["web", "internal"]` |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | **reserved for multi-user**, see §4 |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC, bumped on any field change |

Indexes: `(actor_id, ip)`, `(actor_id, hostname)`, `(scan_id)`.

### 2.2 `service`

Represents an open port + service banner on an `asset`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `asset_id` | INTEGER NOT NULL | FK → `asset.id` |
| `port` | INTEGER NOT NULL | |
| `protocol` | TEXT NOT NULL | `tcp` / `udp` |
| `service` | TEXT | `http`, `ssh`, … |
| `product` | TEXT | banner product, e.g. `nginx` |
| `version` | TEXT | banner version |
| `state` | TEXT NOT NULL | `open` / `filtered` / `closed` |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | |
| `created_at` | DATETIME NOT NULL | |
| `updated_at` | DATETIME NOT NULL | |

Unique: `(asset_id, port, protocol)`.

### 2.3 `vulnerability`

Represents a finding from `vuln_scan` / `weak_password` / `pentest`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `asset_id` | INTEGER NOT NULL | FK → `asset.id` |
| `service_id` | INTEGER | FK → `service.id`, nullable when not port-bound |
| `severity` | TEXT NOT NULL | one of `critical`/`high`/`medium`/`low`/`info` (see [theme-tokens.md §2](../frontend/theme-tokens.md#2-severity-palette)) |
| `category` | TEXT NOT NULL | `cve` / `weak_password` / `misconfig` / `exposure` |
| `title` | TEXT NOT NULL | human-readable |
| `cve_id` | TEXT | nullable, e.g. `CVE-2024-1234` |
| `evidence` | JSON | structured evidence (request, response snippet, credentials hash) |
| `raw_log_path` | TEXT | path to raw skill log, see [context-trimming.md §1](./context-trimming.md#1-two-path-output-rule) |
| `discovered_by` | TEXT NOT NULL | skill name, e.g. `nuclei-template-scan` |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | |
| `created_at` | DATETIME NOT NULL | |

Indexes: `(actor_id, severity, created_at)`, `(asset_id)`.

### 2.4 `scan`

Tracks a single user-initiated scan task. See [scan-lifecycle.md](./scan-lifecycle.md).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | ULID |
| `target` | TEXT NOT NULL | original user input |
| `status` | TEXT NOT NULL | `queued` / `running` / `awaiting_user` / `completed` / `failed` / `cancelled` |
| `scope_json` | JSON | normalised target list + opt-out flags |
| `started_at` | DATETIME | nullable, set on first expert tool call |
| `finished_at` | DATETIME | nullable |
| `error` | TEXT | nullable, set when `status='failed'` |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | |
| `created_at` | DATETIME NOT NULL | |

Indexes: `(actor_id, status)`, `(actor_id, created_at DESC)`.

---

## 3. Write Discipline

- Skills MUST NOT write to the CMDB directly. They emit `summary_json` and the **expert agent** layer calls `secbot/cmdb/repo.py::upsert_*` helpers.
- Upserts are keyed on natural keys (`(actor_id, ip)` for asset; `(asset_id, port, protocol)` for service; `(asset_id, service_id, title, cve_id)` for vulnerability) to keep re-scans idempotent.
- All writes go through a single `async with get_session() as s:` block per expert turn — no cross-turn open transactions.

---

## 4. Multi-Tenant Reservation

Every business table carries `actor_id TEXT NOT NULL DEFAULT 'local'`. In v1 the value is always `'local'`; the column exists so a future "team / RBAC" migration is non-breaking.

**Hard rules**

- Every read query MUST filter by `actor_id`. The repo layer enforces this by always taking `actor_id` as the first argument; raw queries that bypass `actor_id` will be flagged.
- Removing this column or its `NOT NULL` constraint requires an ADR.

---

## 5. Migration Policy

- One Alembic revision per PR that touches the schema. Filenames: `YYYYMMDD_<slug>.py`.
- Online schema changes (add column, add index) only. Destructive changes (drop column, narrow type) require a **two-step** revision: deprecate-then-drop across two releases.
- Test fixture: `tests/cmdb/conftest.py::tmp_cmdb` spins up an in-memory SQLite with all migrations applied — every CMDB-touching test MUST use it.

---

## Origin

Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"Architecture Snapshot" + ADR-002 (single-writer SQLite, actor_id reservation).
