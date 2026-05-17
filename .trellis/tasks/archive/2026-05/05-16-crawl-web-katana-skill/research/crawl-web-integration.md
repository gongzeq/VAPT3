# Research: crawl_web expert agent + katana-crawl-web skill integration

- Query: How to integrate a `crawl_web` expert agent and `katana-crawl-web` skill into the existing secbot two-layer agent/skill architecture.
- Scope: mixed
- Date: 2026-05-16

## Findings

### Task context

- `.trellis/tasks/05-16-crawl-web-katana-skill/prd.md` - Defines the MVP: add a Katana-backed crawler skill, add a `crawl_web` expert agent, classify/dedupe crawled URLs, return structured candidates for the orchestrator to hand to `vuln_scan`, and do not let `crawl_web` invoke `vuln_scan` directly.
- The requested Katana default command is equivalent to `katana -u <target> -d 5 -jc -ef css,png,jpg,gif,svg,woff,ttf,js -aff -o <file>`.

### Architecture constraints

- `.trellis/spec/backend/architecture.md:8` says the platform is a two-layer agent system: orchestrator -> expert agent -> skill -> external binary.
- `.trellis/spec/backend/architecture.md:63` forbids an expert agent from invoking another expert agent. `crawl_web` must return `candidates`; the orchestrator should decide whether to call `vuln_scan`.
- `.trellis/spec/backend/agent-registry-contract.md:20` says one YAML file per expert agent and filename stem is the orchestrator-visible tool name.
- `.trellis/spec/backend/agent-registry-contract.md:80` requires agent names to match `^[a-z][a-z0-9_]*$`; `crawl_web` is valid.
- `.trellis/spec/backend/agent-registry-contract.md:81` requires each `scoped_skills` entry to exist as a registered skill.
- `.trellis/spec/backend/agent-registry-contract.md:121` says the orchestrator never sees individual skill names; skills are implementation details of expert agents.
- `.trellis/spec/backend/agent-registry-contract.md:129` forbids defining an agent in Python instead of YAML.
- `.trellis/spec/backend/agent-registry-contract.md:130` forbids sharing a skill across two expert agents. `katana-crawl-web` must only appear under `crawl_web`.
- `.trellis/spec/backend/skill-contract.md:8` defines skill package shape: `SKILL.md`, `handler.py`, `input.schema.json`, `output.schema.json`.
- `.trellis/spec/backend/skill-contract.md:19` requires kebab-case skill directory names such as `katana-crawl-web`.
- `.trellis/spec/backend/skill-contract.md:93` forbids `print()` in skill handlers.
- `.trellis/spec/backend/skill-contract.md:94` says all external command execution goes through the sandbox.
- `.trellis/spec/backend/skill-contract.md:95` says raw stdout must not be returned in `summary`; use `raw_log_path` for raw bytes.
- `.trellis/spec/backend/tool-invocation-safety.md:15` says `ExecToolConfig.enable` defaults false and raw shell is not standard LLM surface.
- `.trellis/spec/backend/tool-invocation-safety.md:16` says every external binary call reaches the LLM as a schema-validated `SkillTool`.
- `.trellis/spec/backend/tool-invocation-safety.md:44` makes raw subprocess and `shell=True` review-blocking inside `secbot/skills/**`.
- `.trellis/spec/backend/tool-invocation-safety.md:60` says adding a scanner binary requires amending both the spec whitelist and sandbox constant, and documenting version/install info.
- `.trellis/spec/backend/orchestrator-prompt.md:19` currently documents the natural order as `asset_discovery -> port_scan -> vuln_scan -> ... -> report`; adding `crawl_web` as a web-app stage between `port_scan` and `vuln_scan` is a routing-policy change and should update the spec plus tests.

### Agent registry patterns

