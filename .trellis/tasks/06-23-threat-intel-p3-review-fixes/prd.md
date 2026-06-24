# PRD: Threat Intel P3 Code Review Fixes

> **Task**: Fix issues identified in the P3 code review for the threat intelligence feed expansion.
> **Date**: 2026-06-23
> **Reviewer**: AI Code Review
> **Status**: Pending Implementation

---

## 1. Background

The P3 batch added 5 new threat intelligence feed pullers (URLhaus, Ransomware.live, ASAM, OSV, PhishTank), enhanced the MITRE ATT&CK importer to extract malware families and techniques, introduced 2 new data models (`ThreatInfraURL`, `RansomwareEvent`), and added a frontend graph mode toggle.

A comprehensive code review identified **2 P0 bugs** (feeds completely non-functional), **3 P1 issues** (data quality / missing infrastructure), and **5 P2/P3 issues** (code quality / test coverage).

---

## 2. Scope

### In Scope

| ID | Priority | Category | Issue | Files |
|----|----------|----------|-------|-------|
| CR-01 | P0 | Bug | OSV API query returns 0 results — missing `package.name` | `secbot/threat_intel/feeds/osv.py` |
| CR-02 | P0 | Bug | URLhaus API returns 401 Unauthorized — missing auth | `secbot/threat_intel/feeds/urlhaus.py` |
| CR-03 | P1 | Data Quality | Ransomware group name matching has false positives | `secbot/threat_intel/feeds/ransomware_live.py` |
| CR-04 | P1 | Infrastructure | No Alembic migration for new tables | `secbot/threat_intel/models.py` |
| CR-05 | P2 | Data Loss | URLhaus malware-to-group lookup loses shared families | `secbot/threat_intel/feeds/urlhaus.py` |
| CR-06 | P2 | Test | No unit tests for any new feed pullers or repo functions | `tests/threat_intel/` |
| CR-07 | P3 | Code Quality | Unused variable `labels` in mitre_groups.py (ruff F841) | `secbot/threat_intel/feeds/mitre_groups.py` |
| CR-08 | P3 | Code Quality | OSV CVSS score parsing has dead `float()` code path | `secbot/threat_intel/feeds/osv.py` |
| CR-09 | P3 | Code Quality | Ransomware `data_leaked=True` hardcoded for all events | `secbot/threat_intel/feeds/ransomware_live.py` |
| CR-10 | P3 | Performance | PhishTank sorts entire feed before slicing max_entries | `secbot/threat_intel/feeds/phishtank.py` |

### Out of Scope

- MITRE Phase 3 N+1 query optimization (acceptable for ~150 groups)
- Graph `all_mode` 3-query pattern (acceptable for current scale)
- API authentication for new endpoints (consistent with existing pattern)

---

## 3. Detailed Requirements

### CR-01: Fix OSV API Query (P0)

**Problem**: The OSV `/v1/query` endpoint requires `package.name` in the request payload. Querying with only `{"package": {"ecosystem": "npm"}}` returns 0 vulnerabilities. The entire OSV feed is silently non-functional — every run returns `status=ok, inserted=0`.

**Verified**: `curl -X POST https://api.osv.dev/v1/query -d '{"package": {"ecosystem": "PyPI"}}'` returns `{"vulns": []}`.

**Fix Options** (choose one):

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| A | Download OSV JSON dumps per ecosystem from `https://osv-vulnerabilities.storage.googleapis.com/` | Complete coverage, no API limits | Large downloads (~50MB per ecosystem) |
| B | Use `/v1/querybatch` with a curated list of critical maritime/transport packages | Targeted, smaller payload | Requires maintaining package list |
| C | Use `/v1/query` with specific package names from Industry CPE table | Integrates with existing CPE matching | Limited to known packages |

**Recommended**: Option A — download ecosystem-level JSON dumps. OSV provides per-ecosystem JSON files at predictable URLs (e.g., `https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip`).

