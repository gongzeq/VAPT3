---
name: report-docx
display_name: DOCX Report
version: 1.0.0
risk_level: low
category: report
external_binary: null
network_egress: none
expected_runtime_sec: 20
summary_size_hint: small
---

Render the scan report as a DOCX file via python-docx. Reads only from
the local CMDB; no network egress, no subprocess.
