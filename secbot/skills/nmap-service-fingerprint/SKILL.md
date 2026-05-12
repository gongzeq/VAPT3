---
name: nmap-service-fingerprint
display_name: Nmap Service Fingerprint
version: 1.0.0
risk_level: medium
category: port_scan
external_binary: nmap
binary_min_version: "7.80"
network_egress: required
expected_runtime_sec: 300
summary_size_hint: medium
---

Run `nmap -sV -p <ports>` against one or more hosts to identify running
services, product names, and version banners. Use this after a port scan
has narrowed the list of open ports; for pure port discovery prefer
`nmap-port-scan`.