- `secbot/agents/asset_discovery.yaml:1` is the simplest YAML pattern: `name`, Chinese `display_name`, routing `description`, `system_prompt_file`, `scoped_skills`, `max_iterations`, `emit_plan_steps`, `input_schema`, and `output_schema`.
- `secbot/agents/vuln_scan.yaml:10` shows multiple scoped skills and is the likely downstream consumer for crawl candidates.
- `secbot/agents/prompts/asset_discovery.md:1` and `secbot/agents/prompts/vuln_scan.md:1` show prompt structure: agent role, tools/procedure, output contract, blackboard guidance.
- `secbot/agents/registry.py:115` loads all `*.yaml` agent specs.
- `secbot/agents/registry.py:150` optionally resolves known skill names and fails for unknown scoped skills.
- `secbot/agents/registry.py:176` sorts YAML files for deterministic registry order.
- `secbot/agents/registry.py:179` enforces no skill sharing across expert agents.
- `secbot/agents/registry.py:194` computes per-agent `required_binaries` and `missing_binaries` from skill metadata when `skills_root` is provided.
- `secbot/agents/registry.py:261` resolves `system_prompt_file` relative to the YAML file.
- `secbot/agents/registry.py:271` validates `input_schema` and `output_schema`.
- `secbot/agents/orchestrator.py:62` renders the agent table dynamically from the registry, so a valid `crawl_web.yaml` appears in the available-agents table automatically.
- `secbot/agents/orchestrator.py:30` hard-codes the current stage order and should be reviewed if `crawl_web` becomes a default web path.

Recommended new files:

- `secbot/agents/crawl_web.yaml` - New expert declaration.
- `secbot/agents/prompts/crawl_web.md` - Prompt that tells the agent to run `katana-crawl-web`, return bounded structured candidates, write only useful blackboard notes, and never call `vuln_scan` itself.

Suggested `crawl_web.yaml` shape:

```yaml
name: crawl_web
display_name: Web 爬虫
description: |
  Crawl an authorized web target with Katana, deduplicate discovered URLs,
  classify parameterized endpoints and business-sensitive paths, and return
  vulnerability hypotheses for vuln_scan.

system_prompt_file: ./prompts/crawl_web.md

scoped_skills:
  - katana-crawl-web

max_iterations: 4
emit_plan_steps: true

input_schema:
  type: object
  required: [target]
  properties:
    target:
      type: string
      description: HTTP/HTTPS URL in authorized scope.
    depth:
      type: integer
      minimum: 1
      maximum: 10
      default: 5
    max_candidates:
      type: integer
      minimum: 1
      maximum: 500
      default: 100

output_schema:
  type: object
  required: [candidates]
  properties:
    candidates:
      type: array
      items:
        type: object
        required: [url, guessed_vulnerabilities, reasons, recommended_action]
        properties:
          url: {type: string}
          parameters:
            type: array
            items:
              type: object
              properties:
                name: {type: string}
                risk: {type: string, enum: [critical, high, neutral, skipped]}
          guessed_vulnerabilities:
            type: array
            items: {type: string}
          reasons:
            type: array
            items: {type: string}
          recommended_action: {type: string}
```

### Skill package patterns

- `secbot/skills/metadata.py:56` parses `SKILL.md` front matter and validates required fields.
- `secbot/skills/metadata.py:75` requires `name` to equal the skill directory name.
- `secbot/skills/metadata.py:87` validates `network_egress`.
- `secbot/skills/metadata.py:93` requires positive `expected_runtime_sec`.
- `secbot/skills/metadata.py:97` validates `summary_size_hint`.
- `secbot/agent/tools/skill.py:231` discovers skill directories and wraps valid skills as LLM-facing `SkillTool` instances.
- `secbot/agent/tools/skill.py:294` builds a `SkillTool` from `SKILL.md`, `input.schema.json`, and `handler.py`.
- `secbot/skills/httpx-probe/handler.py:21` is the best binary-resolution pattern: check `tools.skill_binaries.<binary>`, then `shutil.which`, else raise `SkillBinaryMissing` with a useful message.
- `secbot/skills/httpx-probe/handler.py:50` shows a URL/host validation regex for a ProjectDiscovery web tool.
- `secbot/skills/httpx-probe/handler.py:103` materializes input lists under `ctx.scan_dir`.
- `secbot/skills/httpx-probe/handler.py:124` calls the resolver and then shared `execute`.
- `secbot/skills/ffuf-dir-fuzz/handler.py:71` is the richest example of handler-level validation, materialized files, tool-specific output files, and bounded parsing.
- `secbot/skills/_shared/runner.py:38` provides `execute(...)`, which wraps sandbox execution, timeout/cancel handling, raw log capture, parser invocation, and `SkillResult`.

