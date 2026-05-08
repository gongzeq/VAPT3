# Component Patterns

> Binding rules for chat / tool-call / destructive UI surfaces in `webui/`.
> Origin: research/cybersec-ui-patterns.md §1 + §2.

---

## 1. MessageBubble Triplet

The assistant chat bubble decomposes into exactly **three** sub-components. New skill output that does not fit one of these MUST extend an existing slot, not introduce a fourth top-level type.

| Sub-component | Purpose | Renders when |
|---------------|---------|--------------|
| `<ToolCallCard>` | Collapsible card for a single `tool_call` (skill invocation, args, status) | Message contains a `tool_call` part |
| `<ScanResultTable>` | Structured result table (ports, vulns, hosts) keyed by skill name | `tool_result.summary_json` present |
| `<PlanTimeline>` | Vertical step list "plan → invoke → observe → iterate" | Orchestrator emits a `plan` part |

### 1.1 Registration contract

- Skill-specific renderers register through `assistant-ui` `runtime.toolUI[<skill-name>]`. **Forbidden**: switch/case branching inside one mega-component.
- Each `SKILL.md` declares the renderer it expects via frontmatter:

  ```yaml
  display_component: scan-result-table   # or tool-call-card / plan-timeline
  ```

- If a skill has no declaration, the runtime falls back to a generic `<ToolCallCard>` (collapsed JSON).

### 1.2 Streaming contract

Long-running skills (any `nmap` / `nuclei` / fuzzing tool) MUST conform to the following stream shape so `<ToolCallCard>` can render progress without re-implementation:

1. While running → yield `progress` events (`{ percent?: number; step?: string }`).
2. On completion → yield `summary_json` (structured, drives `<ScanResultTable>`) **and** `raw_log_path` (HTTP URL).
3. UI shows summary inline; raw log is opened in a new tab via `[查看原始日志 ↗]`. **Do not** inline raw log in the bubble.

---

## 2. Tool-Call Folding

- Default state: **collapsed**, showing only `skill_name`, `target`, status badge.
- Expanded state reveals: arguments JSON (syntax-highlighted), live progress, structured result.
- The card width MUST stay within the message column; wide tables (`ScanResultTable`) get an internal horizontal scroll, not a viewport overflow.
- Status badge color: `running` → `--primary`, `success` → green-500, `failure` → `--sev-critical`, `denied` → `--sev-info`.

---

## 3. Destructive Confirmation Dialog

Every action that (a) writes to a remote target, (b) launches an intrusive scan, (c) deletes server-side data MUST funnel through shadcn `<AlertDialog destructive>`. No bespoke modal.

### 3.1 Required structure (top → bottom)

1. **Header**: orange-red ⚠ icon + title `"确认执行高危操作"`.
2. **Risk summary card** with these fields:
   - `skill_name`
   - `target` (host / URL / scope)
   - `expected_impact` (one short sentence)
   - `external_network` (boolean badge)
3. **Action row** (left-aligned cancel, right-aligned confirm):
   - Cancel: secondary outline button.
   - Confirm: `destructive` variant (uses `--destructive` = `--sev-critical`); MUST require **1 second hover** before becoming fully opaque (anti-misclick).

### 3.2 Denial feedback contract

When the user cancels, the runtime MUST inject a synthetic `tool_result` back to the LLM:

```json
{ "status": "user_denied", "reason": "<optional user note>" }
```

This keeps the orchestrator from re-issuing the same tool_call without acknowledgement.

---

## 4. Layout Patterns (informational; no rule)

Inherited from research §1 as recommended baselines. They are **not** binding constraints—deviating only requires a comment, not a spec PR.

- Asset views: tree (collapsible IP/Service) on the left, detail panel on the right (Bishop Fox Cosmos style).
- Vulnerability list: facet filters on top, table-driven body (DefectDojo style).
- Operator activity: chronological feed with left-aligned avatars (Faraday style).
- Reports: in-page Markdown editor with placeholder tokens (`<<screenshot>>`, `<<evidence>>`); export = template fill (Dradis style), not PDF preview.

---

## 5. Forbidden

- ❌ Custom modals for destructive flows (use `<AlertDialog destructive>`).
- ❌ Branching renderer selection inside a single component (use `toolUI` registry).
- ❌ Embedding raw scan logs inline in `<ToolCallCard>` (link out instead).
- ❌ Adding a fourth top-level chat sub-component without amending §1.
