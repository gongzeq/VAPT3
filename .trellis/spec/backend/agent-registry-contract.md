# Agent Registry Contract

> Defines how Expert Agents are declared, discovered, and exposed to the Orchestrator.
> Implementation lives under `secbot/agent/subagent.py` + a new `secbot/agents/` registry directory.

---

## 1. Storage Layout

```
secbot/agents/
├── asset_discovery.yaml
├── port_scan.yaml
├── vuln_scan.yaml
├── weak_password.yaml
├── pentest.yaml
└── report.yaml
```

One YAML file per expert agent. Filename (without extension) IS the agent's
registered name; the Orchestrator picks it via `create_agent(name=...)`. Per-
agent tools (one tool per yaml) are no longer exposed at the LLM tool surface
(see `orchestrator-tool-whitelist.md` and decision D2 in
`05-18-subagent-prompt-minimal-create-agent/prd.md`).

---

## 2. YAML Schema

```yaml
# secbot/agents/<name>.yaml
name: asset_discovery                # required, snake_case, == filename
display_name: 资产探测                # required, shown in WebUI plan timeline
description: |                       # required, drives Orchestrator routing
  Discover live hosts, services and basic asset
  inventory under a target CIDR/IP/domain.
  Use BEFORE port_scan or vuln_scan.

system_prompt_file: ./prompts/asset_discovery.md  # required, path relative to YAML

scoped_skills:                       # required, non-empty list
  - nmap-host-discovery
  - fscan-asset-discovery
  - cmdb-add-target

model:                               # optional, falls back to global default
  provider: openai
  name: gpt-4o-mini
  temperature: 0.1

max_iterations: 8                    # optional, default 10
emit_plan_steps: true                # optional, default true (renders in PlanTimeline)
endpoint_bound: false                # optional, default false. When true, the
                                     # agent operates on a single (endpoint_url,
                                     # endpoint_param) pair and SubagentManager
                                     # enforces endpoint-level mutual exclusion.

legacy_input_schema:                 # required (alias `input_schema` accepted
                                     # with a DeprecationWarning during the
                                     # migration window — decision D7). Kept
                                     # for diagnostics & schema docs ONLY; the
                                     # Orchestrator no longer hands per-agent
                                     # input shapes to the LLM.
  type: object
  required: [target]
  properties:
    target:
      type: string
      description: CIDR / IP / domain
    label:
      type: string
      description: Optional human label written into CMDB

output_schema:                       # required, declares the summary returned to Orchestrator
  type: object
  required: [assets]
  properties:
    assets:
      type: array
      items:
        type: object
        required: [target, kind]
        properties:
          target: {type: string}
          kind:   {type: string, enum: [cidr, ip, domain]}
          label:  {type: string}
```

### 2.1 Field Rules

| Field | Rule |
|-------|------|
| `name` | MUST equal filename stem; MUST match `^[a-z][a-z0-9_]*$`. |
| `scoped_skills` | Each entry MUST exist as a registered skill (`secbot/skills/<entry>/SKILL.md`). Loader fails fast if missing. |
| `scoped_skills` at runtime | Scoped skills are the agent's default/preferred tools, not an exclusive allow-list. `SubagentManager._run_subagent()` registers every executable SkillTool that is not disabled, then orders/presents `scoped_skills` first in the prompt. |
| `system_prompt_file` | MUST exist; loader reads it and **appends** it to the subagent system prompt (after the safety scaffold). This gives the subagent both the hard-rules skeleton and the per-agent role instructions. |
| `legacy_input_schema` / `output_schema` | MUST be valid JSON Schema 2020-12. `legacy_input_schema` is informational only — the Orchestrator no longer validates `args` against it (the `create_agent` tool has its own fixed schema). `output_schema` MAY still drive post-run summary validation. The legacy alias `input_schema` is accepted with a DeprecationWarning. |
| `endpoint_bound` | Optional bool, default `false`. When `true`, `create_agent` MUST receive both `endpoint_url` and `endpoint_param`; `SubagentManager` rejects a second concurrent spawn against the same normalised `(endpoint_url, endpoint_param)` key. |
| `emit_plan_steps` | When `false`, the agent's individual steps collapse in the WebUI; only the final summary renders. |

### 2.2 Availability Semantics

When `load_agent_registry(..., skills_root=...)` is used, the registry derives:

- `required_binaries`: unique `external_binary` values declared by the agent's `scoped_skills`.
- `missing_binaries`: the subset not resolved by config override or `PATH`.
- `available`: `true` when the agent has no binary requirements, or at least one binary-backed scoped skill is runnable.
- `degraded`: `true` when `available` is `true` but `missing_binaries` is non-empty.

`create_agent` / `create_worker` MUST reject only fully unavailable agents
(all binary-backed scoped skills missing). Partially missing binaries are a
degraded mode: the subagent still starts, all executable skill tools remain
registered, and an unavailable individual skill reports `binary_missing` when
invoked.

---

## 3. Registration Flow

```
secbot startup
  └── load_agent_registry(secbot/agents/)
        ├── for each *.yaml:
        │     ├── parse + validate against this schema
        │     ├── resolve scoped_skills against skill registry
        │     ├── load system_prompt_file
        │     └── expose the agent through the single create_agent(name=...) surface
        └── on ANY failure: abort startup with structured error
```

- Registration is **at startup only**. No hot reload in MVP.
- Adding a new expert agent requires zero change to Orchestrator code (AC4 in PRD).

---

## 4. What the Orchestrator Sees

The Orchestrator does NOT receive one tool per expert agent. Instead, it sees a
single `create_agent(name, task, target, endpoint_url?, endpoint_param?)` tool
plus the locked agent table rendered into its system prompt by
`render_orchestrator_prompt()`. Each row of that table lists:

- the agent `name` (the value to pass as `create_agent(name=...)`),
- whether the agent is `endpoint-bound`,
- a one-line purpose,
- the agent's scoped skills.

The Orchestrator never sees individual skill names as standalone tools.
Skills are an **implementation detail** of the expert agent.

---

## 5. Forbidden Patterns

| Anti-pattern | Why |
|--------------|-----|
| Defining an agent in Python instead of YAML | Breaks AC4 (zero-code addition). |
| Sharing a skill across two expert agents | Causes Orchestrator routing ambiguity; if a capability is truly shared, factor it into a separate expert agent. |
| Putting `risk_level` on the agent YAML | `risk_level` is a **skill** attribute (see [skill-contract.md](./skill-contract.md)). Agents are routing units, not safety units. |
| Calling another expert agent from inside an expert agent | Violates two-layer rule ([architecture.md §3](./architecture.md#3-boundaries-what-each-layer-must-not-do)). |

---

## 6. Test Hooks

- `tests/agent/test_agent_registry.py` MUST verify: missing skill → startup error; bad schema → startup error; valid YAML → tool surface matches snapshot.
- New expert agent PRs MUST add a YAML fixture under `tests/fixtures/agents/`.
