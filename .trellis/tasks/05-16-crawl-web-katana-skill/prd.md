# brainstorm: crawl_web agent and katana skill

## Goal

Add a `crawl_web` expert agent that crawls an authorized web target with Katana, deduplicates discovered URLs, filters them by parameter names, data format hints, and business-path heuristics, then returns structured vulnerability hypotheses that the orchestrator can hand to `vuln_scan`.

## What I already know

* The requested crawler command is:
  `katana -u http://TARGET.com -d 5 -jc -ef css,png,jpg,gif,svg,woff,ttf,js -aff -o ./katana_urls.txt 2>/dev/null`
* The desired decision logic prioritizes:
  * Critical parameter names: `cmd`, `exec`, `command`, `file`, `path`, `url`, `uri`, `template`, `query`
  * High-risk parameter names: `id`, `user id`, `username`, `xml`, `data`, `payload`
  * Low-value parameter names to skip: `color`, `theme`, `page_size`, `lang`, `sort`, `order`
  * JSON class/type indicators such as `{"@type":"com.xxx.JdbcRowSetImpl"}` for deserialization fuzzing
  * XML payloads for XXE testing
  * Business-sensitive paths such as `/upload`, `/export`, `/fetch`, `/download`, and admin login endpoints
  * Static assets and static dictionary/region-list style APIs should be dropped.
* Existing agent registration is YAML-based under `secbot/agents/*.yaml`.
* Existing skill registration is directory-based under `secbot/skills/<skill-name>/` with `SKILL.md`, `handler.py`, and JSON schemas.
* Skill subprocess execution must go through the shared sandbox, not raw subprocess.
* The current architecture forbids agent-to-agent calls from inside an expert agent. `crawl_web` should therefore return structured findings for the orchestrator to route to `vuln_scan`, unless we intentionally change the architecture.

## Assumptions (temporary)

* Katana should be registered as a secbot skill, likely named `katana-crawl-web`.
* `crawl_web` should be a new expert agent with the single scoped skill `katana-crawl-web`.
* URL deduplication and heuristic filtering should live in the Katana skill handler so output is deterministic and testable.
* The MVP does not perform exploit/fuzz payload execution itself; it only classifies candidates and recommends tests for `vuln_scan`.
* Targets are authorized and in scope; the skill should still validate URL shape to avoid shell argument injection.

## Open Questions

* None currently blocking.

## Requirements (evolving)

* Add a `crawl_web` agent YAML and prompt.
* Add a Katana-backed crawl skill with metadata, input schema, output schema, and handler.
* Add `katana` to the external-binary whitelist / availability checks.
* Run Katana with defaults equivalent to the requested command: depth 5, JavaScript crawling enabled, excluded extensions `css,png,jpg,gif,svg,woff,ttf,js`, automatic form fill enabled, and raw output persisted.
* Deduplicate `katana_urls.txt` output before filtering.
* Classify URL/query/body-derived parameters into critical, high, skip, or neutral buckets.
* Detect JSON deserialization and XML/XXE indicators where available from URL or crawled artifacts.
* Prioritize `/upload`, `/export`, `/fetch`, `/download`, and admin login-like paths.
* Drop static assets and pure static dictionary/region-list style endpoints.
* Return structured candidates containing URL, parameters, guessed vulnerability types, reasons, and recommended downstream scan action.
* Follow the existing two-layer architecture: `crawl_web` must not directly invoke `vuln_scan`; it returns `candidates` for the orchestrator to route in a later tool call.

## Acceptance Criteria (evolving)

* [ ] `load_agent_registry(secbot/agents, skill_names=...)` accepts the new `crawl_web` agent.
* [ ] The Katana skill metadata validates via the existing skill metadata loader.
* [ ] The Katana handler uses the shared sandbox and does not invoke shell redirection.
* [ ] Unit tests cover deduplication, static-resource filtering, parameter-risk classification, business-path prioritization, JSON deserialization hints, and XML/XXE hints.
* [ ] The skill returns a bounded structured summary suitable for LLM context.
* [ ] `crawl_web` only returns candidates; it does not directly call `vuln_scan`.
* [ ] Existing agent/skill tests still pass.

