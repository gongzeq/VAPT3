# Tool Invocation Safety

> Hard contract for any code path that shells out to an external binary (nmap, fscan, nuclei, hydra, httpx, ffuf, sqlmap, weasyprint, …).
> Implementation: `secbot/agent/tools/sandbox.py` is the **only** legal entry point.
> **`exec` tool is disabled by default** (PRD `05-11-security-tools-as-tools` §D4) — LLMs reach security binaries exclusively via SkillTool adapters.

---

## 0. LLM Reach-Out Surface

> Added 2026-05-13. Origin: PRD `05-11-security-tools-as-tools` §D4 / §Acceptance Criteria.

The LLM's tool surface is **bounded** by the following invariants:

1. `ExecToolConfig.enable` defaults to `False`. The free-form shell `exec` tool is **not exposed** to the LLM in any standard orchestration config. Re-enabling it is an explicit operator decision and MUST be recorded in config, not derived from defaults.
2. Every external binary call reaches the LLM as a `SkillTool` — one skill = one tool, schema-validated, sandbox-backed. No skill MAY shell out outside `sandbox.run_command`.
3. Specialist sub-loops (`SubagentManager._run_subagent(spec)`) register **only** `spec.scoped_skills` from the agent YAML. The orchestrator loop sees `spawn / blackboard_read / blackboard_write / request_approval` — NOT skill tools directly.
4. Skills with `risk_level: critical` in SKILL.md front-matter MUST block on `ctx.confirm(...)` before execution. In non-interactive channels (cron, API, tests) `ctx.confirm` returns `False` → skill aborts with a denial tool-error; it never hangs waiting.

Consequences:
- A regression that defaults `ExecToolConfig.enable` back to `True` is a **P0 security regression**.
- Adding a new skill that bypasses `sandbox.run_command` (raw `subprocess.*`, `os.system`, `shell=True`) is **review-blocking** (same rule as §1 below).
- Re-introducing a "raw shell" tool under a different name (e.g. `bash`, `run_cmd`) requires amending this §0 first.

---

## 1. Single Entry Point

All `subprocess` calls inside skills MUST go through:

```python
from secbot.agent.tools.sandbox import run_command

result = await run_command(
    binary="nmap",                       # MUST be in BINARY_WHITELIST
    args=["-sn", "-PE", target_cidr],   # list of strings; never a single string
    timeout_sec=120,                     # required
    cwd=ctx.scan_dir,                    # optional; default = temp dir
    network=NetworkPolicy.REQUIRED,      # required; from skill's network_egress
    capture="file",                      # one of: file | memory_capped(MB) | discard
)
```

Direct use of `subprocess.run`, `subprocess.Popen`, `os.system`, `asyncio.create_subprocess_*`, or `shell=True` ANYWHERE in `secbot/skills/**` is **review-blocking**.

---

## 2. Binary Whitelist

`sandbox.run_command` rejects any `binary` not in:

```python
BINARY_WHITELIST = frozenset({
    "nmap", "fscan", "nuclei", "hydra", "masscan",
    "weasyprint",          # PR10 PDF rendering
    "python3", "git",       # internal helper use only
})
```

To add a binary:

1. Open a spec PR amending this list AND `secbot/agent/tools/sandbox.py` constant.
2. Document the binary's `--version` flag, the minimum version, and its install instructions in the same PR.
3. The `external_binary` field in the corresponding [SKILL.md](./skill-contract.md#2-skillmd-front-matter-schema) MUST match exactly.

---

## 3. Argument Construction

### 3.1 Always a list

```python
# CORRECT
args = ["-sV", "-p", str(port_range), target]

# WRONG — review-blocking
args = f"-sV -p {port_range} {target}"
```

### 3.2 Validation order

For every skill that builds args from user-influenced data:

1. Args go through the skill's `input.schema.json` validator (loader-level).
2. Each value that becomes an argv element is checked against a per-field allow regex defined in the skill module:

   ```python
   TARGET_PATTERN = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?$"
                               r"|^[a-z0-9.-]+\.[a-z]{2,}$")

   if not TARGET_PATTERN.match(args["target"]):
       raise InvalidSkillArg("target")
   ```
3. `shlex.quote` is **NOT** used as a safety net — by then it's already too late. Lists + validation are the only acceptable defence.

### 3.3 Forbidden chars in any argv element

Across all skills, the following characters in user-derived argv elements are unconditionally rejected, even if a regex would otherwise allow them:

```
; & | $ ` < > \n \r \\ '"'
```

`sandbox.run_command` re-checks each element and raises `InvalidArgvCharacter` before exec.

---

## 4. Network Policy

```python
class NetworkPolicy(StrEnum):
    REQUIRED = "required"   # external scans (nmap, fscan, nuclei)
    OPTIONAL = "optional"   # report renderer that may fetch fonts; warn but allow
    NONE     = "none"       # offline transforms only; sandbox MUST drop egress
```

The policy comes from the SKILL's `network_egress` field. `NONE` engages `secbot/security/network.py` to block external sockets in the subprocess. PR review rejects any skill where the declared policy doesn't match observed behaviour (covered by `tests/security/test_network_policy.py`).

---

## 5. Output Capture

| Mode | Use when | Behaviour |
|------|----------|-----------|
| `file` | Default for scanners; output is large, structured, and persisted | Streams stdout/stderr to `~/.secbot/scans/<scan_id>/raw/<skill>.log`; returns the path. |
| `memory_capped(MB=2)` | Helper utilities with bounded output (e.g. version checks) | Buffers in memory up to MB; OverflowError if exceeded. |
| `discard` | Fire-and-forget side-effects (rare) | Captures only exit code. |

`file` capture is mandatory for every skill that runs an external scanner. The path returned populates `SkillResult.raw_log_path`.

---

## 6. Timeouts and Cancellation

- `timeout_sec` is required; defaults are forbidden. The skill MUST justify the value in `expected_runtime_sec` of its SKILL.md.
- On timeout, the sandbox sends SIGTERM, waits 5s, then SIGKILL. The skill receives `SkillTimeout` and MUST surface it as `summary={"error": "timeout"}`.
- The sandbox listens to `ctx.cancel_token`. When set, it terminates the subprocess and raises `SkillCancelled`.

---

## 7. Test Requirements

- `tests/security/test_sandbox_whitelist.py`: verify each non-whitelisted binary raises `BinaryNotAllowed`.
- `tests/security/test_argv_injection.py`: parametrised over the forbidden character set; each MUST raise `InvalidArgvCharacter`.
- `tests/security/test_network_policy.py`: `NONE` skill cannot open external sockets (use `secbot/security/network.py` test harness).
- New skill PRs MUST include a fuzz-style negative test for their `args` regex.
