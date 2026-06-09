# Frontend-Backend Gap Analysis

> Identifies gaps between the confirmed frontend template and the current backend implementation. Each gap includes the frontend expectation, the backend reality, and the remediation plan.

---

## Gap Summary

| # | Gap | Frontend Source | Backend Source | Severity | Status |
|---|-----|----------------|----------------|----------|--------|
| G1 | `/api/sessions` missing extended fields | `SessionRow` type, `useSessionsList` | `websocket.py` `_handle_sessions_list` | **P0** | **Done** |
| G2 | `/api/reports?session_key=` filter | `useReports` hook | `websocket.py` `_handle_reports_list` | **P1** | Partial |
| G3 | `query` session type backend support | `ScanType` union, `SessionDetailPage` | `SessionManager` metadata | **P1** | **Done** |
| G4 | Session findings/token rollup | `SessionRow.findings`, `SessionRow.tokens` | Not computed | **P0** | **Done** |

---

## G1: `/api/sessions` Missing Extended Fields

### Frontend Expectation

`SessionRow` type (`lib/types.ts`) requires:

```typescript
interface SessionRow extends ChatSummary {
  target: string | null;        // Scan target (IP/domain/topic)
  scanType: ScanType | null;    // "full" | "vuln" | "weakpwd" | "asset" | "query"
  status: SessionStatus;         // "running" | "finished" | "failed" | "stopped"
  findings: SessionFindingsRollup; // { critical, high, medium, low, total }
  tokens: SessionTokenRollup;    // { input, output, cached }
  durationMs: number | null;     // Wall-clock duration
  reports: ReportRow[];          // Generated report artefacts
}
```

### Backend Reality

`_handle_sessions_list` returns per row:
```json
{ "key": "...", "created_at": "...", "updated_at": "...", "title": "...", "preview": "...", "archived": false }
```

No `target`, `scan_type`, `status`, `findings`, `tokens`, `duration_ms`, or `reports` fields.

### Remediation

1. Extend `SessionManager.list_sessions()` to parse session JSONL metadata line for scan-related fields.
2. The metadata line (`_type: "metadata"`) should be enriched by the agent loop at scan start with:
   - `scan_type`: from the user's first message or `/scan` command argument
   - `target`: extracted from the scan target
   - `status`: tracked as scan progresses (running → finished/failed/stopped)
3. Compute `findings` rollup from the persisted `agent_event` entries with `type: "blackboard_entry"` and `kind: "finding"`.
4. Compute `tokens` rollup from `turn_end` events that carry `usage`.
5. Compute `duration_ms` from `created_at` to the last `turn_end` timestamp.
6. Attach matching `reports` from the `report_meta` table by `session_key`.

### Implementation Notes

- The JSONL metadata line is the first line of each session file (see `secbot/session/manager.py` `list_sessions`).
- `agent_event` rows are persisted with `_kind: "agent_event"` and `agent_event: {...}` payload.
- Token usage arrives via `turn_end` events with `usage: { prompt_tokens, completion_tokens, cached_tokens }`.
- Report metadata lives in `cmdb.db` `report_meta` table (spec: `backend/report-meta.md`).

---

## G2: `/api/reports?session_key=` Filter

### Frontend Expectation

`useReports(sessionKey?)` expects to filter reports by session:
```typescript
function useReports(sessionKey?: string): UseReportsResult
```

### Backend Reality

`_handle_reports_list` supports `range`, `type`, `status`, `limit`, `offset` but NOT `session_key` filtering.

### Remediation

Add `session_key` query parameter to `_handle_reports_list` that filters the `report_meta` table by `session_key` column.

### Current Status

**Partial**: `useReports()` global report list now uses real `GET /api/reports` API. Per-session filtering (`useReports(sessionKey)`) falls back to mock because `report_meta` uses `scan_id` not `session_key` — requires a `scan_id ↔ session_key` mapping or adding `session_key` column to `report_meta`.

---

## G3: `query` Session Type Backend Support

### Frontend Expectation

`ScanType` includes `"query"` for non-scanning sessions (security knowledge queries). The frontend renders different UI for `isQuery = row.scanType === "query"`:
- KPI card shows "会话类型: 安全咨询" instead of findings
- Findings section is hidden
- Timeline labels use "正在处理/会话完成/会话失败"
- Session info label changes from "扫描目标" to "查询主题"

### Backend Reality

The backend has no concept of session type. `scan_type` is not persisted in session metadata.

### Remediation

1. Add `scan_type` to the JSONL metadata line when a session starts.
2. Infer `scan_type` from the first user message:
   - If the message triggers a scan workflow → `"full"`, `"vuln"`, `"weakpwd"`, or `"asset"` based on the scenario.
   - If the message is a conversational query → `"query"`.
3. Persist `target` as the scan target (IP/CIDR) for scan sessions, or the query topic for query sessions.

---

## G4: Session Findings/Token Rollup

### Frontend Expectation

`SessionDetailPage` displays:
- **Findings KPI card**: critical/high/medium/low/total counts
- **Token KPI card**: input/output/cached tokens with cache hit rate
- **Findings section**: severity breakdown with visual bars

### Backend Reality

Neither findings nor token rollups are computed or persisted per session.

### Remediation

1. **Findings rollup**: Parse persisted `agent_event` rows with `type: "blackboard_entry"` and `kind: "finding"`. Extract severity from the `[finding]` prefix text (e.g., `[finding:critical]`). Aggregate into `{critical, high, medium, low, total}`.

2. **Token rollup**: Parse persisted `turn_end` events (injected as system messages or stored in the JSONL). Sum `usage.prompt_tokens`, `usage.completion_tokens`, `usage.cached_tokens` across all turns.

3. **Storage**: Pre-compute on session completion and store in the metadata line, OR compute on-the-fly when reading session messages (the latter is simpler but slower for large sessions).

---

## Implementation Priority

1. **G1 + G4** (P0): **Done** — `_compute_session_rollups()` in `manager.py` computes scan_type, target, status, findings, tokens, duration_ms from JSONL messages. Results cached in metadata `_rollups` field.
2. **G3** (P1): **Done** — scan_type inference from user messages and orchestrator plans, "query" type supported.
3. **G2** (P1): **Partial** — global reports use real API; per-session filter needs `session_key` in `report_meta` table.

---

## Frontend Mock Files (to be replaced)

| Mock File | Hook Consumer | Real API | Status |
|-----------|--------------|----------|--------|
| `lib/mock-sessions.ts` → `MOCK_SESSIONS` | `useSessionsList` | `GET /api/sessions` (extended) | **Replaced** |
| `lib/mock-sessions.ts` → `MOCK_REPORTS` | `useReports` | `GET /api/reports?session_key=` | Global: **Replaced**, Per-session: mock fallback |

After backend implementation, the mock files can be deleted and the hooks switched to real `fetch` calls.
