---
name: httpx-probe
display_name: HTTPX Probe
version: 1.0.0
risk_level: low
category: asset_discovery
external_binary: httpx
network_egress: required
expected_runtime_sec: 120
summary_size_hint: small
---

Probe a batch of hosts / URLs with
[projectdiscovery/httpx](https://github.com/projectdiscovery/httpx) to capture
HTTP status, title, tech stack and TLS fingerprint. Safe, read-only — use it
to build the web-service inventory before running vuln scans.
