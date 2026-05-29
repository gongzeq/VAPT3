---
name: detection-db-query
display_name: Query Detection Database
version: 1.0.0
risk_level: medium
category: analysis
network_egress: none
expected_runtime_sec: 10
summary_size_hint: medium
---

Query the local SQLite detection-results database (`detection_results.db`) to
retrieve phishing-email detection records and log-analysis results.  This
skill is **strictly read-only** — it never writes, migrates, or alters the
database in any way.

Use this skill when the user asks you to:
- Generate a phishing detection report or summary.
- List recent phishing / suspicious emails with their confidence scores.
- Show log-analysis findings (anomalies, critical events, trends).
- Pull stats or trend data to back a narrative report.
- Inspect raw detection records before formatting them for the user.

## When NOT to use

- For live scanning / detection — this skill only reads **past** results.
- For writing or modifying the database — use a workflow step script instead.

## Actions

Choose the **action** that matches the user's intent:

| action | description | key params |
|--------|-------------|------------|
| `phishing_summary` | Today's phishing count, total, 7-day sparkline | — |
| `phishing_history` | Paginated detection rows with optional search / filter | `page`, `page_size`, `search`, `filter` |
| `phishing_stats` | KPI×4 (today total, phishing, rate, avg duration) + deltas | — |
| `phishing_trend` | Phishing/suspicious/normal counts per day over N days | `days` |
| `phishing_top_senders` | High-risk sender ranking | `limit`, `days` |
| `log_latest` | Most recent log-analysis records | `limit` |
| `log_stats` | Log-analysis aggregate stats | — |
| `db_schema` | Return table schemas so you know what columns are available | — |
| `sql_query` | Execute a **read-only** custom SQL query (SELECT only) | `sql` |

All actions return JSON.  `sql_query` is guarded — UPDATE / INSERT / DELETE /
DROP / ALTER are rejected.

## Arguments

- `action` (string, required): one of the action names above.
- `page` (integer, optional, default 1): page number for paginated queries.
- `page_size` (integer, optional, 1–500, default 50): rows per page.
- `search` (string, optional): free-text search across sender / subject.
- `filter` (string, optional, default "all"): `phishing` | `suspicious` | `normal` | `all`.
- `days` (integer, optional, 1–90, default 7): look-back window for trends / top senders.
- `limit` (integer, optional, 1–500, default 8 for top_senders, 20 for log_latest).
- `sql` (string, required for `sql_query`): a SELECT-only SQL statement.

## Return contract

```json
{
  "action": "phishing_summary",
  "ok": true,
  "data": { ... action-specific payload ... },
  "elapsed_ms": 12
}
```

On error:
```json
{
  "action": "sql_query",
  "ok": false,
  "error": "Only SELECT queries are allowed",
  "elapsed_ms": 1
}
```

## Security

- This skill is **read-only** — no INSERT / UPDATE / DELETE / DROP / ALTER.
- Database path respects `DETECTION_DB_PATH` env var, falling back to the
  project-default location.
- Connection timeout is 1.5 s; missing DB → empty payloads, never a crash.
