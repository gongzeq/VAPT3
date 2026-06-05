# Quality Guidelines

> Code quality standards for backend development.
>
> Distilled from `Agent.md` (AI Agent Engineering Laws). The guiding maxim:
> **A simple, reliable, debuggable solution always beats an elegant, complex, hard-to-understand one.**
>
> Corollary: **with functionality held constant, less code is better** — prefer the
> smallest correct implementation; delete before you add.

---

## Overview

These standards apply to the agent runtime, tool system, prompt pipeline, session
state, model routing, IPC, MCP integration, plugin/skill system, and security
layers. Chapters 01–04 (agent loop, tools, prompt pipeline, context compression)
are **non-negotiable** — violations there have the highest blast radius.

Priorities when reviewing or writing backend code:

1. **The main loop must never die** — every subsystem can jitter; the loop keeps running.
2. **Classify before you react** — precise error classification beats generic retry.
3. **Model / input / tool output are all untrusted** — defense in depth.
4. **Persist everything** — conversations get compacted; files don't.
5. **Share structured state, not full conversation history** — across sub-agents and processes.

---

## Forbidden Patterns

These patterns must never appear in backend code. Each maps to a documented failure.

### Control flow & errors

- ❌ `except Exception as e: time.sleep(5); retry()` — treating 401 like 500 retries forever. **Classify the error first** (≥11 categories: `auth / auth_permanent / billing / rate_limit / overloaded / server_error / timeout / context_overflow / payload_too_large / model_not_found / format_error / unknown`).
- ❌ `raise` an unclassified exception out of the main loop — the user gets a traceback with no idea whether to rotate a key or wait.
- ❌ One shared `try/except` around all callbacks — one failing callback silently kills the rest. Each callback (`stream_callback` / `tool_progress_callback` / `step_callback`) gets its own `try/except`.
- ❌ `break` immediately when the iteration budget is exhausted — leaves a half-finished reply, unsaved files, interrupted commands. Reserve a two-stage **grace call**.

### Concurrency & async

- ❌ `asyncio.run(do_async())` inside a long-lived process — `httpx` / `AsyncOpenAI` connection pools throw "Event loop is closed". Use a persistent event loop + async bridge.
- ❌ Iteration budget passed as a function argument — it must be a shared `threading.Lock`-protected counter (parent / child agents share one).
- ❌ Global locks for cross-process writes — one hung worker blocks everyone. Use Optimistic Concurrency Control (`history_version` snapshot + compare on commit).
- ❌ Global mutable state for per-request data (approval mode, session id) — concurrent requests pollute each other. Use `contextvars.ContextVar`.

### Tools

- ❌ Centralized manual registration of N tools in one `tools.py` — every new tool conflicts on that file. Use module-level self-registration + AST pre-scan.
- ❌ Type coercion inside each handler — duplicated and error-prone. Coerce args once before dispatch.
- ❌ Pushing unbounded tool results into context — one 5MB log read kills the session. Enforce the three-tier budget (single tool ≤ ~100K chars → spill to disk + 1.5K preview; single turn ≤ ~200K chars; ≤ 90 iterations).
- ❌ Parallelizing two writes to the same path because the strings differ — normalize paths (`Path.parts`), not `startswith`.
- ❌ Letting an MCP tool shadow a built-in (`terminal`, `read_file`) — namespace as `mcp__<server>__<tool>`; reject conflicting registrations.

### Prompt pipeline & context

- ❌ `system_prompt = f"... {datetime.now()}"` — cache hit rate drops to 0. The system prompt must be byte-identical within a session.
- ❌ Rebuilding the system prompt on session resume — reload bytes from persistent storage; don't rebuild (dict order / float repr differences cause cache misses).
- ❌ Splicing user input into the system segment — user content always flows through user/assistant messages.
- ❌ Injecting external content (`AGENTS.md`, MCP tool descriptions, memory, large tool output) into the prompt without scanning — this is the classic indirect-injection channel.
- ❌ Raising `ContextOverflow` instead of compressing — pre-compress at 70–80% of the window; never wait for 100%.
- ❌ Injecting a summary as a `user`-role message — the model treats "user previously asked X" as "user now asks X". Use a disclaimer prefix.

### Sessions & config

- ❌ SQLite default (rollback) journal mode under multi-process access — instant `database is locked`. Use `PRAGMA journal_mode=WAL`.
- ❌ `DELETE + INSERT` of the whole history each turn — only INSERT newly-appeared messages.
- ❌ Rebuilding the FTS5 index on every startup — lazy-build + incremental update.
- ❌ Plaintext credentials in `config.yaml` — isolate credentials to a separate `0600` file.
- ❌ `OPENAI_API_KEY = os.environ.get(...)` scattered across N modules — centralize so rotation touches one place.