**Acceptance Criteria**:
- [ ] OSV pull returns > 0 vulnerabilities for at least one ecosystem
- [ ] CVSS filtering (>= 7.0) works correctly
- [ ] `feed_pull_run` metadata records `total_vulns_processed > 0`
- [ ] Status is `ok` or `partial` (not `failed`) on successful runs

### CR-02: Fix URLhaus API Authentication (P0)

**Problem**: The URLhaus API at `https://urlhaus-api.abuse.ch/v1/urls/recent/` returns `{"error": "Unauthorized"}` (HTTP 401). The code does not include any authentication headers.

**Verified**: `curl https://urlhaus-api.abuse.ch/v1/urls/recent/` returns `{"error": "Unauthorized"}`.

**Fix**:
1. Check if URLhaus now requires an API key (register at abuse.ch if needed).
2. Add `URLHAUS_API_KEY` environment variable support.
3. Pass API key in request header: `Auth-Key: <URLHAUS_API_KEY>`.
4. If the endpoint has changed, update `URLHAUS_API_URL` to the correct one.
5. Add a clear error message when the API key is missing.

**Acceptance Criteria**:
- [ ] URLhaus pull returns HTTP 200 with valid data (when API key is configured)
- [ ] Clear error message when API key is missing: `"URLhaus API key not configured. Set URLHAUS_API_KEY env var."`
- [ ] `feed_pull_run` status is `failed` with descriptive error when key is missing
- [ ] URLhaus entries are correctly upserted into `ThreatInfraURL` table

### CR-03: Fix Ransomware Group Name Matching (P1)

**Problem**: `_extract_group_from_text()` uses case-insensitive substring matching. Common group names produce false positives:
- `"play"` matches `"display"`, `"played"`, `"playlist"`
- `"hive"` matches `"archive"`, `"chive"`
- `"cuba"` matches `"cuban"`

**Fix**: Use word-boundary regex matching:
```python
import re

def _extract_group_from_text(text: str) -> str:
    text_lower = text.lower()
    for name_lower, canonical in _GROUP_NAME_LOOKUP.items():
        if re.search(r'\b' + re.escape(name_lower) + r'\b', text_lower):
            return canonical
    return "Unknown"
```

**Acceptance Criteria**:
- [ ] `"Display panel was compromised"` does NOT match group `"Play"`
- [ ] `"Archive of leaked data"` does NOT match group `"Hive"`
- [ ] `"LockBit claimed responsibility"` DOES match group `"LockBit"`
- [ ] `"BlackCat / ALPHV"` matches both `"BlackCat"` and `"ALPHV"` (first match wins, acceptable)

### CR-04: Add Alembic Migration for New Tables (P1)

**Problem**: New tables `ThreatInfraURL` and `RansomwareEvent` are defined in `models.py` but have no Alembic migration. Production deployments using Alembic will not have these tables created.

**Fix**:
1. Generate Alembic migration: `alembic revision --autogenerate -m "add threat_infra_url and ransomware_event tables"`
2. Verify migration includes:
   - `threat_infra_url` table with all columns, indexes, and unique constraint
   - `ransomware_event` table with all columns, indexes, and unique constraint
3. Test migration on a clean database.

**Acceptance Criteria**:
- [ ] `alembic upgrade head` creates both new tables on a fresh DB
- [ ] `alembic downgrade -1` drops both tables cleanly
- [ ] Indexes and unique constraints match the model definitions

### CR-05: Fix URLhaus Malware-to-Group Lookup (P2)

**Problem**: `_build_malware_to_group_lookup()` builds `dict[str, str]` (family_name → group_id). When the same malware family is used by multiple APT groups (e.g., Cobalt Strike), only the last group wins — other associations are silently lost.

**Fix**: Change to `dict[str, list[str]]` and handle ambiguity:
```python
async def _build_malware_to_group_lookup(session: AsyncSession) -> dict[str, list[str]]:
    result = await session.execute(
        select(ThreatMalwareFamily.family_name, ThreatMalwareFamily.group_id)
    )
    lookup: dict[str, list[str]] = {}
    for row in result:
        if row.family_name:
            key = row.family_name.lower()
            lookup.setdefault(key, []).append(row.group_id)
    return lookup
```

