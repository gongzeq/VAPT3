# Finish Audit: crawl_web Katana Skill

Date: 2026-05-17

## Objective

Continue and finish `.trellis/tasks/05-16-crawl-web-katana-skill`: add a `crawl_web` expert agent and a Katana-backed `katana-crawl-web` skill that crawls authorized HTTP/HTTPS targets, deduplicates and filters discovered URLs, classifies vulnerability hypotheses, and returns structured candidates for orchestrator-driven downstream scanning.

## Completion Evidence

- `secbot/agents/crawl_web.yaml` defines the new `crawl_web` expert agent scoped to `katana-crawl-web`.
- `secbot/agents/prompts/crawl_web.md` instructs the agent to call Katana, return candidates, and never call `vuln_scan` directly. The file now also includes the later asset-feed convention from `05-17-bb-realtime-notify`; do not revert that newer guidance.
- `secbot/skills/katana-crawl-web/` contains `SKILL.md`, `handler.py`, `input.schema.json`, and `output.schema.json`.
- `secbot/skills/_shared/sandbox.py` whitelists `katana`, accepts configured absolute-path binary overrides by checking `Path(binary).name`, and continues to enforce sandboxed argv execution.
- `.trellis/spec/backend/tool-invocation-safety.md` includes an executable Katana crawl skill scenario with signatures, contracts, validation/error matrix, tests, and wrong/correct examples.
- `.trellis/spec/backend/orchestrator-prompt.md` and `secbot/agents/orchestrator.py` include `crawl_web` before `vuln_scan` in the default stage order.
- Relevant tests exist and were rerun:
  - `tests/agent/test_agent_registry.py` covers the shipped `crawl_web` registry entry and Katana availability metadata.
  - `tests/agent/test_orchestrator_prompt.py` covers prompt ordering that includes `crawl_web`.
  - `tests/agent/tools/test_subagent_tools.py` covers scoped skill registration for `crawl_web`.
  - `tests/security/test_sandbox.py` covers the Katana whitelist and sandbox cancellation/timeout behavior.
  - `tests/skills/test_metadata.py` covers `katana-crawl-web` metadata discovery.
  - `tests/skills/test_katana_crawl_web_handler.py` covers Katana argv construction, dedupe, static/noisy filtering, target scope filtering, parameter classification, business-path hints, JSON/XML hints, bounded output, invalid target rejection, timeout handling, and missing binary behavior.

## Prompt-to-Artifact Checklist

| Requirement / gate | Evidence inspected | Status |
|---|---|---|
| Add `crawl_web` agent YAML and prompt | `secbot/agents/crawl_web.yaml`; `secbot/agents/prompts/crawl_web.md` | Complete |
| Add Katana skill package with metadata, handler, input schema, output schema | `secbot/skills/katana-crawl-web/{SKILL.md,handler.py,input.schema.json,output.schema.json}` | Complete |
| Add `katana` to external-binary whitelist / availability checks | `secbot/skills/_shared/sandbox.py`; `tests/security/test_sandbox.py`; `tests/agent/test_agent_registry.py` | Complete |
| Use Katana defaults equivalent to requested command | Handler builds `-u`, `-d 5`, `-jc`, `-ef css,png,jpg,gif,svg,woff,ttf,js`, `-aff`, `-o <scan_dir>/katana/katana_urls.txt`, `-silent`, `-no-color`; argv asserted in `tests/skills/test_katana_crawl_web_handler.py` | Complete |
| Use shared sandbox and no shell redirection | Handler calls `run_command(... capture="file", raw_log_path=...)`; no `subprocess`/`shell=True` in `secbot/skills/katana-crawl-web/handler.py` | Complete |
| Deduplicate Katana output before filtering | `_read_deduped_urls`; duplicate/fragment case asserted in handler tests | Complete |
| Classify critical/high/skip/neutral parameters | `_CRITICAL_PARAMS`, `_HIGH_PARAMS`, `_SKIP_PARAMS`, `_classify_param`; handler tests assert `cmd`, `id`, `file`, `theme`, `lang` cases | Complete |
| Detect JSON deserialization and XML/XXE hints | `_content_hints`; handler tests assert `@type` and `<!DOCTYPE` cases | Complete |
| Prioritize upload/export/fetch/download/admin/login-like paths | `_path_hints`; handler tests assert export/fetch/admin-login behavior | Complete |
| Drop static assets and static dictionary/region-list endpoints | `_is_static_asset`, `_is_static_dictionary_api`; handler tests assert static JS, region-list, and low-value preferences are excluded | Complete |
| Return bounded structured candidates for LLM context | Output schema plus `max_candidates` truncation test and schema validation test | Complete |
| Preserve two-layer architecture; no direct `vuln_scan` call | Prompt says return candidates only; handler only returns `recommended_action`; no agent-to-agent call path | Complete |
| Relevant spec/docs updated | `.trellis/spec/backend/tool-invocation-safety.md`, `.trellis/spec/backend/orchestrator-prompt.md`, `.trellis/spec/backend/architecture.md`, `.trellis/spec/backend/skill-contract.md` | Complete |
| Lint/type/test gate | Commands below rerun on 2026-05-17 | Complete |
| Trellis Phase 3.4 commit | Work and audit commits are present in `git log` | Complete |

