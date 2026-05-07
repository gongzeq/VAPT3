---
name: nmap-host-discovery
display_name: Nmap Host Discovery
version: 1.0.0
risk_level: medium
category: asset_discovery
external_binary: nmap
binary_min_version: "7.80"
network_egress: required
expected_runtime_sec: 60
summary_size_hint: small
---

# Nmap Host Discovery

Discover live hosts under a CIDR / IP / domain using `nmap -sn` (ping
scan: ICMP echo, TCP SYN to 80/443, ICMP timestamp, ARP on local link).

## Args

- `target` (string, required): CIDR, single IP or hostname.
- `rate` (string, optional, default `normal`): `slow|normal|fast` →
  `-T2|-T3|-T4`.

## Summary shape

```json
{
  "hosts_up": ["10.0.0.1", "10.0.0.5"],
  "elapsed_sec": 12.4
}
```

Raw nmap output (greppable + XML) is on disk; the LLM only sees the
host list above.
