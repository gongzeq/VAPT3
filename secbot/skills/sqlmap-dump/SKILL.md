---
name: sqlmap-dump
display_name: SQLMap Dump
version: 1.0.0
risk_level: critical
category: vuln_scan
external_binary: sqlmap
network_egress: required
expected_runtime_sec: 1200
summary_size_hint: medium
---

**Critical-risk**: Actually extract data from a confirmed-vulnerable
database via `sqlmap --batch --dbs` / `--tables` / `--columns` / `--dump`.
Gated by `HighRiskGate.guard` — the LLM must have explicit user
authorisation for this target and a prior `sqlmap-detect` confirming
injection. Caller chooses the scope (`dbs` → `tables` → `columns` → `dump`)
via the `action` parameter; each step dumps into `<scan_dir>/sqlmap/` and
records findings.
