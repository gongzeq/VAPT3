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

1. List the top-level categories first:
   ```
   ls secbot/resource/poc/
   ```
2. Drill into the folders that match the target profile
   (product, framework, CVE year, ...), e.g.
   `ls secbot/resource/poc/cve/2023/`.
3. Pass only the matching entries via the `templates` argument as relative
   paths (file OR subdirectory) under `secbot/resource/poc/`, for example
   `["cve/2023/CVE-2023-1234.yaml", "exposure/nginx"]`.

> **Note:** Do NOT use `glob("secbot/resource/poc/**/*.yaml")` —
> relative-path globs are not resolved correctly by the glob tool.
> Always drill down from the top-level listing.

Omit `templates` entirely when only built-in nuclei templates should run.
