---
name: qscan-port-scan
display_name: Qscan Port Scan
version: 2.0.0
risk_level: medium
category: port_scan
external_binary: qscan
network_egress: required
expected_runtime_sec: 600
summary_size_hint: medium
---

Run qscan against a single host:

- **With ports**: `qscan -t <target> -p <ports> -o qscan-port-scan.log`
- **Without ports**: `qscan -t <target> --top 1000 -o qscan-port-scan.log`

Reports open ports per host with protocol and fingerprint.
