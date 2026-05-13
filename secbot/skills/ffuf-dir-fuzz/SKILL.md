---
name: ffuf-dir-fuzz
display_name: FFUF Directory / Content Fuzz
version: 2.0.0
risk_level: medium
category: asset_discovery
external_binary: ffuf
network_egress: required
expected_runtime_sec: 300
summary_size_hint: medium
---

# FFUF directory / content fuzzing

Run [ffuf](https://github.com/ffuf/ffuf) against a target web app to
discover hidden directories, files, parameters or API endpoints. The
skill replaces the `FUZZ` keyword in the URL (or in a captured raw HTTP
request) with every entry from the provided wordlist and reports the
matching responses. Medium risk: it generates substantial traffic — only
use on in-scope systems.

## Two invocation modes

1. **URL + FUZZ marker** — simplest. Put `FUZZ` anywhere in the URL,
   optionally with a POST body, custom headers, or extensions:

   ```
   url          = "https://target.com/FUZZ"
   wordlist     = ["admin", "api", "backup", ...]
   extensions   = [".php", ".bak", ".old"]       # optional
   match_codes  = "200,204,301,302,307,401,403"  # default
   ```

2. **Raw HTTP request** — the recommended mode when the endpoint needs
   authentication or a complex body (JWTs, session cookies, CSRF tokens,
   GraphQL, …). Capture the request from Burp / DevTools, replace the
   value you want to fuzz with `FUZZ`, and pass the whole thing as
   `raw_request`. ffuf is invoked with `--request`.

   ```
   raw_request = """
   POST /api/v1/query HTTP/1.1
   Host: api.target.com
   Authorization: Bearer eyJhbGciOi…
   Content-Type: application/json

   {"query": "FUZZ", "limit": 100}
   """
   request_proto = "https"           # or "http"
   wordlist      = ["users", "admin", ...]
   ```

## Auto-calibration (`-ac`) is on by default

The handler always passes `-ac` (or `-ach` for per-host calibration) so
ffuf automatically filters the baseline "not-found" responses. This is
non-negotiable for usable results — disable only if you have a specific
reason (`auto_calibrate: false`). Custom auto-calibration strings can be
supplied via `auto_calibrate_strings`.

## Matchers & filters

| Option            | ffuf flag | Purpose                            |
|-------------------|-----------|------------------------------------|
| `match_codes`     | `-mc`     | Status codes to include            |
| `match_sizes`     | `-ms`     | Response sizes to include          |
| `match_words`     | `-mw`     | Word counts to include             |
| `match_lines`     | `-ml`     | Line counts to include             |
| `match_regex`     | `-mr`     | Response-body regex to include     |
| `filter_codes`    | `-fc`     | Status codes to drop               |
| `filter_sizes`    | `-fs`     | Response sizes to drop             |
| `filter_words`    | `-fw`     | Word counts to drop                |
| `filter_lines`    | `-fl`     | Line counts to drop                |
| `filter_regex`    | `-fr`     | Response-body regex to drop        |

All range specs follow the ffuf grammar: `200,204,301-302,400-499`.
Regex inputs must not contain shell metacharacters (`<`, `>`, `$`, …) —
we reject those to keep the argv safe.

## Rate control

- `threads` (default 40) — concurrent workers, hard-capped at 200.
- `rate` — requests/second ceiling. Use low values (`2`–`10`) on
  production to avoid WAF/IDS triggers.
- `delay` — random jitter between requests, e.g. `"0.1-2.0"`.
- `max_time_sec`, `max_time_job_sec` — total / per-job wall-clock
  deadlines. `max_time_job_sec` only matters when `recursion` is set.

## Recursion

Set `recursion: true` to descend into discovered directories; combine
with `recursion_depth` (1..5). Always set `max_time_job_sec` to avoid
getting stuck in deep trees.

## Authentication

- `headers` — list of `Name: Value` strings (e.g. Authorization,
  X-API-Key). Values must not contain shell metacharacters.
- `cookies` — list of `name=value` cookie segments.
- Use `raw_request` instead when the auth surface is rich (cookies +
  CSRF + dynamic payload).

## Proxy

- `proxy` — upstream HTTP/SOCKS5 URL (e.g. for Burp: `http://127.0.0.1:8080`).
- `replay_proxy` — replay only matched responses through the proxy.

## Output

`ffuf -of json -o <results.json>` is always used. The handler normalises
each hit into:

```json
{
  "url": "...",
  "input": "<FUZZ value>",
  "status": 200,
  "length": 1234,
  "words": 120,
  "lines": 40,
  "duration_ms": 82,
  "content_type": "text/html; charset=utf-8",
  "redirect_location": "",
  "host": "target.com"
}
```

Up to 500 hits are returned in `summary.hits`. Full JSON and ffuf stderr
are written to the scan's `raw/` directory.

## Examples

**Directory discovery with extensions**

```yaml
url: https://target.com/FUZZ
wordlist: [...raft-large-directories entries...]
extensions: [".php", ".bak", ".old"]
match_codes: "200,301,302,403"
```

**Parameter-name fuzzing**

```yaml
url: https://target.com/page?FUZZ=test
wordlist: [...burp-parameter-names entries...]
filter_sizes: "4242"
```

**Authenticated IDOR (raw request)**

```yaml
raw_request: |
  GET /api/v1/users/FUZZ/profile HTTP/1.1
  Host: api.target.com
  Authorization: Bearer eyJhbGciOi…
  Accept: application/json
wordlist: ["1", "2", "3", "4", "5", ...]
match_codes: "200,201"
filter_words: "100-200"
```

**Stealth scan**

```yaml
url: https://target.com/FUZZ
wordlist: [...common.txt...]
threads: 10
rate: 2
delay: "0.5-1.5"
max_time_sec: 600
```
