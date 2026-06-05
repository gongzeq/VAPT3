---
name: fscan-vuln-scan
display_name: fscan Vulnerability Scan
version: 1.0.0
risk_level: high
category: vuln_scan
external_binary: fscan
network_egress: required
expected_runtime_sec: 600
summary_size_hint: large
---

Run fscan with built-in POC checks (`-pocpath`/default) against the
target list. Emits one finding per detected vulnerability and writes
results into the CMDB `vulnerabilities` table.

By default brute-force is disabled (`-nobr`). It is turned on only when
`user_dict` and/or `pass_dict` are supplied.

## Wordlist workflow (secbot/resource/fuzzDicts/)

Dictionary files live under `secbot/resource/fuzzDicts/` but are **never**
auto-loaded. Before calling this skill with `user_dict` / `pass_dict`:

1. List the sub-categories first:
   ```
   ls secbot/resource/fuzzDicts/
   ```
   This reveals category folders such as `passwordDict/`, `userNameDict/`,
   `ServiceWeakPass/`, `directoryDicts/`, etc.
2. Drill into the folder that matches the target service
   (e.g. `ls secbot/resource/fuzzDicts/passwordDict/`).
3. Pick exactly ONE filename per slot (`user_dict` / `pass_dict`).
4. Pass those filenames as relative paths under `secbot/resource/fuzzDicts/`
   (e.g. `passwordDict/top1000.txt`, `userNameDict/top500.txt`).

> **Note:** Do NOT use `glob("secbot/resource/fuzzDicts/**/*.txt")` —
> relative-path globs are not resolved correctly by the glob tool.
> Always drill down from the top-level listing.