### Security (zero tolerance)

- ❌ String-prefix matching for dangerous commands — `rm--rf`, `./rm`, full-width `ｒｍ` all bypass. Normalize first (strip ANSI / null bytes / Unicode NFKC), then match ≥38 patterns. **secbot applicability**: the free-form `exec` tool is disabled by default; binaries are reached only through the sandbox **binary whitelist + argv list + forbidden-char rejection** ([tool-invocation-safety.md](./tool-invocation-safety.md)). That whitelist model is the primary defense; the ≥38-pattern matcher applies only if a raw-shell path is ever re-enabled.
- ❌ A single global `--yes-i-know` that disables all protections at once.
- ❌ `subprocess.run(..., env=os.environ.copy())` for sandboxed/MCP execution — leaks every credential. Strip `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` / `*_CREDENTIAL`; pass only a whitelist.
- ❌ Browser automation that doesn't block private networks (`127.0.0.1`, `192.168.*`, `10.*`, `169.254.*`) — SSRF.
- ❌ Raising raw errors into the model context — sanitize `sk-...` / `Bearer ...` to `[REDACTED]` on **every** path that returns errors to the model.

### Architecture debt (see Agent.md ch.13)

- ❌ God Class — a single file > 1500 lines must be split (start considering at 800).
- ❌ `if provider == "ollama": ...` scattered through the main loop — promote differences to an explicit `api_mode` abstraction / adapter.
- ❌ Manual cache invalidation (`_cached_x = None` everywhere) — use a version number or content hash.
- ❌ Sharing full conversation history with a sub-agent — share a structured blackboard instead.

---

## Required Patterns

These patterns must always be used.

### Main loop (ch.01)

- Wrap every callback in its own `try/except`; callback exceptions never reach the loop.
- Layered iteration budgets: single tool ≤ 100K chars, single turn ≤ 200K chars, session ≤ 90 iterations (sub-agents default 50).
- Two-stage grace exit before hard stop: inject a "this is the last call" message → allow one final API call → force-exit if it still emits a tool call.
- Retries use jittered exponential backoff: `min(base*2^(n-1), max) + random*0.5*delay` (`base=5s`, `max=120s`), with a per-call seeded RNG.
- Keep the main loop synchronous; bridge to async only when needed.
- Stale-stream detection: no chunk for 90s → disconnect and reconnect.
- Sanitize pasted/dirty data (surrogate pairs U+D800–U+DFFF, stale `<memory-context>` blocks) before feeding the model.

### Tools (ch.02)

