# 重构 Orchestrator 提示词：动态规划 + 子代理知识下沉

## Goal

Refactor the Orchestrator prompt contract so the top-level agent plans dynamically from the current state and agent registry instead of following a fixed scan pipeline, while expert-specific routing/execution knowledge lives in agent YAML descriptions and Orchestrator-authored `create_agent.task` prompts rather than implicit subagent system prompt injection.

## What I already know

- The repo already exposes a single `create_agent` entry point and renders a `# Planning` section in `secbot/agents/orchestrator.py`.
- `tests/agent/test_orchestrator_prompt.py` already asserts dynamic planning, no `"natural ordering"` text, full multiline agent YAML descriptions, and mandatory report guidance.
- `secbot/agents/*.yaml` descriptions already contain routing knowledge for `asset_discovery`, `port_scan`, `crawl_web`, `vuln_detec`, `vuln_scan`, and `report`.
- `secbot/templates/agent/subagent_system.md` is already a slim hard-rules scaffold.
- `SubagentManager._build_subagent_prompt()` still appends `spec.system_prompt`, and older tests/spec text still describe that implicit injection. That contradicts the prompt-minimization direction where `create_agent.task` is the expert's full instruction source.
- `.trellis/spec/backend/orchestrator-prompt.md` is stale: it still documents fixed natural ordering and a four-section skeleton without `# Planning`.
- `.trellis/spec/backend/orchestrator-tool-whitelist.md` is stale: actual tests/implementation include `read_assets`, `read_file`, and `message` in addition to `create_agent`, `read_blackboard`, `write_plan`, and `request_approval`.
- `.trellis/spec/backend/agent-registry-contract.md` is stale: it says `system_prompt_file` is appended to the subagent system prompt, which must no longer be true.

## Assumptions

- The current partially implemented `secbot/agents/orchestrator.py` direction is intentional and should be completed, not reverted.
- `system_prompt_file` remains in YAML for migration/documentation/diagnostics compatibility, but live subagent LLM prompts should not append it.
- Agent YAML descriptions are the correct home for Orchestrator routing knowledge; detailed execution steps belong in the `task` body Orchestrator passes to `create_agent`.

## Requirements

- [x] Orchestrator system prompt has five stable sections: `# Role`, `# Hard rules`, `# Planning`, `# Available expert agents`, `# Working style`.
- [x] Orchestrator prompt explicitly requires dynamic planning/replanning and must not encode a fixed `asset_discovery -> port_scan -> ...` pipeline or the phrase `natural ordering`.
- [x] Orchestrator prompt tells the model to use registry descriptions and blackboard/asset summaries to decide which expert to spawn and what to put into `create_agent.task`.
- [x] Agent YAML descriptions carry routing knowledge that used to live in global prompt text.
- [x] Subagent system prompt is only the slim hard-rules scaffold; it does not append `spec.system_prompt`, skills summaries, or automatic blackboard snapshots.
- [x] Subagent user message is exactly the Orchestrator-provided `task`.
- [x] Specs are updated to match actual behavior and tests: orchestrator prompt, tool whitelist, and agent registry contract.
- [x] Tests cover the prompt contract and the subagent prompt ownership boundary.

## Acceptance Criteria

- [x] `render_orchestrator_prompt(load_agent_registry(...))` includes `# Planning`, dynamic/OODA guidance, full agent YAML descriptions, and no `natural ordering`.
- [x] The rendered prompt still names `create_agent`, lifecycle tools, report generation, and high-risk approval.
- [x] A subagent run receives messages shaped as `[{role: system, content: slim scaffold}, {role: user, content: task}]`; `spec.system_prompt` content is absent from the system prompt.
- [x] Existing scoped-skill filtering, ExecTool deny-by-default, minimal-tools report behavior, endpoint mutex, and `create_agent` validation tests remain green.
- [x] Focused tests for orchestrator prompt, registry/tool whitelist, subagent tools/isolation, and search/tool-surface behavior pass.
- [x] `ruff`, `mypy`, and a relevant pytest slice pass, or any non-pass is documented with the exact blocker.

## Definition of Done

- Code and tests updated.
- Relevant Trellis specs updated.
- `implement.jsonl` and `check.jsonl` point at the specs needed by implementation/check agents.
- Task is started/completed through Trellis workflow as far as the platform permits.

## Out of Scope

- Adding new expert agents or skills.
- Changing `create_agent` schema, endpoint mutex behavior, scan lifecycle, report generation internals, or high-risk approval semantics.
- Removing the YAML `system_prompt_file` field entirely.
- Building a new planning engine outside prompt/spec/test changes.

## Technical Notes

- Main files: `secbot/agents/orchestrator.py`, `secbot/agent/subagent.py`, `secbot/templates/agent/subagent_system.md`, `secbot/agents/*.yaml`.
- Spec files: `.trellis/spec/backend/orchestrator-prompt.md`, `.trellis/spec/backend/orchestrator-tool-whitelist.md`, `.trellis/spec/backend/agent-registry-contract.md`.
- Tests: `tests/agent/test_orchestrator_prompt.py`, `tests/agent/tools/test_subagent_tools.py`, `tests/tools/test_search_tools.py`, `tests/agent/test_subagent_isolation.py`, `tests/agent/test_agent_registry.py`.

## Verification

- `uv run pytest tests/agent/test_orchestrator_prompt.py tests/agent/test_agent_registry.py tests/agent/test_subagent_isolation.py tests/agent/tools/test_subagent_tools.py tests/tools/test_search_tools.py` -> 90 passed, 1 pre-existing RuntimeWarning in `test_spawn_tool_rejects_unknown_agent`.
- `uv run ruff check secbot/agent/subagent.py secbot/agents/orchestrator.py tests/agent/test_orchestrator_prompt.py tests/agent/tools/test_subagent_tools.py tests/tools/test_search_tools.py tests/agent/test_subagent_isolation.py tests/agent/test_agent_registry.py` -> passed.
- `git diff --check` -> passed.
- `uv run python -m mypy secbot/agent/subagent.py secbot/agents/orchestrator.py secbot/agents/registry.py` -> blocked because the project venv has no `mypy` module.
- `uv run mypy secbot/agent/subagent.py secbot/agents/orchestrator.py secbot/agents/registry.py` -> blocked because the global mypy entrypoint loads an incompatible architecture compiled extension.
