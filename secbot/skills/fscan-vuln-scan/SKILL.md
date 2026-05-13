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

1. Use the `glob` tool to list what exists, e.g.
   `glob("secbot/resource/fuzzDicts/**/*.txt")`.
2. Pick exactly ONE filename per slot that fits the target profile
   (service type, known product, etc.).
3. Pass those filenames via `user_dict` / `pass_dict` as relative paths
   under `secbot/resource/fuzzDicts/`.
