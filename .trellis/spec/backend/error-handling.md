# Error Handling

> How errors are handled in the secbot backend.
> This document is the layer-specific companion to [quality-guidelines.md](./quality-guidelines.md):
> where QG states the principle, this file states the concrete contract.

---

## Overview

secbot handles errors at three distinct layers, each with its own contract:

| Layer | Origin | Contract |
|-------|--------|----------|
| Model call | LLM provider / network (`secbot/agent/loop.py`, `secbot/providers/`) | **Classify into one of the canonical categories below**, then decide retry vs surface. Never blind-retry. |
| Skill / tool | Sandbox + skill handlers (`secbot/skills/`) | Return a **structured** `summary={"error": ...}`; raise only typed, loop-handled exceptions. |
| API / transport | aiohttp + WS (`secbot/api/`, `secbot/channels/`) | Map to a stable HTTP status + JSON body; never leak a traceback or credential. |

Guiding rule (QG priority #2): **classify before you react.** A precise classification beats a generic `except Exception: retry`.

---

## Error Types

### 1. Model-call categories (classify every provider error)

The classifier MUST resolve every provider/network failure into exactly one of these ≥11 categories before the loop reacts:

| Category | Meaning | Default reaction |
|----------|---------|------------------|
| `auth` | Transient auth failure (clock skew, retryable 401) | Retry with backoff, then surface |
| `auth_permanent` | Invalid / revoked key | Surface immediately — waiting won't help |
| `billing` | Quota / payment (402) | Surface; do NOT retry as `rate_limit` |
| `rate_limit` | 429 throttling | Backoff + retry |
| `overloaded` | Provider capacity | Backoff + retry |
| `server_error` | 5xx | Bounded backoff + retry |
| `timeout` | No response in window | Retry once, then surface |
| `context_overflow` | Prompt exceeds window | **Compress, not retry** — see [context-trimming.md](./context-trimming.md) |
| `payload_too_large` | Single request too big | Trim / spill (distinct from `context_overflow`) |
| `model_not_found` | Bad model id | Surface; fall back per routing |
| `format_error` | Malformed response / JSON | Re-ask once, then surface |
| `unknown` | Unmapped | Surface with sanitized detail; never silent-retry forever |

> The `auth`-vs-`auth_permanent` and `rate_limit` (429)-vs-`billing` (402) splits are
> the highest-value distinctions — getting them wrong causes either infinite retries
> or a key the operator cannot diagnose. They are the primary classifier test target.

### 2. Skill / tool errors

| Failure | Handler MUST |
|---------|--------------|
| Subprocess non-zero exit / scanner failure | Return `SkillResult(summary={"error": "..."}, findings=[], raw_log_path=...)`; do NOT raise. |
| External binary missing | Raise `SkillBinaryMissing` — a typed, loop-handled exception converted to a structured tool error. |
| Timeout | `summary={"error": "timeout"}` + `raw_log_path`. |
| Cancellation (`ctx.cancel_token`) | Terminate subprocess; `summary={"cancelled": true}`. |
| High-risk denied | `summary={"user_denied": true}`. |

This is the QG nuance: handlers never raise an *unclassified* exception into the
model context, but typed exceptions the loop knows how to convert ARE allowed.
See [skill-contract.md §5](./skill-contract.md#5-error-handling).

### 3. API / transport errors

See [API Error Responses](#api-error-responses) below.

---

## Error Handling Patterns

- **Classify, then react.** All provider errors funnel through the classifier; no `except Exception: time.sleep(); retry()` anywhere in the loop.
- **Each callback owns its `try/except`.** `stream_callback` / `tool_progress_callback` / `step_callback` must not let one failure kill the loop or the other callbacks.
- **Retry uses jittered exponential backoff**: `min(base*2^(n-1), max) + random*0.5*delay` (`base=5s`, `max=120s`), only for the retryable categories above.
- **Sanitize before returning to the model or client.** Every error string that can reach model context or an API response passes `_sanitize_error()`: `sk-...` / `Bearer ...` → `[REDACTED]`, on EVERY error-return path.
- **The main loop never dies.** Subsystems may jitter; classify and continue or surface — never raise an unclassified traceback out of the loop.
- **Compress, don't crash, on `context_overflow`.** Raising `ContextOverflow` is forbidden; pre-compress at 70–80% of the window.

---

## API Error Responses

HTTP / WS handlers map errors to stable, non-leaking responses. Established contracts:

| Condition | Status | Body |
|-----------|--------|------|
| Missing required query param (e.g. `chat_id`) | 400 | `{"error": "chat_id required"}` |
| Invalid / missing bearer token | 401 | global auth middleware |
| Unknown but valid-shaped resource (empty chat) | 200 | empty collection, e.g. `{"entries": []}` — see [blackboard-registry.md §3.1](./blackboard-registry.md#31-request-validation) |
| Config / source parse error (e.g. `prompts.yaml`) | 200 | last-known-good cached value, never 500 — see [prompts-config.md §5.2](./prompts-config.md#52-error-modes) |
| Unexpected server fault | 500 | sanitized `{"error": "internal"}` — never a traceback, never a credential |

Rules:

- Never return a raw traceback to a client.
- Never return a 500 for an expected, recoverable condition (missing config, empty resource).
- Error bodies are JSON; the embedded WebUI must receive JSON (not the SPA `index.html`) on `/api/*` — see [blackboard-registry.md §3.5](./blackboard-registry.md#35-embedded-webui-http-mirror).

---

## Common Mistakes

| Anti-pattern | Why it's wrong |
|--------------|----------------|
| `except Exception as e: time.sleep(5); retry()` | Treats `auth_permanent` like `server_error` → infinite retry. Classify first. |
| Raising an unclassified exception out of the loop | User gets a traceback with no idea whether to rotate a key or wait. |
| One shared `try/except` around all callbacks | One failing callback silently kills the rest. |
| Returning raw scanner stderr in `summary` | May leak secrets and blows the context budget; spill to `raw_log_path`. |
| Raising `ContextOverflow` instead of compressing | Loses the turn; compress pre-emptively. |
| `500` + traceback for a missing config file | Expected condition; serve a safe default. |
| Leaking `sk-...` / `Bearer ...` into model or client | Must pass `_sanitize_error()` on every path. |

---

## Test Requirements

- Error classifier covers all categories, especially `auth` vs `auth_permanent` and `rate_limit` (429) vs `billing` (402).
- `_sanitize_error()` is applied on every error-return path (model + client).
- Each callback's `try/except` isolation (a throwing callback does not kill the loop).
- Skill error matrix: non-zero exit → structured `summary.error`; missing binary → `SkillBinaryMissing`; cancel / timeout paths.
- API: 400 on missing param, 401 on bad token, 200 empty on unknown resource, no 500 for recoverable config errors.

---

**Language**: All documentation should be written in **English**.
