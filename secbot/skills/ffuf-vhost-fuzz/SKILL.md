---
name: ffuf-vhost-fuzz
display_name: FFUF Virtual-host Fuzz
version: 1.0.0
risk_level: medium
category: asset_discovery
external_binary: ffuf
network_egress: required
expected_runtime_sec: 300
summary_size_hint: medium
---

Fuzz the `Host:` header of a target URL with `ffuf` to discover virtual
hosts backed by the same IP. Supply a list of candidate hostnames; `ffuf`
replaces `FUZZ` in the `-H "Host: FUZZ.example.com"` header and filters
responses whose size differs from the baseline.