## Definition of Done

* Tests added/updated for agent registry and skill behavior.
* Relevant backend specs are included in Trellis context JSONL before implementation starts.
* Lint/typecheck/test commands pass where available.
* Documentation/spec notes updated if the agent handoff behavior creates a new convention.

## Out of Scope (explicit)

* Running exploit payloads directly from `crawl_web`.
* Letting `crawl_web` bypass the orchestrator to call `vuln_scan` unless explicitly approved as an architecture change.
* Crawling targets outside the user-provided scope.
* Full authenticated crawling or browser automation unless later added to MVP.

## Technical Notes

## Research References

* [`research/crawl-web-integration.md`](research/crawl-web-integration.md) — Integration map for new `crawl_web` agent, `katana-crawl-web` skill, sandbox whitelist, routing constraints, and tests.

## Technical Approach

Implement `crawl_web` as a normal expert agent backed by one scoped skill, `katana-crawl-web`.

The skill handler will:

* Validate an HTTP/HTTPS target and bounded crawl options.
* Resolve Katana via `tools.skillBinaries.katana` or `PATH`.
* Invoke Katana through the shared sandbox with argv equivalent to the requested command, writing Katana output to `ctx.scan_dir / "katana" / "katana_urls.txt"`.
* Parse the Katana URL file, dedupe URLs in first-seen order, drop static/noisy endpoints, classify parameters and content hints, and return bounded `candidates`.

The agent prompt will:

* Tell `crawl_web` to call `katana-crawl-web`, summarize candidate classes, write concise blackboard notes, and never call `vuln_scan` directly.
* Explain that the orchestrator is responsible for routing returned candidates into later vulnerability scanning.

Implementation files likely needed:

* `secbot/agents/crawl_web.yaml`
* `secbot/agents/prompts/crawl_web.md`
* `secbot/skills/katana-crawl-web/SKILL.md`
* `secbot/skills/katana-crawl-web/handler.py`
* `secbot/skills/katana-crawl-web/input.schema.json`
* `secbot/skills/katana-crawl-web/output.schema.json`
* `secbot/skills/_shared/sandbox.py`
* `.trellis/spec/backend/tool-invocation-safety.md`
* Tests under `tests/agent/`, `tests/skills/`, and possibly `tests/security/`.

## Implementation Plan

* PR1: Add agent/skill scaffolding, Katana whitelist, schemas, metadata, and registry tests.
* PR2: Implement Katana handler parsing, deduplication, filtering, classification, and unit tests.
* PR3: Add prompt/routing docs, spec update, and targeted regression checks.

* Relevant specs:
  * `.trellis/spec/backend/agent-registry-contract.md`
  * `.trellis/spec/backend/skill-contract.md`
  * `.trellis/spec/backend/tool-invocation-safety.md`
  * `.trellis/spec/backend/orchestrator-prompt.md`
* Existing patterns inspected:
  * `secbot/agents/vuln_scan.yaml`
  * `secbot/agents/prompts/vuln_scan.md`
  * `secbot/skills/httpx-probe/handler.py`
  * `secbot/skills/ffuf-dir-fuzz/handler.py`
  * `secbot/skills/_shared/sandbox.py`
  * `secbot/skills/_shared/runner.py`
  * `secbot/skills/metadata.py`

## Decision (ADR-lite)

**Context**: The requested flow says to send URL, parameters, and guessed vulnerabilities to the `vuln_scan` agent. The current backend spec forbids expert agents from calling other expert agents directly.

**Decision**: Keep the current architecture. `crawl_web` will return structured `candidates`; the orchestrator remains responsible for deciding whether and how to call `vuln_scan`.

**Consequences**: The MVP is smaller and aligns with the registry contract. A later task can extend `vuln_scan` input schema if URL-parameter candidates need first-class downstream handling.
