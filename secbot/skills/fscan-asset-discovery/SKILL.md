---
name: fscan-asset-discovery
display_name: fscan Asset Discovery
version: 1.0.0
risk_level: medium
category: asset_discovery
external_binary: fscan
network_egress: required
expected_runtime_sec: 120
summary_size_hint: small
---

Run `fscan -nopoc -nobr` for fast multi-protocol asset discovery
(IcmpScan + alive host listing). Suitable for /16-/24 subnets.
