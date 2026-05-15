---
name: run-python
display_name: Run Custom Python
version: 1.0.0
risk_level: critical
category: adhoc
external_binary: python3
network_egress: required
expected_runtime_sec: 60
summary_size_hint: medium
---

Execute a short, one-shot Python 3 script that you write yourself, for tasks where no pre-built skill fits (ad-hoc data transforms, protocol assembly, CVE PoC debugging, JSON/CSV massaging, etc.). The code runs in isolated interpreter mode (`python3 -I -B`) under the secbot sandbox, inside the current scan workspace, with the declared timeout. Only stdout/stderr (merged) is returned to you, truncated to ~10 KB — if you need to persist findings, write them via `write_file` / `write_blackboard` tools. The script source is archived under `<scan_dir>/run-python/<timestamp>.py` for audit.

## When to use

- A one-line transformation or parsing task that existing skills don't cover.
- Quickly wiring together a custom HTTP / TCP probe to debug a target.
- Reshaping a previous skill's output before feeding it to another step.

## When NOT to use

- Anything an existing skill already handles (nmap, sqlmap, fscan, nuclei, …). Prefer the dedicated skill — it has bespoke parsers, CMDB writes, and tuned args.
- Long-running or interactive sessions. This is one-shot, no persistent kernel, no `pip install`.
- Storing large artefacts. Keep output small; use `write_file` for bulk data.

## Arguments

- `code` (string, required, ≤ 32 KB): full Python source to execute. Receives no arguments and no stdin.
- `timeout_sec` (integer, optional, 1–600, default 60): kill the interpreter after this many wall-clock seconds.

## Return contract

```json
{
  "exit_code": 0,
  "stdout_tail": "...last ~10KB of merged stdout+stderr...",
  "bytes": 1234,
  "truncated": false,
  "script_path": "/abs/path/run-python/1731500000000.py",
  "elapsed_sec": 0.42
}
```

- `exit_code != 0` surfaces through `error` in the summary — the caller decides whether to retry or give up.
- Timeout returns `summary={"error": "timeout", ...}`; cancellation returns `summary={"cancelled": true, ...}`.

## Security notes

- **No shell.** The script is started as `python3 -I -B <file>`; there is no intermediate shell interpretation.
- **Network egress is not a sandbox boundary here.** Python can open arbitrary sockets; internal-network isolation must be enforced at the host / container network layer, not by this skill.
- **High-risk.** Every call requires user confirmation on first use within a conversation (the HighRiskGate remembers approvals per session).
- **Workspace-bound.** The script's `cwd` / raw log dir stay under the scan workspace; you cannot directly clobber paths outside it, but Python still has full filesystem access as the host user — do not write outside the workspace.