## Verification Performed

Used Python 3.11 because the default Anaconda Python is too old for this repo's `tomllib` usage.

- `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m ruff check secbot/agents/orchestrator.py secbot/skills/_shared/sandbox.py secbot/skills/katana-crawl-web/handler.py tests/agent/test_agent_registry.py tests/agent/test_orchestrator_prompt.py tests/agent/tools/test_subagent_tools.py tests/security/test_sandbox.py tests/skills/test_metadata.py tests/skills/test_katana_crawl_web_handler.py`
  - Result: passed.
- `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m py_compile secbot/agents/orchestrator.py secbot/agents/registry.py secbot/agent/tools/spawn.py secbot/agent/subagent.py secbot/skills/_shared/sandbox.py secbot/skills/katana-crawl-web/handler.py tests/skills/test_katana_crawl_web_handler.py`
  - Result: passed.
- `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m pytest tests/agent/test_agent_registry.py tests/agent/test_orchestrator_prompt.py tests/agent/tools/test_subagent_tools.py tests/security/test_sandbox.py tests/skills/test_metadata.py tests/skills/test_katana_crawl_web_handler.py`
  - Result: `83 passed, 1 warning`.

The warning is in `tests/agent/tools/test_subagent_tools.py::test_spawn_tool_rejects_unknown_agent`: `RuntimeWarning: coroutine 'Queue.get' was never awaited`. It is not introduced by the Katana handler path and the targeted tests all passed.

## Commit Evidence

Trellis Phase 3.4 was completed after explicit user confirmation.

Commits:

- `ee61e391e feat(agent): add crawl_web katana crawler`
- `61033ce9e docs(trellis): update crawl_web katana finish audit`

Work commit files:

- `secbot/agents/orchestrator.py`
- `secbot/agents/crawl_web.yaml`
- `secbot/agents/prompts/crawl_web.md`
- `secbot/skills/_shared/sandbox.py`
- `secbot/skills/katana-crawl-web/SKILL.md`
- `secbot/skills/katana-crawl-web/handler.py`
- `secbot/skills/katana-crawl-web/input.schema.json`
- `secbot/skills/katana-crawl-web/output.schema.json`
- `tests/agent/test_orchestrator_prompt.py`
- `tests/security/test_sandbox.py`
- `tests/skills/test_metadata.py`
- `tests/skills/test_katana_crawl_web_handler.py`
- `.trellis/tasks/05-16-crawl-web-katana-skill/finish-audit.md`

Already present in HEAD from earlier related commits and not currently dirty:

- `.trellis/spec/backend/architecture.md`
- `.trellis/spec/backend/orchestrator-prompt.md`
- `.trellis/spec/backend/skill-contract.md`
- `.trellis/spec/backend/tool-invocation-safety.md`
- `tests/agent/test_agent_registry.py`
- `tests/agent/tools/test_subagent_tools.py`

Unrelated dirty files must not be included without explicit user direction:

- `ffuf_claude_skill-main/ffuf-skill/*` deletions
- `secbot/agents/vuln_detec.yaml`
- `secbot/agents/vuln_scan.yaml`
- `secbot/resource/fuzzDicts`
- `secbot/skills/ctf-web/`
- `secbot/skills/ffuf-skill/`
