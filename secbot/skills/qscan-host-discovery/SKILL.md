---
name: qscan-host-discovery
display_name: Qscan Host Discovery
version: 1.1.0
risk_level: medium
category: asset_discovery
external_binary: qscan
network_egress: required
expected_runtime_sec: 120
summary_size_hint: small
---

# Qscan Host Discovery

Discover live hosts under a CIDR / IP / domain using `qscan -t <target>`.

## Args

- `target` (string, required): CIDR, single IP or hostname.

## Summary shape

```json
{
  "hosts_up": ["10.0.0.1", "10.0.0.5"],
  "elapsed_sec": 12.4
}
```

Raw qscan output is on disk; the LLM only sees the host list above.
