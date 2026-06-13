# Agent Registry Contract

> Defines how expert agents are declared, discovered, and exposed to the
> Orchestrator. Implementation lives under `secbot/agents/registry.py`,
> `secbot/agent/subagent.py`, and `secbot/agents/`.

---

## 1. Storage Layout

```text
secbot/agents/
├── asset_discovery.yaml
├── crawl_web.yaml
├── port_scan.yaml
├── vuln_detec.yaml
├── vuln_scan.yaml
├── weak_password.yaml
├── report.yaml
└── prompts/
    └── <agent>.md
```

One YAML file declares one expert agent. Filename without extension is the
registered name, and the Orchestrator selects it with
`create_agent(name=...)`. Per-agent tools are not exposed at the Orchestrator
LLM surface; see [orchestrator-tool-whitelist.md](./orchestrator-tool-whitelist.md).

---

## 2. YAML Schema

```yaml
name: asset_discovery
display_name: 资产探测
description: |
  Full routing description rendered into the Orchestrator prompt.
  This is where expert selection guidance belongs.

system_prompt_file: ./prompts/asset_discovery.md

scoped_skills:
  - qscan-host-discovery
  - fscan-asset-discovery

model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.1

max_iterations: 10
emit_plan_steps: true
endpoint_bound: false
allow_exec: false
minimal_tools: false

legacy_input_schema:
  type: object
  required: [target]
  properties:
    target:
      type: string

output_schema:
  type: object
```

### 2.1 Field Rules

| Field | Rule |
|-------|------|
| `name` | Required. MUST equal filename stem and match `^[a-z][a-z0-9_]*$`. |
| `display_name` | Required non-empty user-facing label. |
| `description` | Required non-empty routing knowledge. Rendered in full under `# Available expert agents`; this is the Orchestrator's source of expert-selection guidance. |
| `system_prompt_file` | Required and MUST exist. Loader reads it into `ExpertAgentSpec.system_prompt` for API/editing/diagnostics compatibility, but live subagent LLM prompts MUST NOT append it automatically. Execution guidance from this file is effective only when the Orchestrator chooses to include the relevant instructions in `create_agent.task`. |
| `scoped_skills` | Required non-empty list. Each entry MUST exist as a registered skill when the loader is called with `skill_names`; a skill MUST NOT be claimed by multiple expert agents. |
| `legacy_input_schema` / `output_schema` | Required valid JSON Schema 2020-12. `legacy_input_schema` is informational only; `create_agent` has its own fixed schema and no longer exposes per-agent input shapes to the LLM. The old alias `input_schema` is accepted with a `DeprecationWarning` during migration. |
| `max_iterations` | Optional positive int, default `10`. Effective runtime is capped by the parent loop's global limit. |
| `emit_plan_steps` | Optional bool, default `true`. When `false`, the agent's individual steps collapse in the WebUI. |
| `endpoint_bound` | Optional bool, default `false`. When `true`, `create_agent` MUST receive both `endpoint_url` and `endpoint_param`; `SubagentManager` rejects concurrent runs against the same normalized endpoint key. |
| `allow_exec` | Optional bool, default `false`. Even if global `ExecToolConfig.enable` is true, a subagent receives `exec` only when its resolved expert spec has `allow_exec: true`. |
| `minimal_tools` | Optional bool, default `false`. When `true`, the subagent receives only its scoped SkillTools, with no file, curl, blackboard, ask_user, exec, asset feed, or vulnerability-report tools. |

---

## 3. Registration Flow

```text
secbot startup
  └── load_agent_registry(secbot/agents/)
        ├── parse every *.yaml
        ├── validate required fields and JSON Schemas
        ├── resolve scoped_skills when a skill set is provided
        ├── reject skills claimed by more than one expert
        ├── read system_prompt_file for diagnostics/API compatibility
        ├── compute required_binaries / missing_binaries when skills_root is provided
        └── expose an AgentRegistry for prompt rendering and create_agent validation
```

Registration is startup-only in the live runtime. Loader failure aborts registry
construction; it must not silently register a partial set.

Adding a new expert agent should not require Orchestrator prompt code changes.
The new YAML description is rendered automatically.

---

## 4. What the Orchestrator Sees

The Orchestrator sees one tool for expert launch:

```text
create_agent(name, task, target, endpoint_url?, endpoint_param?)
```

It also sees a rendered `# Available expert agents` section from
`render_orchestrator_prompt()`. Each agent entry lists:

- the agent `name` to pass as `create_agent(name=...)`,
- the display name,
- whether it is endpoint-bound,
- its scoped skills,
- the full YAML `description`.

The Orchestrator never sees individual expert skills as standalone tools.
Skills are implementation details of the expert agent.

---

## 5. Live Subagent Prompt Boundary

At runtime, `SubagentManager` starts expert subagents with:

```python
[
    {"role": "system", "content": "<shared slim scaffold>"},
    {"role": "user", "content": create_agent.task},
]
```

The system prompt comes from `secbot/templates/agent/subagent_system.md`. It is
a shared safety/tool-use scaffold only. The runtime MUST NOT append:

- `spec.system_prompt`,
- a skill summary,
- a blackboard snapshot,
- asset-feed snapshots,
- parent conversation history.

The Orchestrator owns task composition. If an expert needs detailed execution
steps, parameter constraints, or selected findings, those instructions must be
written into `create_agent.task`.

---

## 6. Forbidden Patterns

| Anti-pattern | Why |
|--------------|-----|
| Defining an expert agent in Python instead of YAML | Breaks registry-driven addition. |
| Sharing one skill across multiple expert agents | Creates routing ambiguity. |
| Putting `risk_level` on the agent YAML | Risk is a skill attribute; agents are routing units. |
| Calling another expert agent from inside an expert | Violates the two-layer architecture. |
| Appending `system_prompt_file` content to the live subagent system prompt | Hides instructions outside the Orchestrator-authored `task` boundary. |
| Relying on `target` metadata to teach the subagent scope | `target` is routing/audit metadata; restate needed scope inside `task`. |

---

## 7. Test Hooks

- `tests/agent/test_agent_registry.py` MUST verify missing skill, bad schema,
  valid YAML, availability, endpoint-bound, allow-exec, and shared-skill
  behavior.
- `tests/agent/test_orchestrator_prompt.py` MUST verify full YAML descriptions
  are rendered for routing.
- Subagent tests MUST verify scoped-skill filtering, `create_agent` absence,
  `minimal_tools` behavior, exact user-message pass-through, and absence of
  `spec.system_prompt` from the system prompt.
- New expert agent PRs MUST add or update YAML fixtures/tests when schema
  behavior changes.
