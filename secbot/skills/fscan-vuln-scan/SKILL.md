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
