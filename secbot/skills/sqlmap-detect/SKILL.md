---
name: sqlmap-detect
display_name: SQLMap Detect
version: 1.0.0
risk_level: medium
category: vuln_scan
external_binary: sqlmap
network_egress: required
expected_runtime_sec: 600
summary_size_hint: medium
---

Probe a target URL with `sqlmap --batch --risk=1 --level=1` to detect SQL
injection vulnerabilities. Stops at detection — no DB fingerprinting or
data extraction (use `sqlmap-dump` for that, with explicit authorisation).
Medium risk: non-destructive but does send crafted traffic.