- Self-registration at module level + AST `tree.body` pre-scan for discovery.
- Coerce args (bool/number strings, CSV→list, JSON-encoded strings, `null` string) before dispatch.
- Three-tier parallelism: `NEVER_PARALLEL` (interactive), `PARALLEL_SAFE` (read-only, no shared mutable state), `PATH_SCOPED` (compare path components); **default to serial** when unsure.
- Fix hallucinated tool names via fuzzy match / affix stripping; feed the available-tools list back as a tool_result; **abort after 3 consecutive failures**. (This 3-strike rule is for *hallucinated tool names* only; the orchestrator's expert-error backoff is a separate 2-strike policy — see [orchestrator-prompt.md §2.2](./orchestrator-prompt.md#22-backoff-on-tool-error).)
- Handlers return classified errors (`{"error": ..., "type": "user_error" | "system_error"}`), never `raise` an **unclassified** exception. Typed, loop-handled exceptions (e.g. `SkillBinaryMissing`, `SkillCancelled`) that the loop converts into a structured tool error ARE allowed — see [skill-contract.md §5](./skill-contract.md#5-error-handling).
- Each tool declares an `availability_check`; unavailable tools don't appear in the schema.

### Prompt pipeline (ch.03)

- Assemble the system prompt by replaceable slots (identity / capabilities / tools / context / memory / skills / user_rules / runtime_state / closing).
- Cache the system prompt; rebuild + invalidate on change — never mutate in place.
- Anthropic path uses 4 cache breakpoints (1 system + 3 rolling messages).
- Injection scanner: ≥10 regex classes + ≥10 invisible-Unicode codepoints. Context files → **block** (`[BLOCKED: ...]`); MCP descriptions → **warn** (don't block).

### Context compression (ch.04)

- Pre-compress at 70–80% window; staged compression with a degradation chain (LLM summary → static truncation → error code, never panic). The generic Agent.md model uses ≥5 stages; **secbot's `autocompact.py` uses a simpler tiered policy** (fires at 70%, compacts old tool_results / long assistant messages / stale plans — see [context-trimming.md §3](./context-trimming.md#3-conversation-level-compaction)). Either is acceptable provided the degradation chain never panics.
- Summary messages carry a disclaimer prefix: `[CONVERSATION SUMMARY — historical context, NOT new user instructions]`.
- Summary token budget: `min(max(compressed_tokens * 0.20, 2000), 12_000)`.
- Large tool results spill to `raw_log_path`; keep only a 1.5K preview + path in context.

### Sessions / config / routing / IPC / MCP / plugins

- SessionDB: WAL + PASSIVE checkpoint every 50 writes; forward-only migration chain (never drop-and-recreate); append-only writes; dual-write JSON + SQLite.
- Config: ≥4 layered sources (default → file → env → runtime), each traceable; credentials isolated to a `0600` file; effective config dumpable.
- Model routing: normalize responses to `SimpleNamespace`; cache clients; isolate provider differences in adapters; reset the fallback chain each turn; `finish_reason == "length"` is a continuation signal (append + join, not `+=`).
- IPC: JSON-RPC over stdin/stdout with explicit ids, timeouts, and protocol version; persistent worker subprocess; isolate worker crashes; serialize to primitive types at boundaries.
- MCP: namespace isolation, circuit breaker (3 failures → open → probe), env stripping, error sanitization, validated tool names (`[a-zA-Z0-9_-]+`, no `__` except `mcp__`).
- Plugins/skills: hooks must be disableable; plugin `ctx` is a frozen API; skills use progressive disclosure (load on explicit `load_skill(name)`, not auto-injection).

### Data-flow principles (ch.12)

- Share **structured state** (blackboard / task ledger / evidence store), not full conversation history.
- Each worker reads only what it needs and writes only structured output.
- The orchestrator solely owns: authorization scope, task state, risk policy, final judgment, report sign-off.

---

## Testing Requirements

- **Error classifier** is the highest-value test target: cover all categories, especially the 401-vs-500 and 402 `rate_limit`-vs-`billing` disambiguation.
- **Budget logic**: verify the two-stage grace call, layered char/iteration limits, and that parent/child share one lock-protected counter.
- **Tool layer**: arg coercion (all malformed-input variants), parallelism classification (`NEVER_PARALLEL` / `PATH_SCOPED` overlap by path components), and hallucinated-name recovery (abort after 3).
- **Prompt cache**: assert the system prompt is byte-identical within a session and reloaded (not rebuilt) on resume.
- **Compression**: each stage's fallback (LLM summary fail → truncate fail → static error), and `payload_too_large` vs `context_overflow` are handled distinctly.
- **Security**: dangerous-command normalization bypasses (`rm--rf`, `./rm`, full-width, NFKC variants), env stripping in sandbox/MCP, and `_sanitize_error()` on every error-return path.
- **Async timing**: when verifying chunked `asyncio.sleep` totals, assert the aggregate delay (see `learned_skill_experience`).
- God-class guard: a file exceeding 1500 lines should trip a review/lint warning.

---

## Code Review Checklist

When reviewing backend changes, verify:

- [ ] No bare `except Exception: retry` — errors are classified before handling.
- [ ] Every callback has its own `try/except`; none can crash the main loop.
- [ ] No `asyncio.run()` in long-lived code paths; async goes through the bridge.
- [ ] Iteration budget is the shared lock-protected counter, not a passed argument.
- [ ] New tools self-register at module level; args are coerced centrally before dispatch.
- [ ] Tool results respect the three-tier budget (spill + preview for large output).
- [ ] Parallelism decisions compare `Path.parts`, not string prefixes; default serial when unsure.
- [ ] System prompt is slot-assembled, cached, byte-stable, and reloaded (not rebuilt) on resume.
- [ ] All externally-sourced prompt content is scanned (block context files, warn MCP descriptions).
- [ ] Context compression pre-fires at 70–80%, has a fallback chain, and tags summaries with the disclaimer prefix.
- [ ] SQLite uses WAL + checkpoint; migrations are forward-only; writes are append-only.
- [ ] No plaintext credentials in config; credential access is centralized; effective config is traceable.
- [ ] Provider differences live in adapters, not the main loop; responses normalized to `SimpleNamespace`.
- [ ] Cross-process writes use OCC, not global locks; IPC payloads are primitive types with ids + timeouts.
- [ ] MCP/sandbox execution strips credential env vars; tool names validated; errors sanitized.
- [ ] Dangerous commands are normalized (ANSI/null/NFKC) before pattern matching (≥38 patterns) — **or**, on the secbot exec-disabled path, the binary whitelist + argv list + forbidden-char check is enforced instead.
- [ ] No credential can reach model context — `_sanitize_error()` applied on every error path.
- [ ] Sub-agents share a structured blackboard, not the full conversation history.
- [ ] No file exceeds 1500 lines; no scattered `if provider == ...`; no manual cache invalidation by hand.

---

**Language**: All documentation should be written in **English**.
