# Tool Invocation Safety

> Hard contract for any code path that shells out to an external binary (nmap, fscan, nuclei, hydra, httpx, ffuf, katana, sqlmap, …).
> Implementation: `secbot/skills/_shared/sandbox.py` is the **only** legal entry point.
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
from secbot.skills._shared.sandbox import run_command

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
    "nmap", "fscan", "nuclei", "hydra", "httpx", "ffuf",
    "katana", "sqlmap", "ghauri",
    "python3", "git",       # internal helper use only
})
```

To add a binary:

1. Open a spec PR amending this list AND the `secbot/skills/_shared/sandbox.py` constant.
2. Document the binary's `--version` flag, the minimum version, and its install instructions in the same PR.
3. The `external_binary` field in the corresponding [SKILL.md](./skill-contract.md#2-skillmd-front-matter-schema) MUST match exactly.

Katana is installed with `go install github.com/projectdiscovery/katana/cmd/katana@latest`;
verify availability with `katana -version`. The `katana-crawl-web` skill declares
`external_binary: katana` and a minimum version of `1.0.0`.

---

## Scenario: Katana Crawl Skill

### 1. Scope / Trigger

- Trigger: `katana-crawl-web` is an external scanner skill and therefore changes the sandbox whitelist, skill schema contract, and orchestrator stage ordering.
- Scope: crawl only authorized HTTP/HTTPS web targets and return bounded crawl candidates; do not run exploit payloads.

### 2. Signatures

- Skill directory: `secbot/skills/katana-crawl-web/`.
- Handler signature: `async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult`.
- Sandbox command: `run_command(binary="katana", args=["-u", target, "-d", str(depth), "-jc", "-ef", "css,png,jpg,gif,svg,woff,ttf,js", "-aff", "-o", raw_urls_path, "-silent", "-no-color"], network=NetworkPolicy.REQUIRED, capture="file", raw_log_path=ctx.raw_log_dir / "katana-crawl-web.log")`.

### 3. Contracts

- Request fields:
  - `target` string, required, must be an HTTP/HTTPS URL without credentials or shell metacharacters.
  - `depth` integer, optional, `1..10`, default `5`.
  - `max_candidates` integer, optional, `1..500`, default `100`.
  - `timeout_sec` integer, optional, `30..7200`, default `600`.
- Response fields:
  - `total_urls`, `deduped_urls`, `filtered_urls`, `candidate_count` are non-negative integers.
  - `candidates[]` entries include `url`, `priority`, `parameters[]`, `guessed_vulnerabilities[]`, `reasons[]`, and `recommended_action`.
  - `parameters[].risk` is one of `critical`, `high`, `neutral`, or `skipped`.
  - `raw_urls_path` points to `ctx.scan_dir / "katana" / "katana_urls.txt"`; raw subprocess output stays in `raw_log_path`.
- Environment/config:
  - Optional binary override is `tools.skillBinaries.katana`; otherwise the handler resolves `katana` from `PATH`.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|-----------|-------------------|
| `target` is not HTTP/HTTPS, has credentials, has invalid port, or contains forbidden characters | Raise `InvalidSkillArg` before calling the sandbox |
| `depth`, `max_candidates`, or `timeout_sec` is outside bounds | Raise `InvalidSkillArg` before calling the sandbox |
| Katana is not configured and not on `PATH` | Raise `SkillBinaryMissing` |
| Katana times out | Return `SkillResult(summary={"error": "timeout"}, raw_log_path=...)` |
| Cancellation token fires | Return `SkillResult(summary={"cancelled": true}, raw_log_path=...)` |
| Katana emits off-scope, malformed, duplicate, static-asset, or static dictionary URLs | Filter them before building `candidates` |

### 5. Good/Base/Bad Cases

- Good: `https://example.com/export?file=report.pdf` becomes a critical candidate with path traversal/access-control hypotheses.
- Base: `https://example.com/admin/login` becomes a medium candidate even without query parameters.
- Bad: `https://evil.example.net/api?cmd=id`, `https://example.com/app.js`, and `https://example.com/region-list?lang=zh` are filtered from candidates.

### 6. Tests Required

- Agent registry test asserts `crawl_web` loads and requires `katana`.
- Skill metadata test asserts `katana-crawl-web` is discovered and validates.
- Sandbox test asserts `katana` is in `BINARY_WHITELIST`.
- Handler tests mock Katana and assert argv construction, target validation, deduplication, static/noisy filtering, off-scope filtering, parameter risk classification, JSON/XML hints, schema-valid summary, timeout handling, and missing-binary handling.
- Orchestrator prompt test asserts `crawl_web` appears in the hard-rule stage order before `vuln_scan`.

### 7. Wrong vs Correct

#### Wrong

```python
subprocess.run(f"katana -u {target} -d 5 -jc -o ./katana_urls.txt 2>/dev/null", shell=True)
```

#### Correct

```python
result = await run_command(
    binary="katana",
    args=["-u", target, "-d", "5", "-jc", "-ef", "css,png,jpg,gif,svg,woff,ttf,js", "-aff", "-o", str(urls_file), "-silent", "-no-color"],
    timeout_sec=600,
    network=NetworkPolicy.REQUIRED,
    capture="file",
    raw_log_path=raw_log,
    cancel_token=ctx.cancel_token,
)
```

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
