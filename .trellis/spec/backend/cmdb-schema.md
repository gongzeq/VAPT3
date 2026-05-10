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
| `tags` | JSON | structured object. **Reserved keys** (see §2.1.1): `system` (business system), `type` (asset class). Free-form extras permitted. |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | **reserved for multi-user**, see §4 |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC, bumped on any field change |

Indexes: `(actor_id, ip)`, `(actor_id, hostname)`, `(scan_id)`.

#### 2.1.1 `asset.tags` reserved keys

The `tags` JSON column doubles as a lightweight classification store. To keep dashboard aggregations cheap and consistent across agents, two keys are reserved:

| Key | Type | Values | Source |
|-----|------|--------|--------|
| `system` | string | Business system name, e.g. `"CRM"`, `"ERP"`, `"官网"`, `"OA"`, `"支付"`, `"大数据"`, `"BI"`, `"内部工具"`. May be `null` when unknown. | `asset_discovery` classifies based on target hostname/domain rules or user-supplied scope. |
| `type` | string | One of `"web_app" / "api" / "database" / "server" / "network" / "other"`. | `asset_discovery` sets based on open-port heuristics; `other` as fallback. |

**Rules**

- Aggregation queries (see [dashboard-aggregation.md](./dashboard-aggregation.md)) read via `json_extract(tags, '$.system')` / `'$.type'`. Assets without these keys are excluded from `asset-cluster` and counted as `other` in `asset-distribution`.
- Reserved keys MUST NOT be used for free-form labels; use additional keys (e.g. `tags.labels`) for that.
- Changing the accepted vocabulary requires updating this spec + dashboard-aggregation.md; the backend returns display names (e.g. `"Web 应用"`) directly so the frontend does not need a separate mapping table.

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
| `category` | TEXT NOT NULL | one of `cve` / `weak_password` / `misconfig` / `exposure` / `injection` / `auth` / `xss` / `other`. See §2.3.1 for grouping semantics. |
| `title` | TEXT NOT NULL | human-readable |
| `cve_id` | TEXT | nullable, e.g. `CVE-2024-1234` |
| `evidence` | JSON | structured evidence (request, response snippet, credentials hash) |
| `raw_log_path` | TEXT | path to raw skill log, see [context-trimming.md §1](./context-trimming.md#1-two-path-output-rule) |
| `discovered_by` | TEXT NOT NULL | skill name, e.g. `nuclei-template-scan` |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | |
| `created_at` | DATETIME NOT NULL | |

Indexes: `(actor_id, severity, created_at)`, `(asset_id)`.

#### 2.3.1 `vulnerability.category` vocabulary

A single flat enum, shared with `/api/dashboard/vuln-distribution`:

| Value | Display name | Typical finding |
|-------|--------------|-----------------|
| `injection` | 注入 | SQLi / command injection / template injection |
| `auth` | 认证缺陷 | broken auth, session fixation, privilege escalation |
| `xss` | XSS | reflected / stored / DOM-based XSS |
| `misconfig` | 配置错误 | weak TLS, exposed admin panel, default passwords at path level |
| `exposure` | 敏感数据暴露 | credentials in response, backup file leak, .git/.svn exposure |
| `weak_password` | 弱口令 | dictionary-hit credentials on SSH/RDP/SMB/etc. (produced by `weak_password` agent) |
| `cve` | CVE | known CVE matched by fingerprint (produced by `vuln_scan` agent) |
| `other` | 其他 | anything that does not fit above |

**Rules**

- `VALID_VULN_CATEGORIES` in `secbot/cmdb/models.py` MUST exactly match this list.
- Discovery skills decide the category at insertion time; post-hoc reclassification requires an update migration.
- New categories require an ADR + update to this spec + dashboard-aggregation.md.

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

### 2.5 `report_meta`

Persistent metadata for generated reports (see [report-meta.md](./report-meta.md) for full contract and [report-pipeline.md](./report-pipeline.md) for the render path).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | ULID-flavoured, formatted as `RPT-YYYY-MMDD-<seq>` at display layer |
| `scan_id` | TEXT NOT NULL | FK → `scan.id` |
| `title` | TEXT NOT NULL | human-readable |
| `type` | TEXT NOT NULL | `compliance_monthly` / `vuln_summary` / `asset_inventory` / `custom` |
| `status` | TEXT NOT NULL | `published` / `pending_review` / `editing` / `archived` |
| `critical_count` | INTEGER NOT NULL DEFAULT 0 | denormalised snapshot taken at build time |
| `author` | TEXT NOT NULL | actor_id of the triggering user/agent |
| `download_path` | TEXT | relative to `~/.secbot/reports/`, may be NULL if only markdown rendered |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | |
| `created_at` | DATETIME NOT NULL | |

Indexes: `(actor_id, status, created_at DESC)`, `(scan_id)`.

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
