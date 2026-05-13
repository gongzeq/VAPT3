---
name: ffuf-vhost-fuzz
display_name: FFUF Virtual-host Fuzz
version: 2.0.0
risk_level: medium
category: asset_discovery
external_binary: ffuf
network_egress: required
expected_runtime_sec: 300
summary_size_hint: medium
---

# FFUF virtual-host fuzzing

Discover virtual hosts backed by the same IP / base URL by fuzzing the
`Host:` header. [ffuf](https://github.com/ffuf/ffuf) rewrites the
`FUZZ` marker inside a host template (e.g. `FUZZ.example.com`) for every
candidate in the wordlist; responses whose size / status differ from the
auto-calibrated baseline are flagged as live vhosts.

## Two invocation modes

1. **url + host_template** — shortest path. The skill renders
   `-H "Host: <host_template>"` and points ffuf at `url`:

   ```yaml
   url:           "https://203.0.113.10"
   host_template: "FUZZ.example.com"
   wordlist:      ["www", "api", "dev", "staging", "admin", ...]
   ```

2. **raw_request** — use when the baseline URL itself needs auth /
   custom headers. Capture the request from Burp / DevTools, set the
   `Host` header to your template (with `FUZZ`) and pass the whole
   thing as `raw_request`. The handler invokes `ffuf --request`.

   ```yaml
   raw_request: |
     GET / HTTP/1.1
     Host: FUZZ.example.com
     Authorization: Bearer eyJhbGciOi…
     Accept: text/html
   wordlist: ["www", "api", ...]
   ```

## Auto-calibration removes the 404/placeholder baseline

`-ac` is on by default. When the default virtual host returns a fixed
placeholder page, ffuf learns the baseline automatically and only
reports responses that deviate. If you know the exact baseline size,
supply `filter_sizes` (e.g. `"4242"`) as belt-and-braces.

## Matchers & filters

Same surface as `ffuf-dir-fuzz` — `match_codes`, `match_sizes`,
`match_words`, `match_lines`, `match_regex`, `filter_codes`,
`filter_sizes`, `filter_words`, `filter_lines`, `filter_regex`. Range
specs follow ffuf's grammar (`200,301-302,400-499`).

Typical patterns:

- **Baseline-size filter** — `filter_sizes: "4242"` drops the IIS / Apache
  default page that has consistent size.
- **Word-count match** — `match_words: "10-1000"` keeps responses whose
  body has a plausible vhost-specific payload.

## Rate control & timing

- `threads` (default 40) — concurrent workers, hard-capped at 200.
- `rate` — requests/second ceiling. Recommend `2`–`10` for production.
- `delay` — random jitter between requests, e.g. `"0.1-2.0"`.
- `max_time_sec` — total wall-clock deadline.

## Authentication

- `headers` — extra headers (e.g. `X-Forwarded-For`, `User-Agent`).
  Avoid duplicating `Host` here — the handler sets it from
  `host_template`.
- `cookies` — list of `name=value` cookie segments.
- For auth flows with cookies + CSRF tokens, use `raw_request`.

## Proxy

- `proxy` — upstream HTTP/SOCKS5 URL (for Burp / mitmproxy).
- `replay_proxy` — replay only matched responses through the proxy.

## Output

`ffuf -of json -o <vhost-results.json>` is always used. Each hit is
normalised to:

```json
{
  "host": "<FUZZ value>",
  "url":  "https://203.0.113.10",
  "status": 200,
  "length": 1234,
  "words": 120,
  "lines": 40,
  "duration_ms": 82,
  "content_type": "text/html; charset=utf-8",
  "redirect_location": ""
}
```

Up to 500 hits are returned in `summary.vhosts`. Full JSON and ffuf
stderr are written to the scan's `raw/` directory.

## Examples

**Basic vhost enumeration**

```yaml
url: https://203.0.113.10
host_template: FUZZ.example.com
wordlist: ["www", "api", "dev", "staging", "admin", "internal", ...]
filter_sizes: "4242"
```

**Per-host auto-calibration for scanning many bases**

```yaml
url: https://203.0.113.10
host_template: FUZZ.example.com
wordlist: [...]
auto_calibrate_per_host: true
```

**Authenticated vhost enumeration (raw request)**

```yaml
raw_request: |
  GET /admin HTTP/1.1
  Host: FUZZ.example.com
  Authorization: Bearer eyJhbGciOi…
  Accept: text/html
wordlist: ["admin", "staging", "internal", ...]
match_codes: "200,302"
```

**Stealth scan**

```yaml
url: https://203.0.113.10
host_template: FUZZ.example.com
wordlist: [...]
threads: 10
rate: 2
delay: "0.5-1.5"
max_time_sec: 600
```
