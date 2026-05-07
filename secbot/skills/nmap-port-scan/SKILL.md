---
name: nmap-port-scan
display_name: Nmap Port Scan
version: 1.0.0
risk_level: medium
category: port_scan
external_binary: nmap
binary_min_version: "7.80"
network_egress: required
expected_runtime_sec: 180
summary_size_hint: medium
---

Run `nmap -sS -p <ports>` against one or more hosts; report open
TCP ports per host.
