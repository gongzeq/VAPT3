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

One YAML file per expert agent. Filename (without extension) IS the agent's tool name as seen by the Orchestrator.

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

input_schema:                        # required, JSON Schema for `args` from Orchestrator
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
| `system_prompt_file` | MUST exist; loader reads and embeds at registration time. |
| `input_schema` / `output_schema` | MUST be valid JSON Schema 2020-12. The Orchestrator validates `args` BEFORE calling the agent; the loop validates `summary_json` AFTER. Validation failure → tool error returned to caller, not raised. |
| `emit_plan_steps` | When `false`, the agent's individual steps collapse in the WebUI; only the final summary renders. |

---

## 3. Registration Flow

```
secbot startup
  └── load_agent_registry(secbot/agents/)
        ├── for each *.yaml:
        │     ├── parse + validate against this schema
        │     ├── resolve scoped_skills against skill registry
        │     ├── load system_prompt_file
        │     └── register tool in OrchestratorTools as {name, description, input_schema}
        └── on ANY failure: abort startup with structured error
```

- Registration is **at startup only**. No hot reload in MVP.
- Adding a new expert agent requires zero change to Orchestrator code (AC4 in PRD).

---

## 4. What the Orchestrator Sees

For the LLM, each expert agent looks like a single tool:

```json
{
  "type": "function",
  "function": {
    "name": "asset_discovery",
    "description": "Discover live hosts, services and basic asset inventory ...",
    "parameters": { /* input_schema */ }
  }
}
```

The Orchestrator never sees individual skill names. Skills are an **implementation detail** of the expert agent.

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
