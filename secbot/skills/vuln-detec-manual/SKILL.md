---
name: vuln-detec-manual
display_name: Manual Vuln Verification
version: 2.0.0
risk_level: medium
category: vulnerability
external_binary: null
network_egress: required
expected_runtime_sec: 300
summary_size_hint: medium
---

Automated lightweight vulnerability verification against Web endpoints.

Performs 8 systematic read-only probes per target URL:

1. **BASELINE** — original request to establish response norm.
2. **Special Character** — inject `test'"<>(){}` and compare response size.
3. **XSS Reflection** — inject a unique marker and check for unescaped
   reflection in the response.
4. **SQL Error Probe** — append a single quote and grep for SQL error keywords.
5. **Time-based SQLi** — inject `AND SLEEP(3)` and measure response delay.
6. **Numeric Arithmetic** — replace numeric params with arithmetic expressions
   (e.g. `2-1`) and check if they evaluate.
7. **Template Injection** — inject `${7*7}` / `{{7*7}}` and look for `49`.
8. **Command Injection** — append harmless shell metacharacters (`;id`, `|id`,
   `$(id)`) and check for `id` command output in the response.

Returns structured `findings` with `confidence` ratings (low / medium / high).
High-confidence findings are automatically translated into `cmdb_writes`
(`vulnerabilities` table) so downstream consumers (report, dashboard) see
live data without waiting for a full `vuln_scan` pass.

Targets are supplied as a list so a single skill call can sweep multiple
endpoints discovered by `crawl_web` or `port_scan` in one batch.
