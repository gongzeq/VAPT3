---
name: vuln-detec-manual
display_name: Manual Vuln Verification
version: 1.0.0
risk_level: low
category: vulnerability
external_binary: curl
network_egress: required
expected_runtime_sec: 300
summary_size_hint: small
---

Lightweight manual vulnerability verification skill placeholder.
The vuln_detec expert agent performs actual curl-based probes via the
ExecTool; this skill exists to satisfy the scoped_skills registry contract
and declares the curl binary dependency.
