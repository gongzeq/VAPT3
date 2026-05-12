---
name: hydra-bruteforce
display_name: Hydra Credential Brute-force
version: 1.0.0
risk_level: critical
category: weak_password
external_binary: hydra
network_egress: required
expected_runtime_sec: 900
summary_size_hint: medium
---

Run `hydra` against a single target/service with a bounded username and
password list to enumerate weak credentials. **Critical risk**: this skill
will be gated by `HighRiskGate.guard` — the LLM must have explicit user
authorisation for the target service before calling it.

Supports the protocols secbot ships out of the box: `ssh`, `ftp`, `telnet`,
`rdp`, `mysql`, `postgres`, `mssql`, `smb`, `redis`, `http-get`, `http-post-form`.