Recommended new files:

- `secbot/skills/katana-crawl-web/SKILL.md`
- `secbot/skills/katana-crawl-web/handler.py`
- `secbot/skills/katana-crawl-web/input.schema.json`
- `secbot/skills/katana-crawl-web/output.schema.json`

Suggested `SKILL.md` metadata:

```yaml
---
name: katana-crawl-web
display_name: Katana web crawl
version: 1.0.0
risk_level: medium
category: crawl_web
external_binary: katana
binary_min_version: "1.0.0"
network_egress: required
expected_runtime_sec: 600
summary_size_hint: medium
---
```

Handler recommendations:

- Implement `_resolve_katana_binary(cli)` using the same precedence as `httpx-probe`: `tools.skill_binaries["katana"]` first, then PATH `katana`, then `SkillBinaryMissing`.
- Validate `target` as HTTP/HTTPS URL with an allow regex before it becomes an argv element. Avoid accepting quotes, shell metacharacters, newlines, or backslashes.
- Build Katana argv as a list, not a string. Use `["-u", target, "-d", str(depth), "-jc", "-ef", ",".join(excluded_extensions), "-aff", "-o", str(urls_file), "-silent", "-no-color"]`.
- Do not use shell redirection for `2>/dev/null`; sandbox already captures stdout/stderr to the raw log. If noisy stderr matters, parse only the `-o` file and treat the raw log as diagnostics.
- Use `ctx.scan_dir / "katana" / "katana_urls.txt"` for Katana's URL output file and `ctx.raw_log_dir / "katana-crawl-web.log"` for subprocess stdout/stderr.
- Use `execute(..., parser=_parse_factory(urls_file), raw_log_name="katana-crawl-web.log")` or call `run_command` directly only if the handler needs finer control. The shared `execute` path is preferred.
- Deduplicate while preserving first-seen order. Normalize cautiously: parse URLs with `urllib.parse`, lower-case scheme/host, remove fragments, preserve path/query, and avoid changing parameter values in ways that alter evidence.
- Filter static assets twice: pass `-ef` to Katana and also drop output URLs whose path suffix matches static extensions, because URLs can still leak via redirects or nonstandard casing.
- Parameter classification should be deterministic and table-driven:
  - Critical: `cmd`, `exec`, `command`, `file`, `path`, `url`, `uri`, `template`, `query`.
  - High: `id`, `userid`, `user_id`, `username`, `xml`, `data`, `payload`.
  - Skip/low-value: `color`, `theme`, `page_size`, `lang`, `sort`, `order`.
  - Neutral: other parameters retained only when path/content hints are strong enough.
- Business path heuristic should boost `/upload`, `/export`, `/fetch`, `/download`, `/admin`, `/login`, and similar sensitive endpoints.
- Static dictionary/region-list APIs can be dropped by low-value path keywords such as `/dict`, `/dictionary`, `/region`, `/province`, `/city`, `/country`, `/locale`, and by query-only low-value parameters.
- JSON/XML hints can be detected from decoded query values and any available form/body artifacts:
  - JSON deserialization: decoded values containing `"@type"` or class-like package names.
  - XML/XXE: decoded values beginning with XML declarations, containing `<!DOCTYPE`, or XML-looking parameter names such as `xml`.
- Return bounded `summary` fields such as `total_urls`, `deduped_urls`, `filtered_urls`, `candidate_count`, `candidates`, and maybe `raw_urls_path`.
- Include only concise reasons and candidate strings in summary. Full Katana output and raw process output belong on disk.

### Sandbox and binary whitelist

