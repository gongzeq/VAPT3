---
name: report-pdf
display_name: PDF Report
version: 1.0.0
risk_level: low
category: report
external_binary: weasyprint
network_egress: none
expected_runtime_sec: 30
summary_size_hint: small
---

Render the scan report as a PDF file via WeasyPrint. Reads only from the
local CMDB; no network egress, no subprocess. Requires the system
libraries cairo/pango (provisioned by `secbot doctor`).
