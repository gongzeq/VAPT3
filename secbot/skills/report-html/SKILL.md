---
name: report-html
display_name: HTML Report
version: 1.0.0
risk_level: low
category: report
external_binary: null
network_egress: none
expected_runtime_sec: 10
summary_size_hint: small
---

Render the canonical HTML report for a completed scan. Reads only from the
local CMDB; no network egress, no subprocess. Call this after every scan
stage to freeze the current findings into a single shareable `report.html`
file.
