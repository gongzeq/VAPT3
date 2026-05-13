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

## Custom POC workflow (secbot/resource/poc/)

Custom POC YAML files live under `secbot/resource/poc/` but are **never**
auto-loaded — that directory can hold hundreds of unrelated templates and
blindly passing it to nuclei wastes the scan budget.

Before calling this skill, the LLM MUST:

1. Use the `glob` tool to inspect what exists, e.g.
   `glob("secbot/resource/poc/**/*.yaml")`.
2. Pick only the entries that actually match the target profile
   (product, framework, CVE year, ...).
3. Pass those entries via the `templates` argument as relative paths
   (file OR subdirectory) under `secbot/resource/poc/`, for example
   `["cve/2023/CVE-2023-1234.yaml", "exposure/nginx"]`.

Omit `templates` entirely when only built-in nuclei templates should run.
