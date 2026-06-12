# Skill Contract

> Defines the package layout, metadata, and runtime contract for every secbot skill.
> Reuses the existing `nanobot/skills/` convention (renamed to `secbot/skills/`).

---

## 1. Directory Layout

```
secbot/skills/<skill-name>/
├── SKILL.md           # required, metadata + prose docs
├── handler.py         # required, exposes `async def run(args, ctx) -> SkillResult`
├── scripts/           # optional, helper binaries / templates
├── input.schema.json  # required, JSON Schema for args
└── output.schema.json # required, JSON Schema for summary_json
```

**Naming**: `<tool>-<function>` kebab-case, e.g. `nmap-host-discovery`, `fscan-weak-password`. The directory name IS the skill name visible to expert agents.

---

## 2. SKILL.md Front-matter Schema

```yaml
---
name: nmap-port-scan                 # required, == directory name
display_name: Nmap port scan
version: 1.0.0
risk_level: medium                   # required, one of: low | medium | high | critical
                                     #   See high-risk-confirmation.md for gating rules.
category: port_scan                  # required, free-form domain tag
external_binary: nmap                # optional, declares hard dependency
binary_min_version: "7.80"           # optional, checked at startup if external_binary set
network_egress: required             # required, one of: required | optional | none
expected_runtime_sec: 60             # required, used for UI progress + timeout
summary_size_hint: small             # required, one of: small | medium | large
                                     #   Drives context-trimming policy.
---
```

Anything below the front-matter is human prose: usage examples, args explanation, known caveats. The agent loop uses the prose as the tool's `description`.

### 2.1 Field rules

| Field | Rule |
|-------|------|
| `risk_level` | `critical` skills MUST be gated by `agent/tools/ask.py` confirmation BEFORE execution. See [high-risk-confirmation.md](./high-risk-confirmation.md). |
| `external_binary` | Skill startup MUST verify the binary is on `PATH`; missing binary → register skill as **disabled**, not crash. |
| `network_egress: none` | Loader MUST configure `secbot/security/network.py` to block external sockets for this skill. |
| `summary_size_hint` | Used by the trim policy in [context-trimming.md](./context-trimming.md). |

---

## 3. Runtime Contract

```python
# secbot/skills/<name>/handler.py

from secbot.skills.types import SkillContext, SkillResult

async def run(args: dict, ctx: SkillContext) -> SkillResult:
    """
    Args validated against input.schema.json BEFORE this is called.
    SkillResult.summary validated against output.schema.json AFTER this returns.
    """
    ...
    return SkillResult(
        summary={"hosts_up": [...], "elapsed_sec": 12},   # MUST satisfy output.schema.json
        raw_log_path="/abs/path/to/raw.log",              # absolute path under ~/.secbot/scans/
        findings=[                                        # optional, bridged by host runtime
            {"severity": "high", "title": "...", "payload": {...}},
        ],
        cmdb_writes=[                                     # optional, declared mutations
            {"table": "assets", "op": "insert", "data": {...}},
        ],
    )
```

### 3.1 SkillContext (provided by the loop)

| Attribute | Purpose |
|-----------|---------|
| `ctx.scan_id` | UUID for the current scan; use for `raw_log_path` directory. |
| `ctx.confirm(prompt)` | Async user-confirmation gate; required for `risk_level=critical`. |
| `ctx.write_progress(pct, message)` | Optional streaming progress (rendered as shadcn `<Progress>`). |
| `ctx.cancel_token` | `asyncio.Event`; skill MUST poll and abort within 1s of being set. |

### 3.2 Scenario: Host-Owned Skill Finding Bridge

#### 1. Scope / Trigger

- Trigger: a Skill returns `SkillResult.findings`, including during an agent wind-down after `max_iterations` or `context_exhausted`.

#### 2. Signatures

- Input: `SkillResult.findings: list[dict]`
- Runtime context: `bind_skill_context(asset_feed=..., vulnerability_store=..., asset_auto_management_enabled=...)`
- Outputs: `VulnerabilityStore.report(...)`, `AssetFeed.append(kind='vuln'|'vulnerability_candidate')`, and optional CMDB `vulnerability_candidate` upsert.

#### 3. Contracts