When looking up, if multiple groups are found, set `group_id=None` (avoid incorrect attribution) and log a warning.

**Acceptance Criteria**:
- [ ] Malware families used by multiple groups do not produce incorrect single-group attribution
- [ ] Warning logged when ambiguity is detected
- [ ] Single-group families still map correctly

### CR-06: Add Unit Tests for New Feed Pullers (P2)

**Problem**: No tests exist for any of the 5 new feed pullers, 2 new repo functions, or 2 new API endpoints. The spec (§12 Tests Required) mandates tests for upsert idempotency, unmapped counting, empty/partial/failed states.

**Required Tests** (per spec §12):

For each new feed puller (`urlhaus`, `ransomware_live`, `asam`, `osv`, `phishtank`):
- [ ] **Upsert idempotency**: Running puller twice with same mock data → 0 inserts on second run
- [ ] **Unmapped counting**: Records that fail to map → `unmapped_count` increases
- [ ] **Empty result**: API returns 0 results → status `ok`, all counts zero
- [ ] **Partial failure**: Some records fail → status `partial`
- [ ] **Total failure**: API error → status `failed`, `error_message` set

For new repo functions:
- [ ] `upsert_threat_infra_url` — insert, update, dedup by `(source, source_ref)`
- [ ] `upsert_ransomware_event` — insert, update, dedup by `(source, source_ref)`
- [ ] `list_threat_infra_urls` — pagination, filters (group_id, url_type, source, status, q)
- [ ] `list_ransomware_events` — pagination, filters (group_name, severity, date range)

For API endpoints:
- [ ] `GET /api/threat-intel/urls` — returns paginated results
- [ ] `GET /api/threat-intel/ransomware` — returns paginated results

**Test file locations**:
- `tests/threat_intel/feeds/test_urlhaus.py`
- `tests/threat_intel/feeds/test_ransomware_live.py`
- `tests/threat_intel/feeds/test_asam.py`
- `tests/threat_intel/feeds/test_osv.py`
- `tests/threat_intel/feeds/test_phishtank.py`
- `tests/threat_intel/test_repo_urls.py`
- `tests/threat_intel/test_repo_ransomware.py`

### CR-07: Remove Unused Variable `labels` (P3)

**Problem**: `labels = stix_obj.get("labels", [])` in `mitre_groups.py:99` is assigned but never used. Ruff reports F841.

**Fix**: Remove the line.

**Acceptance Criteria**:
- [ ] `ruff check` passes with 0 errors on `mitre_groups.py`

### CR-08: Clean Up OSV CVSS Score Parsing (P3)

**Problem**: `float(score_str)` is attempted first, but OSV `score` field is always a CVSS vector string, so `float()` always fails. This is dead code.

**Fix**: Remove the `float()` attempt, directly call `_cvss_base_score()`:
```python
for sev in severity_list:
    if sev.get("type") == "CVSS_V3":
        score_str = sev.get("score", "")
        cvss_score = _cvss_base_score(score_str)
        break
```

**Acceptance Criteria**:
- [ ] CVSS vector strings are correctly parsed to numeric scores
- [ ] No `float()` exception handling for non-numeric strings

### CR-09: Make Ransomware `data_leaked` Configurable (P3)

**Problem**: `data_leaked=True` is hardcoded for all ransomware events. While Ransomware.live primarily tracks leak sites, some events may be encryption-only without data exfiltration.

**Fix**: Infer from summary text:
```python
def _has_data_leak_indicator(summary: str) -> bool:
    """Check if summary text indicates data exfiltration."""
    indicators = ["leak", "data", "exfiltrat", "stolen", "download", "publish"]
    summary_lower = summary.lower()
    return any(ind in summary_lower for ind in indicators)
```

**Acceptance Criteria**:
- [ ] Events with "data leaked" in summary → `data_leaked=True`
- [ ] Events with no leak indicators → `data_leaked=False`
- [ ] Conservative: when in doubt, default to `True` (Ransomware.live is a leak site tracker)

