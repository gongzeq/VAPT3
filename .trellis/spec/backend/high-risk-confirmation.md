# High-Risk Confirmation

> Defines `risk_level` semantics and the user-confirmation contract for skills that may cause harm.
> Reuses `secbot/agent/tools/ask.py` (formerly `nanobot/agent/tools/ask.py`).

---

## 1. Risk Levels

The `risk_level` field on each [SKILL.md](./skill-contract.md#2-skillmd-front-matter-schema) MUST be one of:

| Level | Meaning | Examples | Confirmation |
|-------|---------|----------|--------------|
| `low` | Read-only, internal data | `cmdb-list-assets`, `report-markdown` | None |
| `medium` | External scan, non-intrusive | `nmap-host-discovery`, `nmap-port-scan` | None |
| `high` | External scan, intrusive but observational | `nuclei-template-scan`, `fscan-vuln-scan` | None (logged only) |
| `critical` | Active exploitation / brute force / data mutation against external assets | `hydra-bruteforce`, `fscan-weak-password`, future `metasploit-exploit-*` | **Required, blocking** |

The classification table is **part of the spec**. Adding a new `critical` skill or downgrading an existing one requires an ADR.

---

## 2. Confirmation Trigger

For every skill with `risk_level: critical`:

1. Before `handler.run()` is called, the loop invokes `ctx.confirm(prompt)`.
2. `ctx.confirm` resolves through `agent/tools/ask.py` and emits a structured event to the Surface (WebUI / CLI).
3. The Surface MUST render per [frontend/component-patterns.md §3 Destructive Confirmation Dialog](../frontend/component-patterns.md#3-destructive-confirmation-dialog).
4. The skill body does NOT run until the user responds.

### 2.1 The confirmation prompt payload

```json
{
  "type": "high_risk_confirm",
  "skill": "hydra-bruteforce",
  "display_name": "Hydra brute-force",
  "risk_level": "critical",
  "summary_for_user": "Will attempt SSH password brute-force against 10.0.0.5 with rockyou.txt (≈14M passwords).",
  "args": {"target": "10.0.0.5", "service": "ssh", "wordlist": "rockyou.txt"},
  "estimated_duration_sec": 1800,
  "destructive_action": true,
  "scan_id": "..."
}
```

`summary_for_user` is composed by the skill's `prepare_confirmation()` hook (mandatory for `critical` skills); it MUST be plain language, name the target, and state the worst-case effect.

---

## 3. User Responses

| Response | Skill behaviour |
|----------|-----------------|
| Approve | `ctx.confirm` returns `True`; `handler.run()` proceeds. |
| Deny | `ctx.confirm` returns `False`; the loop SHORT-CIRCUITS the skill and returns `summary={"user_denied": true}` to the expert agent. The expert agent's prompt MUST instruct it to plan an alternative or stop. |
| Timeout (no response in 120s) | Treated as Deny. Logged separately as `confirm_timeout` for audit. |

The expert agent never sees a "secret approval" path. There is no agent-side override.

---

## 4. Logging & Audit

Every confirmation event (approve, deny, timeout) MUST be persisted:

```sql
-- in cmdb-schema.md `audit_log` table
(id, scan_id, skill, action, payload_json, created_at)
-- action ∈ {confirm_request, confirm_approve, confirm_deny, confirm_timeout}
```

This is the MVP's audit trail. `actor` is fixed (`local`) per [architecture.md §4](./architecture.md#4-reusable-assets-do-not-rewrite); a future multi-user mode replaces it with a real user id.

---

## 5. Forbidden Patterns

| Anti-pattern | Why |
|--------------|-----|
| Skill calls `ctx.confirm` itself, late in `run()` | Confirmation MUST happen before any side effect. The loop guarantees this only if `risk_level=critical` is set. |
| Asking via the LLM ("Are you sure? Reply yes/no") | Falls outside the structured event; WebUI cannot render it as the destructive dialog; not auditable. |
| Suppressing confirmation when running from CLI | CLI MUST also prompt (see `secbot/cli/onboard.py` confirm helper). No "headless" bypass in MVP. |
| Allowing the agent to retry a denied skill in the same turn | The Orchestrator and Expert prompts both forbid this; verified by `tests/agent/test_high_risk_retry.py`. |

---

## 6. Test Requirements

- `tests/agent/test_high_risk_gating.py`: every `critical` skill MUST be wrapped by `ctx.confirm` before subprocess starts.
- `tests/agent/test_high_risk_deny.py`: deny → `summary.user_denied=True`, no subprocess started, audit log row written.
- `tests/agent/test_confirm_timeout.py`: 120s timeout path produces `confirm_timeout`.
