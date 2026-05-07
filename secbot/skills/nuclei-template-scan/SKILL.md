---
name: nuclei-template-scan
display_name: Nuclei Template Scan
version: 1.0.0
risk_level: high
category: vuln_scan
external_binary: nuclei
network_egress: required
expected_runtime_sec: 600
summary_size_hint: large
---

Run a curated set of Nuclei templates (CVE / misconfig / exposure)
against the target list. High-risk templates (RCE, auth bypass) are
filtered to `severity in {medium,high,critical}` only. Findings are
emitted as structured CMDB writes.
