# Orchestrator System Prompt

> Defines the locked system prompt template for the top-layer Orchestrator and
> the dynamic routing strategy it MUST follow.
> Implementation: `secbot/agents/orchestrator.py`, rendered by
> `ContextBuilder.build_system_prompt(..., is_orchestrator=True)`.

---

## 1. Prompt Skeleton

The Orchestrator system prompt is composed of **five** locked sections, in
order. Inserting, deleting, or reordering sections requires an ADR plus focused
prompt-contract tests.

```markdown
# Role
You are secbot...

# Hard rules
- Tool surface declaration.
- Strict delegation through `create_agent`.
- Restricted `.secbot/` file access.
- Subagent lifecycle completion gate.
- High-risk approval guardrail.
- Mandatory report generation for scanning tasks unless the user opts out.

# Planning
- Dynamic OODA planning/replanning.
- Registry-driven expert selection.
- Blackboard/asset-summary driven task composition.
- Redundancy avoidance.

# Available expert agents
### `<agent_name>`(...)
- Endpoint-bound: ...
- Skills: ...

<full YAML description>

# Working style
- Action-cycle decisions after every tool result.
- Asset/file ingestion rules.
- Knowledge propagation.
- Final report surfacing.
- User-language guidance.
```

### 1.1 Field Rules

| Section | Rule |
|---------|------|
| `# Role` | Names secbot as a privileged security operations orchestrator. It must say the Orchestrator delegates operational work and does not run scans directly. |
| `# Hard rules` | Lists the live Orchestrator tools and non-negotiable safety/completion/reporting rules. It MUST NOT encode a fixed scan pipeline. |
| `# Planning` | Requires dynamic planning and replanning from current user intent, registry descriptions, blackboard state, asset summaries, and subagent lifecycle state. |
| `# Available expert agents` | Auto-generated from [agent-registry-contract.md](./agent-registry-contract.md). It renders each expert's full YAML `description`, endpoint-bound flag, and scoped skills. Never hand-edit generated entries. |
| `# Working style` | Free prose, but it must preserve the action-cycle, asset/file ingestion, final report, and user-language guidance. |

The prompt text MUST be byte-stable for the same registry contents. Do not add
wall-clock time, random ordering, session state, or user content to the system
prompt.

---

## 2. Dynamic Planning Strategy

The Orchestrator runs the standard ReAct loop in `agent/loop.py`, but its
routing must be state-driven rather than a fixed stage list.

### 2.1 Observe

Before spawning or respawning experts, inspect the available state that matters:

- the user's current request and explicit scope/constraints,
- expert descriptions under `# Available expert agents`,
- subagent lifecycle via `check_subagents` / `wait_subagent`,
- relevant blackboard entries via `read_blackboard`,
- structured asset deltas via `read_assets` after an expert has produced work,
- persisted `.secbot/` artifacts via `read_file` only when a subagent announces
  `[tool output persisted]`.

### 2.2 Orient

Use the registry descriptions as the routing source of truth. Examples:

- `asset_discovery` is useful for CIDR/subnet/ambiguous asset inventory.
- `port_scan` is useful when hosts are known but service ports are not.
- `crawl_web` is useful for authorized HTTP/HTTPS URL exploration.
- `vuln_detec` is for suspicious HTTP/HTTPS endpoints and must not receive
  non-HTTP services.
- `vuln_scan` handles template/service vulnerability scans and consumes
  targeted hypotheses when available.
- `weak_password` is endpoint-bound and high-risk.
- `report` generates final deliverables or detection-data summaries.

These are examples of description-driven routing, not a required sequence. Skip
work that the user already supplied or that the blackboard/asset feed already
proves.

### 2.3 Decide

Before dispatching tools, write a concise 1-3 step plan with `write_plan`.
After each tool result, explicitly choose one state:

- Continue
- Replan
- Request Approval
- Answer

If the current evidence changes the route, write the revised plan before the
next dispatch.

### 2.4 Act

Spawn experts only through:

```text
create_agent(name, task, target, endpoint_url?, endpoint_param?)
```