### CR-10: Optimize PhishTank Sort (P3)

**Problem**: `entries.sort()` sorts the entire feed (potentially 100k+ entries) before slicing `max_entries` (500). This is O(n log n) when O(n) would suffice.

**Fix**: Use `heapq.nlargest`:
```python
import heapq
entries = heapq.nlargest(
    max_entries, entries,
    key=lambda e: e.get("submission_time", ""),
)
```

**Acceptance Criteria**:
- [ ] Same entries selected as before (most recent by submission_time)
- [ ] No full-sort performance penalty on large feeds

---

## 4. Spec Compliance Checklist

Per `.trellis/spec/threat-intel/index.md` Pre-Implementation Checklist:

- [ ] Upsert key matches P0 pattern — new tables have documented upsert keys
- [ ] Feed puller follows exact lifecycle (create_feed_pull_run → fetch → upsert → finish_feed_pull_run)
- [ ] New API endpoints follow `/api/threat-intel/` prefix and use `_ensure_engine()` + `get_session()`
- [ ] Frontend types mirror backend response shapes in `threat-intel-client.ts`
- [ ] No direct `sqlite3` / raw SQL outside `secbot/threat_intel/`
- [ ] Source URLs preserved in `source_refs` for human verification
- [ ] Rate-limit handling (429 response) implemented for external APIs
- [ ] Tests cover upsert idempotency + unmapped counting + empty/partial/failed states

Per `.trellis/spec/threat-intel/feed-integration.md` §11 Forbidden Patterns:

- [ ] No creating pseudo-groups for unmapped IOCs
- [ ] No NVD pull without rate-limit handling (applies to OSV too)
- [ ] No MalwareBazaar/URLhaus family without group mapping

---

## 5. Upsert Key Documentation (Spec Update Required)

The spec documents upsert keys for P0/P1 tables. The new P3 tables need to be added:

| Entity | Upsert Key | Notes |
|--------|-----------|-------|
| ThreatInfraURL | `(source, source_ref)` or `(source, url)` when source_ref is None | Matches existing pattern |
| RansomwareEvent | `(source, source_ref)` or `(group_name, victim_name, breach_date)` fallback | Fallback for APIs without source_ref |

**Update**: `.trellis/spec/threat-intel/index.md` §Upsert Pattern table.

---

## 6. Implementation Order

1. **CR-07** (remove unused variable) — trivial, 1 line
2. **CR-08** (clean up CVSS parsing) — trivial, 3 lines
3. **CR-03** (fix group name matching) — small, 1 function
4. **CR-09** (data_leaked inference) — small, 1 function
5. **CR-10** (optimize PhishTank sort) — small, 2 lines
6. **CR-05** (fix URLhaus lookup) — medium, 1 function + caller
7. **CR-01** (fix OSV API query) — medium, rewrite query logic
8. **CR-02** (fix URLhaus auth) — medium, add env var + header
9. **CR-04** (Alembic migration) — medium, generate + verify
10. **CR-06** (unit tests) — large, ~7 test files

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OSV dump download is too large | Medium | Medium | Use streaming decompression, cap per-ecosystem |
| URLhaus API key not available | Medium | High | Fall back to disabled feed with clear log message |
| Ransomware regex matching misses edge cases | Low | Low | Conservative matching, "Unknown" fallback |
| Migration conflicts with existing DB | Low | High | Test on copy of production DB first |
| Test mocks don't match real API responses | Medium | Medium | Use recorded API responses as fixtures |

---

## 8. Success Metrics

After all fixes:
- All 5 P3 feeds can be triggered manually and return data (or clear error if API unavailable)
- `ruff check` passes with 0 errors on all modified files
- `mypy` passes (no new type errors)
- All new unit tests pass
- `alembic upgrade head` succeeds on clean DB
- `feed_pull_run` table shows non-zero `inserted_count` for OSV and URLhaus on first successful run
