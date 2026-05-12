---
name: ffuf-dir-fuzz
display_name: FFUF Directory Fuzz
version: 1.0.0
risk_level: medium
category: asset_discovery
external_binary: ffuf
network_egress: required
expected_runtime_sec: 300
summary_size_hint: medium
---

Fuzz for hidden directories / files on a target URL using
[ffuf](https://github.com/ffuf/ffuf). Replaces the `FUZZ` marker in the
target URL with every entry from the bundled wordlist. Medium risk: this
does generate substantial traffic against the target — only use on in-scope
systems.
