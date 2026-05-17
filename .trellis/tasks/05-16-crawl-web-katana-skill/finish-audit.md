# Finish Audit: crawl_web Katana Skill

Date: 2026-05-17

## Objective

Continue and finish `.trellis/tasks/05-16-crawl-web-katana-skill`: add a `crawl_web` expert agent and a Katana-backed `katana-crawl-web` skill that crawls authorized HTTP/HTTPS targets, deduplicates and filters discovered URLs, classifies vulnerability hypotheses, and returns structured candidates for orchestrator-driven downstream scanning.

## Completion Evidence

- `secbot/agents/crawl_web.yaml` defines the new `crawl_web` expert agent scoped to `katana-crawl-web`.
- `secbot/agents/prompts/crawl_web.md` instructs the agent to call Katana, return candidates, and never call `vuln_scan` directly.
- `secbot/skills/katana-crawl-web/` contains `SKILL.md`, `handler.py`, `input.schema.json`, and `output.schema.json`.
- `secbot/skills/_shared/sandbox.py` whitelists `katana` and continues to enforce sandboxed argv execution.
- `.trellis/spec/backend/tool-invocation-safety.md` includes an executable Katana crawl skill scenario with signatures, contracts, validation/error matrix, tests, and wrong/correct examples.
- `.trellis/spec/backend/orchestrator-prompt.md` and `secbot/agents/orchestrator.py` include `crawl_web` before `vuln_scan` in the default stage order.
- Tests added/updated:
  - `tests/agent/test_agent_registry.py`
  - `tests/agent/test_orchestrator_prompt.py`
  - `tests/agent/tools/test_subagent_tools.py`
  - `tests/security/test_sandbox.py`
  - `tests/skills/test_metadata.py`
  - `tests/skills/test_katana_crawl_web_handler.py`

## Verification Performed

Used Python 3.11 because the default Anaconda Python is too old for this repo's `tomllib` usage.

- `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m ruff check secbot/agents/orchestrator.py secbot/skills/_shared/sandbox.py secbot/skills/katana-crawl-web/handler.py tests/agent/test_agent_registry.py tests/agent/test_orchestrator_prompt.py tests/agent/tools/test_subagent_tools.py tests/security/test_sandbox.py tests/skills/test_metadata.py tests/skills/test_katana_crawl_web_handler.py`
  - Result: passed.
- `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m py_compile secbot/agents/orchestrator.py secbot/agents/registry.py secbot/agent/tools/spawn.py secbot/agent/subagent.py secbot/skills/_shared/sandbox.py secbot/skills/katana-crawl-web/handler.py tests/skills/test_katana_crawl_web_handler.py`
  - Result: passed.
- `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m pytest tests/agent/test_agent_registry.py tests/agent/test_orchestrator_prompt.py tests/agent/tools/test_subagent_tools.py tests/security/test_sandbox.py tests/skills/test_metadata.py tests/skills/test_katana_crawl_web_handler.py`
  - Result: `83 passed, 1 warning`.

## Commit Gate

Trellis Phase 3.4 remains blocked pending user confirmation because unrelated dirty files are present in the worktree.

Proposed commit:

`feat(agent): add crawl_web katana crawler`

Files to include:

- `.trellis/spec/backend/architecture.md`
- `.trellis/spec/backend/orchestrator-prompt.md`
- `.trellis/spec/backend/skill-contract.md`
- `.trellis/spec/backend/tool-invocation-safety.md`
- `secbot/agents/orchestrator.py`
- `secbot/agents/crawl_web.yaml`
- `secbot/agents/prompts/crawl_web.md`
- `secbot/skills/_shared/sandbox.py`
- `secbot/skills/katana-crawl-web/SKILL.md`
- `secbot/skills/katana-crawl-web/handler.py`
- `secbot/skills/katana-crawl-web/input.schema.json`
- `secbot/skills/katana-crawl-web/output.schema.json`
- `tests/agent/test_agent_registry.py`
- `tests/agent/test_orchestrator_prompt.py`
- `tests/agent/tools/test_subagent_tools.py`
- `tests/security/test_sandbox.py`
- `tests/skills/test_metadata.py`
- `tests/skills/test_katana_crawl_web_handler.py`

Unrelated dirty files must not be included without explicit user direction:

- `ffuf_claude_skill-main/ffuf-skill/*` deletions
- `secbot/agents/prompts/asset_discovery.md`
- `secbot/agents/prompts/port_scan.md`
- `secbot/agents/prompts/vuln_detec.md`
- `secbot/agents/prompts/vuln_scan.md`
- `secbot/agents/prompts/weak_password.md`
- `secbot/agents/vuln_detec.yaml`
- `secbot/agents/vuln_scan.yaml`
- `secbot/resource/fuzzDicts`
- `secbot/skills/ctf-web/`
- `secbot/skills/ffuf-skill/`
- `.trellis/tasks/05-17-bb-realtime-notify/`

## Current Blocker

Awaiting one explicit user choice:

- `ok` / `行`: stage and commit only the crawl_web/Katana files listed above.
- `manual` / `我自己来`: skip commit execution and leave it for the user.