- Finding persistence is host-owned; Expert Agents do not need to restate every scanner hit in their final text.
- Confirmed, verified, or high-confidence positive findings become confirmed vulnerabilities in `VulnerabilityStore` and `AssetFeed(kind='vuln')`.
- Passive, unverified, or low-confidence findings become `AssetFeed(kind='vulnerability_candidate')`.
- CMDB `vulnerability_candidate` rows are written only when Asset Auto-Management is enabled.
- Legacy `cmdb_writes` remain gated by Asset Auto-Management, but this gate MUST NOT suppress the in-memory finding bridge.
- Built-in active vulnerability Skills that also emit `cmdb_writes` for the `vulnerabilities` table MUST mark corresponding `findings` with `status='confirmed'` and a `verification` method.

#### 4. Validation & Error Matrix

| Finding input | Host result |
|---------------|-------------|
| `verified=true` or `confirmed=true` | confirmed vulnerability + `vuln` feed row |
| `status='verified'|'confirmed'|'true_positive'` | confirmed vulnerability + `vuln` feed row |
| `confidence='high'` and `result='positive'|'vulnerable'|'confirmed'` | confirmed vulnerability + `vuln` feed row |
| no verification signal | `vulnerability_candidate` feed row only |
| candidate + Asset Auto-Management enabled | candidate feed row + CMDB candidate upsert |
| malformed finding item | skipped, skill result still returned |
| bridge persistence failure | warning log, skill result still returned |

#### 5. Good/Base/Bad Cases

- Good: a SQL probe with high confidence and positive result reaches the report data source even if the agent is interrupted before final narration.
- Base: a passive template match is visible as a candidate but not counted as a confirmed report vulnerability.
- Bad: gating all findings behind `cmdb_writes`, or promoting every scanner hit to a confirmed vulnerability.

#### 6. Tests Required

- Confirmed `SkillResult.findings` bridge to `VulnerabilityStore` and `AssetFeed(kind='vuln')` when Asset Auto-Management is disabled.
- Unverified findings bridge to `AssetFeed(kind='vulnerability_candidate')` and do not enter `VulnerabilityStore`.
- Candidate CMDB persistence is covered when Asset Auto-Management is enabled.

#### 7. Wrong vs Correct

Wrong:

```python
if not asset_auto_management_enabled:
    return skill_result
```

Correct:

```python
await bridge_skill_findings(skill_result)
if asset_auto_management_enabled:
    await apply_cmdb_writes(skill_result.cmdb_writes)
```

---

## 4. Hard Rules

1. **No `print()`**. Use `ctx.write_progress` for UX, structured logging for diagnostics. (See [logging-guidelines.md](./logging-guidelines.md).)
2. **No bare subprocess**. All external command execution goes through `secbot/skills/_shared/sandbox.py`. (See [tool-invocation-safety.md](./tool-invocation-safety.md).)
3. **No raw stdout in `summary`**. The summary is for the LLM; raw bytes go to `raw_log_path`.
4. **Idempotent reruns**. Re-invoking a skill with the same args + scan_id MUST be safe; no double CMDB inserts (use `INSERT OR IGNORE` or upsert).
5. **No skill-to-skill calls**. If logic needs to be shared, factor it into `secbot/skills/_shared/`.

---

## 5. Error Handling

| Failure | Skill MUST |
|---------|------------|
| Args invalid | Never reach `run()`; loader rejects before call. |
| Subprocess non-zero exit | Return `SkillResult` with `summary={"error": "..."}` AND set `findings=[]`. Do NOT raise — the LLM needs the structured failure to plan next step. |
| External binary missing at runtime | Raise `SkillBinaryMissing`; loop converts to tool error. |
| User cancels via `ctx.cancel_token` | Cleanly terminate subprocess; return `summary={"cancelled": true}`. |
| User denies high-risk confirmation | Return `summary={"user_denied": true}`; surface via WebUI per [frontend/component-patterns.md §3](../frontend/component-patterns.md#3-destructive-confirmation-dialog). |

---

## 6. Test Requirements

For each skill PR:

- `tests/skills/<name>/test_handler.py` covers happy path + at least one failure path.
- `input.schema.json` and `output.schema.json` MUST validate against the test fixtures.
- A subprocess-based skill MUST mock the binary call (no real network in unit tests).
- High-risk skills MUST have a test verifying `ctx.confirm` is called BEFORE the subprocess.
