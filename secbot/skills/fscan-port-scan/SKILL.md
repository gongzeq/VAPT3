---
name: fscan-port-scan
display_name: fscan Port Scan
version: 1.0.0
risk_level: medium
category: port_scan
external_binary: fscan
network_egress: required
expected_runtime_sec: 240
summary_size_hint: medium
---

Multi-host port + service scan via fscan; faster than nmap on /16+
ranges thanks to built-in concurrency.
