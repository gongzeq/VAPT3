---
name: knowledge-search
display_name: Security Knowledge Search
version: 1.0.0
risk_level: low
category: knowledge
network_egress: optional
expected_runtime_sec: 10
summary_size_hint: medium
---

Search the local cybersecurity knowledge base (`secbot/knowledge/docs/`) for
relevant security documentation, vulnerability references, attack methodologies,
and defensive techniques.

Use this skill when the user asks you to:
- Explain a security concept (XSS, SQL injection, SSRF, etc.)
- Look up CVE details or vulnerability information
- Find attack methodologies or pentesting checklists
- Retrieve defensive best practices or hardening guides
- Answer any cybersecurity knowledge question

## How it works

1. **Keyword search** (primary): scans all `.md` files under `knowledge/docs/` using
   regex pattern matching. Fast (milliseconds), precise for technical terms.
2. **Vector fallback** (when keyword hits are insufficient): if a `vector_cache.json`
   index exists, performs semantic similarity search using cosine distance on
   pre-computed embeddings. Handles synonym/paraphrase queries.

## Arguments

- `query` (string, required): the security question or search terms.
- `top_k` (integer, optional, default 5): max number of results to return.
- `source_filter` (string, optional): limit results to a subdirectory
  (e.g. `"web-security"`, `"cve-archive"`, `"methodologies"`, `"regulations"`, `"ai-security"`).

## Return contract

```json
{
  "action": "search",
  "ok": true,
  "data": {
    "query": "SQL 注入绕过 WAF",
    "results": [
      {
        "text": "...",
        "source": "web-security/sql-injection.md",
        "heading": "绕过技术",
        "score": 0.95,
        "match_type": "keyword"
      }
    ],
    "total_hits": 3,
    "search_mode": "keyword"
  },
  "elapsed_ms": 42
}
```

## Notes

- The knowledge base is built from curated markdown documents.
- Vector index must be pre-built via `secbot knowledge index` CLI command.
- If neither keyword nor vector results are found, returns an empty result set with `ok: true`.