- `secbot/skills/_shared/sandbox.py:23` is the implemented scanner whitelist. It currently includes `nmap`, `fscan`, `nuclei`, `hydra`, `httpx`, `ffuf`, `sqlmap`, `ghauri`, `python3`, and `git`, but not `katana`.
- `secbot/skills/_shared/sandbox.py:37` rejects dangerous characters in argv elements.
- `secbot/skills/_shared/sandbox.py:72` is the only valid process entry point for skills.
- `secbot/skills/_shared/sandbox.py:89` rejects non-whitelisted binaries before execution.
- `secbot/skills/_shared/sandbox.py:98` resolves binaries with `shutil.which`.
- `secbot/config/schema.py:265` defines `tools.skill_binaries`, so a Katana override can be configured as `tools.skillBinaries.katana`.
- `config.example.json:3` already demonstrates binary overrides for `sqlmap` and `httpx`; adding `katana` is optional documentation polish if desired.

Required code/spec updates:

- Add `"katana"` to `secbot/skills/_shared/sandbox.py:BINARY_WHITELIST`.
- Update `.trellis/spec/backend/tool-invocation-safety.md` whitelist text and version/install note for Katana.
- Consider updating `.trellis/spec/backend/architecture.md:25` external binary examples to include Katana.
- Update `tests/security/test_sandbox.py:21` to assert `katana` is whitelisted.

### Orchestrator and subagent routing

- `secbot/agent/loop.py:498` loads the agent registry at loop startup.
- `secbot/agent/loop.py:503` passes `skills_root` and `skill_binary_overrides` into the registry, so a new Katana skill's `external_binary: katana` automatically affects `crawl_web.available`.
- `secbot/agent/loop.py:632` registers orchestrator tools. The orchestrator does not receive direct skill tools.
- `secbot/agent/loop.py:647` registers operational tools for non-orchestrator loops.
- `secbot/agent/loop.py:666` explicitly keeps `ExecTool` disabled even for operational loops.
- `secbot/agent/loop.py:694` registers discovered skills for non-orchestrator loops.
- `secbot/agent/tools/spawn.py:17` exposes optional `agent` selection on `delegate_task`.
- `secbot/agent/tools/spawn.py:80` validates the requested expert agent and rejects unknown/offline agents with a readable error.
- `secbot/agent/subagent.py:469` says subagents get `SkillTool` instances.
- `secbot/agent/subagent.py:474` restricts skill registration to `spec.scoped_skills` when an expert spec is used.
- `secbot/agent/subagent.py:491` binds per-subagent `SkillContext` and raw log directory.
- `tests/agent/tools/test_subagent_tools.py:524` verifies scoped skill filtering and should naturally cover `crawl_web` if extended or duplicated.

Orchestrator prompt consideration:

- `secbot/agents/orchestrator.py:30` currently routes directly from `port_scan` to `vuln_scan`. To make crawling a default web-app stage, update that hard rule and likely tests in `tests/agent/test_orchestrator_prompt.py`.
- Because `.trellis/spec/backend/orchestrator-prompt.md:44` says new hard rules require ADR/spec enforcement, this should be captured via the spec-update phase, not silently changed.
- If implementation avoids prompt hard-rule changes, `crawl_web` will still be listed in the auto-generated agent table, but the orchestrator may not consistently choose it before `vuln_scan`.

### Test targets