The `task` argument is the Orchestrator-authored concrete work request. Runtime
prepends the selected expert's project-authored execution contract from
`spec.system_prompt` to the initial user message, but `task` must still contain
the goal, relevant scope, summarized findings or blackboard excerpts,
constraints, and expected output. `target`, `endpoint_url`, and
`endpoint_param` are routing and audit metadata; they are not automatically
injected into the LLM prompt.

---

## 3. Subagent Boundary

Subagents receive exactly one system message and one user message at start:

```python
[
    {"role": "system", "content": "<slim subagent scaffold>"},
    {
        "role": "user",
        "content": (
            "<expert execution contract from spec.system_prompt>\n\n"
            "<Orchestrator-authored create_agent.task>"
        ),
    },
]
```

The subagent system message is only the shared scaffold from
`secbot/templates/agent/subagent_system.md`. The runtime MUST NOT append
`spec.system_prompt`, skill summaries, automatic blackboard snapshots, asset
snapshots, or parent conversation history to that system message.

The user message carries two parts: the trusted project-authored expert
execution contract (`spec.system_prompt`) and the Orchestrator-authored concrete
task. Expert routing knowledge belongs in agent YAML descriptions; expert
procedure/output/write-channel rules belong in the execution contract; selected
runtime findings and scope belong in `create_agent.task`.

---

## 4. Tool Surface

The live Orchestrator tools are documented in
[orchestrator-tool-whitelist.md](./orchestrator-tool-whitelist.md). The prompt
must name the coordination tools it expects to use:

- `create_agent`
- `check_subagents`
- `wait_subagent`
- `read_blackboard`
- `read_assets`
- `read_file`
- `write_plan`
- `request_approval`
- `message`

The Orchestrator MUST NOT call security skills directly.

---

## 5. Error, Approval, and Completion Rules

| Tool result | Orchestrator action |
|-------------|---------------------|
| Subagent `error` | Analyze and adjust parameters/context before retrying. Never retry the exact same action more than twice. |
| Subagent `incomplete` / budget exhaustion | Treat as partial work. Read the summary, replan, and decide whether to redispatch with narrower scope. |
| `wait_subagent` timeout | Ask the user to wait, skip, or abort; do not infer completion from asset polling. |
| User denies approval | Treat as a deliberate stop for that high-risk path and choose an alternative or answer with partial results. |
| No new assets | Stop reading assets and use lifecycle tools or replan. |

For scanning tasks, the Orchestrator MUST invoke the `report` expert before
concluding unless the user explicitly opts out. When the `report` expert returns
a `report_path`, surface it immediately and summarize important findings.

---

## 6. Forbidden Patterns

| Anti-pattern | Why |
|--------------|-----|
| Encoding a fixed scan sequence in the system prompt | The correct route depends on the current user request, known assets, registry descriptions, and subagent outputs. |
| Asking the LLM to compose nmap/fscan/nuclei/hydra command lines | Bypasses typed SkillTool schemas and sandboxing. |
| Hard-coding expert routing logic outside YAML descriptions and tests | Breaks registry-driven extensibility. |
| Injecting per-agent prompt files into subagent system messages | Breaks the shared slim-scaffold boundary and can hide expert instructions from review. |
| Using `read_assets` as a wait signal | Asset deltas are data, not lifecycle state. Use `check_subagents` or `wait_subagent`. |
| Adding a `# Persona` section | Out of scope; no role-play behavior wanted. |

---

## 7. Test Hooks

- `tests/agent/test_orchestrator_prompt.py` MUST assert the five sections,
  dynamic/OODA planning guidance, full multiline YAML descriptions, mandatory
  report guidance, lifecycle tools, and absence of fixed-order wording.
- Tool-surface tests MUST assert the exact Orchestrator whitelist from
  [orchestrator-tool-whitelist.md](./orchestrator-tool-whitelist.md).
- Subagent tests MUST assert initial messages are the slim scaffold system
  message plus one user message containing the expert execution contract and
  Orchestrator task, with no appended `spec.system_prompt` in the system prompt.
