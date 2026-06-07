---
name: report-html
display_name: HTML Report
version: 2.0.0
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

Layout follows the `123.html` design language: a neutral slate palette,
card-based sections, mini-labels and rounded badges. The summary adds KPI
cards (资产 / 服务 / 漏洞发现 / 严重·高危) and a pure-CSS severity
distribution bar. All styling is inlined — no CDN, no JS dependency beyond
the print button — so the file opens offline and renders identically through
WeasyPrint PDF export.
