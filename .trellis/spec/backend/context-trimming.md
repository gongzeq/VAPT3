# Context Trimming

> Defines what enters the LLM context and what stays on disk.
> Implementation: `secbot/agent/context.py` + `secbot/agent/autocompact.py`.

---

## 1. Two-Path Output Rule

Every skill produces two outputs, going to two different destinations:

| Output | Destination | Size budget | Lifetime |
|--------|-------------|-------------|----------|
| `summary_json` | LLM context (next turn) + WebUI MessageBubble | ≤ 4 KB after trimming | One conversation |
| `raw_log_path` | Disk: `~/.secbot/scans/<scan_id>/raw/<skill>.log` | Unbounded | Until user deletes |

Anything that does not fit `summary_json`'s budget MUST be truncated and a `raw_log_path` reference inserted. The LLM never sees raw stdout.

---

## 2. summary_json Trimming Policy

The trim policy is driven by the SKILL's `summary_size_hint`:

| Hint | Per-array cap | Per-string cap | Example |
|------|---------------|----------------|---------|
| `small` | 50 items | 256 chars | port lists, host lists |
| `medium` | 20 items | 1 KB | service banner samples |
| `large` | 10 items | 2 KB | nuclei finding details |

When trimming truncates an array or string, the parent object MUST gain a `_truncated` field:

```json
{
  "hosts_up": ["10.0.0.1", "10.0.0.2", "..."],
  "_truncated": {
    "hosts_up": {"shown": 50, "total": 1247, "raw_log_path": "/Users/.../raw/nmap.log"}
  }
}
```

The Orchestrator prompt instructs the LLM to read `_truncated` and tell the user where the full data lives.

---

## 3. Conversation-Level Compaction

`secbot/agent/autocompact.py` (existing nanobot module, kept) runs when the message-history token estimate exceeds **70%** of the model's context window.

### 3.1 What gets compacted

| Item | Action |
|------|--------|
| `tool_result` events older than the last 3 turns | Replace `summary_json` with `{"compacted": true, "raw_log_path": "..."}`. |
| Long assistant messages (> 1 KB, > 5 turns old) | Replace with a one-line summary the autocompactor produces. |
| `plan` events | Keep only the latest plan; older plans are dropped (the WebUI keeps its own copy for display). |

### 3.2 What is never compacted

- The system prompt.
- The original user request (turn 0 user message).
- Any `confirm_*` audit events from [high-risk-confirmation.md §4](./high-risk-confirmation.md#4-logging--audit) — these stay verbatim for trust-and-safety review.
- Any message containing a `findings[]` array — findings are compact and load-bearing for the report.

---

## 4. Disk Layout

```
~/.secbot/scans/<scan_id>/
├── raw/
│   ├── nmap-host-discovery.log
│   ├── nmap-port-scan.log
│   ├── nuclei-template-scan.log
│   └── ...
├── findings.json        # accumulator written by `findings[]` skill outputs
├── plan.json            # final plan timeline snapshot
└── summary.md           # human-readable scan summary used by report skills
```

- `<scan_id>` is the UUID generated at scan start; surfaced in the WebUI ScanHistory view.
- The directory is created by the loop, not by skills, before the first skill runs.
- Skills MUST write only to their own `raw/<skill>.log` plus the structured returns; arbitrary file writes are review-blocking.

---

## 5. WebUI Hooks

- `_truncated` blocks render as a "Truncated — open raw log" inline link in [ScanResultTable](../frontend/component-patterns.md#1-messagebubble-triplet).
- The `raw_log_path` is exposed via REST `GET /api/scans/{scan_id}/raw/{skill}` (covered by [cmdb-schema.md](./cmdb-schema.md) `raw_logs` table); never via WebSocket.
- Logs are streamed in 64 KB chunks; the WebUI uses a virtual scroller (no library dep — built on shadcn ScrollArea per [frontend/visualization-libraries.md](../frontend/visualization-libraries.md)).

---

## 6. Forbidden Patterns

| Anti-pattern | Why |
|--------------|-----|
| Inlining raw log content in `summary_json` | Defeats the 4 KB budget; risks model-side blow-up. |
| Compacting `confirm_*` events | Destroys the audit trail. |
| Skill-side decision to "skip writing the raw log" | The LLM may need to re-examine; always write the raw log even if `summary` is small. |
| Multiple skills sharing one raw-log file | One file per `(scan_id, skill)`; simplifies cleanup and re-runs. |

---

## 7. Test Requirements

- `tests/agent/test_summary_trim.py`: each `summary_size_hint` produces the expected cap; `_truncated` annotation is correctly attached.
- `tests/agent/test_autocompact_preserves_audit.py`: confirm events are preserved through compaction.
- `tests/skills/<each>/test_raw_log_written.py`: skill always writes a raw log, even on subprocess error.