- `tests/skills/test_metadata.py:30` checks expected secbot skills from `scan_skills`; add `katana-crawl-web` to the required list or add a focused metadata test.
- Add `tests/skills/test_katana_crawl_web_handler.py` for handler behavior. Use `tests/skills/conftest.py:53` fake sandbox fixture or monkeypatch `secbot.skills._shared.runner.run_command` if the handler uses shared `execute`.
- `tests/skills/conftest.py:54` fake writes stdout to `raw_log_path`, but Katana writes URLs to the `-o` output file. Tests should monkeypatch `run_command` to also write the expected `katana_urls.txt` path, similar to the ffuf tests that write a tool-specific JSON file.
- `tests/skills/test_ffuf_handlers.py` is a good model for mocked binary, parser, validation, and no-real-network unit tests.
- `tests/security/test_sandbox.py:21` should include `katana` in required whitelist assertions.
- `tests/agent/test_agent_registry.py:17` has `REAL_SKILL_NAMES`; add `katana-crawl-web`.
- `tests/agent/test_agent_registry.py:45` asserts the exact shipped registry names; add `crawl_web`.
- `tests/agent/test_agent_registry.py:98` and related availability tests can add coverage that `crawl_web.required_binaries == ("katana",)` when all binaries are present, and missing Katana makes only `crawl_web` offline.
- `tests/agent/test_orchestrator_prompt.py:24` is generic and should pick up the new agent automatically; add explicit assertions only if routing hard rules are updated.
- `tests/agent/tools/test_subagent_tools.py:524` can be extended with `spec = registry.get("crawl_web")` to assert only `katana-crawl-web` is registered for that expert.

Recommended handler unit cases:

- Happy path: Katana output with duplicates, static assets, query URLs, and sensitive paths produces bounded candidates and raw log path.
- Deduplication: repeated URLs preserve first-seen order.
- Static filtering: `.css`, `.png`, `.jpg`, `.gif`, `.svg`, `.woff`, `.ttf`, `.js` URLs are dropped.
- Critical parameter classification: `cmd`, `exec`, `command`, `file`, `path`, `url`, `uri`, `template`, `query`.
- High parameter classification: `id`, `user_id`, `userid`, `username`, `xml`, `data`, `payload`.
- Low-value skip: `color`, `theme`, `page_size`, `lang`, `sort`, `order`.
- Business path boosting: `/upload`, `/export`, `/fetch`, `/download`, `/admin`, `/login`.
- Static dictionary/region APIs dropped.
- JSON deserialization hint: decoded query/body value with `@type` produces a deserialization hypothesis.
- XML/XXE hint: decoded XML or `<!DOCTYPE` produces an XXE hypothesis.
- Invalid target rejects before sandbox call.
- Timeout/cancel/nonzero exit returns structured `summary.error`/`summary.cancelled` via shared `execute`.
- Missing binary raises `SkillBinaryMissing`.

### External references

- ProjectDiscovery Katana usage docs: https://docs.projectdiscovery.io/opensource/katana/usage
  - Confirms `-u`/`-list` accepts target URLs, `-d` controls maximum crawl depth, `-jc` enables JavaScript endpoint crawling, `-aff` enables automatic form filling, `-ef` filters extensions, and `-o` writes output to a file.
  - Also documents useful output flags `-j` JSONL, `-silent`, `-no-color`, and `-version`.
- ProjectDiscovery Katana overview: https://docs.projectdiscovery.io/opensource/katana
  - Describes Katana as a CLI web crawling tool for gathering websites/endpoints, including JavaScript and headless crawling support.
- ProjectDiscovery Katana install docs: https://docs.projectdiscovery.io/opensource/katana/install
  - Installation uses `go install github.com/projectdiscovery/katana/cmd/katana@latest`; include this in any spec/docs note for the new `katana` binary.

## Caveats / Not Found

- `task.py current --source` returned no active task in this agent environment, but the parent dispatch gave the explicit task directory. Research was therefore written under `.trellis/tasks/05-16-crawl-web-katana-skill/research/`.
- There is no existing `secbot/skills/katana-*` package and no `crawl_web` agent YAML.
- The spec whitelist in `.trellis/spec/backend/tool-invocation-safety.md` is stale relative to the implemented whitelist in `secbot/skills/_shared/sandbox.py`; update both when adding `katana`.
- The current `vuln_scan` input schema requires `services`, not crawl candidates. Passing `crawl_web.candidates` downstream may need either orchestrator-level conversion into existing service-like inputs or a future schema extension for `vuln_scan`.
- Katana can emit JSONL (`-j`) and form extraction (`-fx`). The PRD-requested command uses plain URL output. MVP can parse the URL file only; richer body/form detection may require opting into JSONL/form extraction later.
