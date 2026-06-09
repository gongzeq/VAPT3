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
| `system` | string | Business system name, e.g. `"CRM"`, `"ERP"`, `"官网"`, `"OA"`, `"支付"`, `"大数据"`, `"BI"`, `"内部工具"`. May be `null` when unknown. | User-supplied scope, naming rules, or manual tag edits. Unknown values are grouped as `"其他"` in dashboard aggregation. |
| `type` | string | One of `"业务" / "智能体" / "OA" / "中间件" / "支撑" / "内网" / "其他"`. | `asset_discovery` sets the primary business classification from target, scope, service, and product heuristics; `"其他"` as fallback. |

**Rules**

- Aggregation queries (see [dashboard-aggregation.md](./dashboard-aggregation.md)) read via `json_extract(tags, '$.system')` / `'$.type'`. Assets without `system` are grouped as `"其他"` in `asset-cluster`; assets without `type` are counted as `"其他"` in `asset-distribution`.
- Reserved keys MUST NOT be used for free-form labels; use additional keys (e.g. `tags.labels`) for that.
- User-edited `system` / `type` values MUST take precedence over automatic scan classification. Re-scans may fill missing values but MUST NOT overwrite a user-edited tag.
- Changing the accepted vocabulary requires updating this spec + dashboard-aggregation.md; the backend returns display names directly so the frontend does not need a separate mapping table.

#### 2.1.2 Managed Asset ingestion gate

Scan discoveries are transient unless the current Session explicitly enables Asset Auto-Management.

##### 1. Scope / Trigger

- Trigger: a skill result or `asset_push` discovery wants to write `asset` / `service` / `vulnerability` rows from scan output.
- Scope: scan-discovery writes only. Direct repository calls from tests, migrations, or admin maintenance may still call repo helpers explicitly.

##### 2. Signatures

- Session metadata key: `asset_auto_management: boolean`.
- WebUI route: `GET /api/sessions/{encoded_session_key}/asset-auto-management`.
- Update form: same route with `?enabled=1|0` (`true/false/yes/no/on/off` accepted).
- Runtime context: `bind_skill_context(..., asset_auto_management_enabled=<bool>)`.

##### 3. Contracts

- Default is `false` for every channel and every fresh Session.
- Backend gating is authoritative. The frontend switch is only a control surface; writes MUST check the runtime context before CMDB persistence.
- Parent agents and subagents inherit the same gate for a turn.
- Disabled sessions still return tool results and keep transient asset-feed entries; only CMDB side effects are skipped.

##### 4. Validation & Error Matrix

| Input | Result |
|-------|--------|
| Missing metadata key | treat as `false` |
| Non-WebUI session key on WebUI route | `404` |
| Invalid encoded session key | `400` |
| Invalid `enabled` value | `400` |
| Session manager unavailable | `503` |

##### 5. Good/Base/Bad Cases

- Good: WebUI session toggles `enabled=1`; subsequent skill `cmdb_writes` persist assets/services.
- Base: user runs a test scan with no toggle; scan discoveries appear in the live feed but CMDB remains unchanged.
- Bad: non-WebSocket or subagent execution bypasses the switch and writes Managed Assets by default.

##### 6. Tests Required

- Session route defaults off and persists update state.
- Skill `cmdb_writes` are returned but not persisted when disabled.
- Enabled context persists expected CMDB rows.
- Subagent context inherits the parent setting.

##### 7. Wrong vs Correct

Wrong: default `asset_auto_management_enabled=True` outside WebSocket because there is no visible switch.

Correct: default `false` everywhere; only `SessionManager.get_asset_auto_management(session_key)` may enable scan-discovery CMDB writes.

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

Represents a confirmed finding from `vuln_scan` / `weak_password` / `pentest`.

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

### 2.3.2 `vulnerability_candidate`

Represents a passive version/database match that may affect an asset before active verification. Candidates are persistent so asset detail and the Asset Risk Topology can show "待验证" risk, but they are not confirmed findings.

#### 1. Scope / Trigger

- Trigger: a Service fingerprint (`service.product` + `service.version`) matches a vulnerability database entry (CVE, CNVD, or title/category fallback).
- Passive matching MUST NOT start a vulnerability scan, PoC, nuclei template, fscan vuln check, brute force, or other external verification.

#### 2. Signatures

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | autoincrement |
| `asset_id` | INTEGER NOT NULL | FK → `asset.id` |
| `service_id` | INTEGER | FK → `service.id`, nullable for asset-level candidates |
| `identity_key` | TEXT NOT NULL | Stable grouping key; prefer `CVE:<id>`, then `CNVD:<id>`, else `TITLE:<category>:<normalized title>` |
| `cve_id` | TEXT | nullable |
| `cnvd_id` | TEXT | nullable |
| `category` | TEXT NOT NULL | Same vocabulary as `vulnerability.category` |
| `title` | TEXT NOT NULL | human-readable |
| `source` | TEXT NOT NULL | vulnerability database or matcher name |
| `evidence` | JSON | matched product/version, version constraint, references |
| `status` | TEXT NOT NULL | `candidate` / `verified` / `dismissed` |
| `last_verification_error` | TEXT | nullable; failed verification attempts do not dismiss the candidate |
| `actor_id` | TEXT NOT NULL DEFAULT `'local'` | |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC |

Unique: `(actor_id, asset_id, service_id, identity_key)`.

#### 3. Contracts

- `status='candidate'`: default passive match state.
- `status='verified'`: active verification succeeded; the system MUST also create or link a confirmed `vulnerability` row.
- `status='dismissed'`: user dismissal or verification proved the candidate not applicable; hidden from default risk views but still available in asset detail/history.
- Dashboard confirmed vulnerability endpoints MUST NOT count `vulnerability_candidate` rows.
- Asset Risk Topology may show candidates, but must visually distinguish them from confirmed vulnerabilities.

#### 4. Validation & Error Matrix

| Input | Result |
|-------|--------|
| Unknown `status` | reject with validation error before DB write |
| Unknown `category` | reject using `VALID_VULN_CATEGORIES` |
| Repeated candidate for same `(actor_id, asset_id, service_id, identity_key)` | upsert; refresh `evidence` and `updated_at` |
| Verification command fails or times out | keep `status='candidate'`, set `last_verification_error` |
| Candidate verified | upsert confirmed `vulnerability`; set candidate `status='verified'` |

#### 5. Good/Base/Bad Cases

- Good: `nginx 1.18.0` on one service matches `CVE-...`; insert one candidate keyed by the CVE.
- Base: no CVE/CNVD exists; key by normalized `category + title`.
- Bad: repeated scans create duplicate candidates or inflate dashboard confirmed vulnerability counts.

#### 6. Tests Required

- Candidate insert/upsert preserves uniqueness by `(actor_id, asset_id, service_id, identity_key)`.
- Dashboard vulnerability summary/trend/distribution ignore candidates.
- Verification failure leaves status as `candidate`.
- Verification success creates/updates a confirmed `vulnerability` row and marks candidate `verified`.

#### 7. Wrong vs Correct

Wrong: treat a version match as a confirmed vulnerability and include it in `/api/dashboard/vuln-distribution`.

Correct: persist it as `vulnerability_candidate(status='candidate')`, show it as "待验证", and only count it after explicit verification succeeds.

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
