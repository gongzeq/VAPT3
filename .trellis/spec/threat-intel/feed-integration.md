# Feed Integration Spec (P1)

> Data source contracts for P1 feed pullers. Each source has: URL, API format, field mapping, preprocessing steps, rate-limit handling, and validation rules.
> Implementation: `secbot/threat_intel/feeds/` — new pullers follow the P0 pattern established in `cisa_kev.py` / `threatfox.py`.

---

## 1. Data Source Matrix

| Source | Type | API URL | Auth | Rate Limit | Schedule | FEED_SOURCES enum |
|--------|------|---------|------|-----------|----------|-------------------|
| NVD | Vulnerability (CVSS≥7.0) | `https://services.nvd.nist.gov/rest/json/cves/2.0` | API key (optional, free) | 5 req/30s (no key), 50 req/30s (with key) | Daily | `nvd` |
| MalwareBazaar | Malware samples | `https://bazaar.abuse.ch/api/v1/` | None | None (fair use) | Daily | `malwarebazaar` |
| Feodo Tracker | Botnet C2 IPs | `https://feodotracker.abuse.ch/downloads/datatable.json` | None | None | Daily | `feodo` |
| AlienVault OTX | Industry pulses | `https://otx.alienvault.com/api/v1/pulses/search` | API key (free registration) | 10 req/s | Weekly | `otx` |
| Exploit-DB | PoC availability | `https://gitlab.com/exploit-database/exploitdb.git` (git clone/diff) | None | None | Weekly | `exploit_db` |

> **Enum registration**: All new sources MUST be added to `FEED_SOURCES` tuple in `secbot/threat_intel/models.py`.

---

## 2. NVD (National Vulnerability Database)

### 2.1 Source

- **API**: `https://services.nvd.nist.gov/rest/json/cves/2.0`
- **API key**: Optional but recommended. Set via `NVD_API_KEY` env var. Free registration at https://nvd.nist.gov/developers/request-an-api-key
- **Docs**: https://nvd.nist.gov/developers/vulnerabilities

### 2.2 Request

```
GET https://services.nvd.nist.gov/rest/json/cves/2.0?cvssV3Severity=HIGH&resultsPerPage=2000&startIndex=0
Header: (if key) apiKey: <NVD_API_KEY>
```

**Pagination**: `resultsPerPage` (max 2000), `startIndex` offset. Must loop until all results fetched.

**Filter strategy**:
- Fetch `cvssV3Severity=HIGH` and `cvssV3Severity=CRITICAL` separately, OR
- Fetch all recent CVEs and filter `cvss_score >= 7.0` in preprocessing.
- **Recommended**: Fetch by `pubStartDate` / `lastModStartDate` (last 24h) to minimize payload.

### 2.3 Response Format

```json
{
  "resultsPerPage": 2000,
  "startIndex": 0,
  "totalResults": 18534,
  "vulnerabilities": [
    {
      "cve": {
        "id": "CVE-2024-1234",
        "descriptions": [{"lang": "en", "value": "..."}],
        "published": "2024-06-15T12:00:00.000",
        "lastModified": "2024-06-16T08:00:00.000",
        "metrics": {
          "cvssMetricV31": [{
            "cvssData": {
              "baseScore": 9.8,
              "baseSeverity": "CRITICAL",
              "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
            }
          }]
        },
        "weaknesses": [{"description": [{"value": "CWE-78"}]}],
        "configurations": [{
          "nodes": [{
            "cpeMatch": [{
              "vulnerable": true,
              "criteria": "cpe:2.3:a:vendor:product:1.0:*:*:*:*:*:*:*"
            }]
          }]
        }],
        "references": [{"url": "https://..."}]
      }
    }
  ]
}
```

### 2.4 Field Mapping (NVD → ThreatVuln)

| NVD Field | ThreatVuln Field | Transformation |
|-----------|-----------------|----------------|
| `cve.id` | `cve_id` | Direct |
| `descriptions[0].value` (lang=en) | `description` | Direct |
| `descriptions[0].value` (first 200 chars) | `title` | Truncate, or use `cve.id` if empty |
| `metrics.cvssMetricV31[0].cvssData.baseScore` | `cvss_score` | Direct (float) |
| `metrics.cvssMetricV31[0].cvssData.baseSeverity` | `severity` | `CRITICAL` → `critical`, `HIGH` → `high` |
| `configurations[].nodes[].cpeMatch[].criteria` | `affected_products` | Collect all CPE strings into JSON array |
| `published` | `published_date` | Parse ISO → `date` |
| (computed) | `is_cisa_kev` | Check if `cve_id` exists in ThreatVuln where `is_cisa_kev=True` — if so, MERGE |
| (computed) | `primary_source` | `"nvd"` for new records; if merging with existing KEV, keep `"cisa_kev"` |
| (computed) | `sources` | Append `"nvd"` to existing `sources` array |

### 2.5 Preprocessing Steps

1. **Filter**: Skip CVEs where `cvss_score < 7.0` (after parsing metrics).
2. **CISA KEV merge**: For each NVD CVE, check if it already exists in DB with `is_cisa_kev=True`. If yes:
   - Update `cvss_score`, `affected_products`, `description` (NVD data is more complete).
   - Append `"nvd"` to `sources` array.
   - Keep `is_cisa_kev=True`, `cisa_kev_date` unchanged.
   - Recalculate `severity`: `max(CVSS mapping, high)` for KEV vulns.
3. **CPE extraction**: Collect all `cpeMatch[].criteria` values into `affected_products` JSON array.
4. **Supply chain check**: After CPE extraction, run Industry CPE matching (see §8).
5. **Source refs**: Build `source_refs` entry:
   ```python
   source_refs = [{
       "source": "nvd",
       "source_id": cve_id,
       "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
       "observed_at": published_date.isoformat(),
       "confidence": 1.0,
       "metadata": {"cvss_vector": vector_string}
   }]
   ```

### 2.6 Rate-Limit Handling (CRITICAL)

NVD returns HTTP 404 with a message when rate-limited (not standard 429):

```python
if resp.status == 404:
    # May be rate limit — check response body for "timeout" or rate-limit message
    body = await resp.text()
    if "timeout" in body.lower() or "rate" in body.lower():
        await asyncio.sleep(6)  # NVD recommends 6s between requests without API key
        # Retry once
    # If still 404 after retry, treat as genuine not-found
```

**With API key**: Sleep 1s between paginated requests.
**Without API key**: Sleep 6s between paginated requests.

### 2.7 Good/Base/Bad

- **Good**: NVD pull fetches 500 CVEs (CVSS≥7.0), 120 merge with existing KEV records (supplementing CVSS/CPE), 380 are new `high`/`critical` vulns.
- **Base**: NVD API returns 0 results for the date range — status `ok`, counts all zero.
- **Bad**: NVD rate-limit causes 3 consecutive failures — status `failed`, `error_message` contains rate-limit hint, partial data committed in session.

### 2.8 Wrong vs Correct

**Wrong**: Creating a new ThreatVuln record for a CVE that already exists from CISA KEV, resulting in duplicate `cve_id` (violates unique constraint).

**Correct**: Querying `ThreatVuln` by `cve_id` first, then calling `upsert_threat_vuln()` which handles merge logic — CVSS/CPE from NVD supplements the existing KEV record.

---

## 3. abuse.ch MalwareBazaar

### 3.1 Source

- **API**: `https://bazaar.abuse.ch/api/v1/` (POST with form data)
- **Docs**: https://bazaar.abuse.ch/api/
- **Auth**: None required.

### 3.2 Request

```
POST https://bazaar.abuse.abuse.ch/api/v1/
Content-Type: application/x-www-form-urlencoded

query=get_recent&selector=100
```

**Queries used**:
| Query | Selector | Purpose |
|-------|----------|---------|
| `get_recent` | `100` | Recent 100 samples (daily pull) |
| `get_taginfo` | tag name | Search by tag (e.g. `APT41`, `ShadowPad`) |
| `get_siginfo` | signature name | Search by signature (e.g. `ShadowPad`) |

### 3.3 Response Format

```json
{
  "query_status": "ok",
  "data": [
    {
      "sha256_hash": "abc123...",
      "md5_hash": "def456...",
      "first_seen": "2026-06-15T14:30:00",
      "last_seen": "2026-06-15T14:30:00",
      "file_name": "sample.exe",
      "file_size": 245760,
      "file_type": "exe",
      "signature": "ShadowPad",
      "tags": ["APT41", "backdoor", "win"],
      "intelligence": {
        "clamav": null,
        "yara_rules": [{"rule_name": "ShadowPad_Generic", "author": "MalwareBazaar"}]
      },
      "reporter": "anonymous"
    }
  ]
}
```

### 3.4 Field Mapping (MalwareBazaar → ThreatMalwareFamily)

MalwareBazaar provides **sample-level** data; the spec requires mapping to **family-level** ThreatMalwareFamily records.

| MalwareBazaar Field | ThreatMalwareFamily Field | Transformation |
|---------------------|--------------------------|----------------|
| `signature` | `family_name` | Direct; skip if empty |
| `tags` (filter for platform: `win`/`linux`/`macos`/`android`) | `platform` | Map `win`→`windows`, collect into array |
| `tags` (filter for type: `rat`/`backdoor`/`ransomware`/`stealer`/`dropper`/`botnet`) | `type` | Direct match; default `other` |
| `sha256_hash` + `md5_hash` | `sample_hashes` | Append `{sha256, md5, source: "malwarebazaar"}` to existing array |
| `first_seen` | `first_seen` | Parse to `date` |
| `last_seen` | `last_active` | Parse to `date` |
| `intelligence.yara_rules` | `yara_rules` | Extract `rule_name` list |
| (computed) | `group_id` | Map via `signature` → group lookup (see §3.5) |
| (computed) | `source` | `"malwarebazaar"` |

### 3.5 Group Mapping Strategy

MalwareBazaar does NOT directly provide threat group association. Mapping strategy:

1. **Signature → Group lookup**: Build `lower(signature) → group_id` map from existing `ThreatMalwareFamily` records.
2. **Tag → Group lookup**: Check if any tag matches a known group name or alias.
3. **YARA rule → Group lookup**: Check if YARA rule name contains a known group identifier.
4. **Unmapped**: If no group found, `unmapped_count++`. Do NOT create orphan malware families.

### 3.6 Preprocessing Steps

1. **Filter**: Skip samples with empty `signature` (cannot map to family).
2. **Deduplicate by signature**: Multiple samples with same signature → one ThreatMalwareFamily upsert, sample hashes accumulated.
3. **Group mapping**: Apply §3.5 strategy. Skip if unmapped.
4. **Sample hash accumulation**: When upserting, append new hashes to existing `sample_hashes` array (avoid duplicates by `sha256`).
5. **Platform/type extraction**: Parse `tags` array for platform and type keywords.

### 3.7 Good/Base/Bad

- **Good**: 100 recent samples, 15 unique signatures, 10 map to known groups → 10 upserts (5 new families, 5 updated with new sample hashes).
- **Base**: 0 samples returned (`query_status: "no_results"`) → status `ok`, all counts zero.
- **Bad**: All 100 samples have unmapped signatures → status `partial`, `unmapped_count=100`, `inserted=0`.

---

## 4. abuse.ch Feodo Tracker

### 4.1 Source

- **URL**: `https://feodotracker.abuse.ch/downloads/datatable.json`
- **Format**: JSON array (datatable export)
- **Docs**: https://feodotracker.abuse.ch/
- **Auth**: None.

### 4.2 Response Format

```json
[
  {
    "first_seen": "2026-06-15T14:30:00Z",
    "last_seen": "2026-06-15T14:30:00Z",
    "dst_ip": "192.168.1.1",
    "dst_port": 8080,
    "malware": "Emotet",
    "sid": 1,
    "login_page": "https://feodotracker.abuse.ch/browse/malware/abc/",
    "network": "AS12345",
    "country": "Germany"
  }
]
```

### 4.3 Field Mapping (Feodo → ThreatInfraIP)

| Feodo Field | ThreatInfraIP Field | Transformation |
|-------------|--------------------|-----------------| 
| `dst_ip` | `ip_address` | Direct |
| `malware` | `malware_family` | Direct |
| `first_seen` | `first_seen` | Parse ISO datetime |
| `last_seen` | `last_seen` | Parse ISO datetime |
| `country` | `geo_country` | Direct |
| `network` | `asn` | Direct (may include "AS" prefix) |
| (computed) | `ip_type` | `"c2"` (Feodo is all C2/botnet) |
| (computed) | `status` | `"active"` (Feodo entries are active by default) |
| (computed) | `source` | `"feodo"` |
| (computed) | `group_id` | Map via `malware` → group lookup |

### 4.4 Group Mapping Strategy

Feodo Tracker provides `malware` field (e.g. `Emotet`, `TrickBot`, `Dridex`, `QakBot`).

1. **Malware → Group lookup**: Build `lower(malware) → group_id` from:
   a. Existing `ThreatMalwareFamily.family_name` → `group_id` map.
   b. Existing `ThreatInfraIP.malware_family` → `group_id` map.
   c. APT alias table (`apt_alias.alias_name`).
2. **Unmapped**: If malware family has no known group, `unmapped_count++`. Do NOT create pseudo-groups.

### 4.5 Preprocessing Steps

1. **Filter**: Skip entries with empty `dst_ip`.
2. **IP normalization**: Strip port if present in `dst_ip` (Feodo provides port separately).
3. **Group mapping**: Apply §4.4 strategy.
4. **Source refs**: Build entry with Feodo browse URL.

### 4.6 Relationship to ThreatFox

Feodo Tracker and ThreatFox both provide C2 IPs but from different perspectives:
- **ThreatFox**: Community-reported IOCs, broad malware coverage.
- **Feodo Tracker**: Specific botnet tracking (Emotet/TrickBot/Dridex/QakBot/Pikabot).

If the same IP appears in both sources, the upsert key `(group_id, ip_address, ip_type)` handles deduplication. The `source` field reflects the most recent puller; `source_refs` accumulates evidence from both sources.

---

## 5. AlienVault OTX

### 5.1 Source

- **API**: `https://otx.alienvault.com/api/v1/pulses/search`
- **Auth**: `X-OTX-API-KEY` header (free registration at https://otx.alienvault.com/)
- **API key env var**: `OTX_API_KEY`
- **Docs**: https://otx.alienvault.com/api

### 5.2 Request

```
GET https://otx.alienvault.com/api/v1/pulses/search?q=maritime&limit=50&page=1
Header: X-OTX-API-KEY: <OTX_API_KEY>
```

**Search queries** (industry-focused):
| Query | Purpose |
|-------|---------|
| `q=maritime` | Maritime-related pulses |
| `q=transport` | Transportation sector |
| `q=scada` | SCADA/ICS threats |
| `q=port+security` | Port infrastructure |

### 5.3 Response Format

```json
{
  "count": 42,
  "next": "https://otx.alienvault.com/api/v1/pulses/search?q=maritime&page=2",
  "results": [
    {
      "id": "abc123",
      "name": "APT41 Targets Maritime Sector",
      "description": "...",
      "created": "2026-06-15T12:00:00",
      "modified": "2026-06-15T12:00:00",
      "tags": ["apt41", "maritime", "shadowpad"],
      "adversary": "APT41",
      "attack_ids": [{"attack_id": "T1059", "name": "Command and Scripting"}],
      "indicators": [
        {"type": "IPv4", "indicator": "192.168.1.1", "title": "C2 server"},
        {"type": "FileHash-SHA256", "indicator": "abc123...", "title": "ShadowPad sample"}
      ]
    }
  ]
}
```

### 5.4 Field Mapping & Preprocessing

OTX provides **pulse-level** intelligence, not raw IOC feeds. Preprocessing:

1. **Industry filter**: Search with maritime/transport/scada keywords.
2. **Adversary extraction**: `pulse.adversary` → map to ThreatGroup by name/alias.
3. **Indicator extraction**:
   - `type: "IPv4"` → ThreatInfraIP (if adversary maps to group)
   - `type: "FileHash-SHA256"` → append to ThreatMalwareFamily.sample_hashes (if adversary maps to group)
   - `type: "CVE"` → check if matches existing ThreatVuln, create ThreatGroupVulnAssoc if adversary maps
4. **Attack technique extraction**: `pulse.attack_ids[].attack_id` → append to ThreatGroup.techniques.
5. **Source refs**: Build entry with OTX pulse URL `https://otx.alienvault.com/pulse/{pulse_id}`.

### 5.5 Group Mapping

- `pulse.adversary` field is the primary group mapping source.
- If `adversary` is empty, try `pulse.tags` for known group names.
- If no group found, skip IOC extraction but count as `unmapped`.

### 5.6 Rate-Limit Handling

OTX allows 10 requests/second. For weekly pulls with ~4 search queries, this is not a concern. Add 0.2s sleep between requests as a courtesy.

### 5.7 Good/Base/Bad

- **Good**: 4 industry searches return 42 pulses total, 28 have `adversary` field, 20 map to known groups → 15 new IPs, 8 new sample hashes, 5 new technique mappings.
- **Base**: 0 pulses returned for all queries → status `ok`, counts zero.
- **Bad**: OTX API key invalid (403) → status `failed`, `error_message` contains auth hint.

---

## 6. Exploit-DB

### 6.1 Source

- **Repo**: `https://gitlab.com/exploit-database/exploitdb.git` (or GitHub mirror `https://github.com/offensive-security/exploitdb.git`)
- **Format**: Git repository, each exploit is a file under `exploits/` directory.
- **Docs**: https://www.exploit-db.com/

### 6.2 Approach

Exploit-DB is NOT an API — it's a git repository. The puller:

1. **Clone or pull** the repo to a local cache (`~/.secbot/cache/exploitdb/`).
2. **Diff** against last commit hash to find new/modified exploit files.
3. **Parse** each exploit file header for metadata.
4. **Match** CVE IDs against existing ThreatVuln records → set `has_poc=True` / `exploit_available=True`.

### 6.3 Exploit File Format

Each file starts with a metadata header:

```
# Exploit Title: Apache Log4j RCE
# Date: 2021-12-10
# Exploit Author: anonymous
# Vendor Homepage: https://apache.org
# Software Link: 
# Version: 2.14.1
# Tested on: Linux
# CVE: CVE-2021-44228
```

### 6.4 Field Mapping (Exploit-DB → ThreatVuln update)

| Header Field | ThreatVuln Update | Transformation |
|-------------|-------------------|----------------|
| `CVE` | (match key) | Extract `CVE-YYYY-NNNN` pattern |
| (file existence) | `has_poc` | Set `True` if exploit file exists for this CVE |
| (file existence) | `exploit_available` | Set `True` (Exploit-DB hosts the actual code) |
| `Exploit Title` | (source_refs metadata) | Store in source_refs entry |
| `Date` | (source_refs metadata) | Store in source_refs entry |

### 6.5 Preprocessing Steps

1. **Git pull**: `git pull origin master` in cache directory. If no cache, `git clone --depth 1`.
2. **Diff**: `git diff --name-only <last_hash> HEAD exploits/` to get changed files.
3. **Parse header**: Read first 20 lines of each file, extract `# CVE: CVE-XXXX-NNNNN` line.
4. **Match**: For each CVE, query `ThreatVuln` by `cve_id`. If found:
   - Set `has_poc=True`, `exploit_available=True`.
   - Append source_refs entry: `{source: "exploit_db", source_id: EDB-ID, url: "https://www.exploit-db.com/exploits/<id>"}`
   - `inserted_count` or `updated_count` accordingly.
5. **Unmapped**: CVEs not in ThreatVuln DB → `unmapped_count++` (do NOT create new vuln records from Exploit-DB).
6. **Save last hash**: Store `HEAD` commit hash for next diff.

### 6.6 Good/Base/Bad

- **Good**: Git diff shows 50 new exploit files, 12 have CVE headers, 8 match existing ThreatVuln records → 8 updates (`has_poc=True`).
- **Base**: No new commits since last pull → status `ok`, counts zero.
- **Bad**: Git clone fails (network error) → status `failed`, `error_message` contains git error.

### 6.7 Wrong vs Correct

**Wrong**: Creating new ThreatVuln records from Exploit-DB CVE headers — Exploit-DB metadata is insufficient (no CVSS, no CPE, no severity classification).

**Correct**: Only UPDATE existing ThreatVuln records (from CISA KEV / NVD) with `has_poc`/`exploit_available` flags. Exploit-DB is a supplementary source, not a primary vulnerability source.

---

## 7. Feed Pull Function Signature Convention

All P1 feed pullers MUST follow this signature pattern (matching P0):

```python
async def pull_<source>(
    session: AsyncSession,
    *,
    trigger: str = "manual",
    url: Optional[str] = None,   # Override for testing
    **source_specific_kwargs,    # e.g. days=1 for ThreatFox
) -> dict[str, Any]:
    """Pull <source> data and upsert records.
    
    Returns summary: {run_id, source, status, inserted, updated, skipped, unmapped, error, metadata}
    """
```

### Required Return Dict

```python
{
    "run_id": str,          # FeedPullRun ID
    "source": str,          # Feed source name (matches FEED_SOURCES enum)
    "status": str,          # "ok" | "partial" | "failed"
    "inserted": int,        # New records created
    "updated": int,         # Existing records updated
    "skipped": int,         # Records skipped (invalid, filtered, wrong type)
    "unmapped": int,        # Records that couldn't map to ThreatGroup
    "error": Optional[str], # Error message if status == "failed"
    "metadata": dict,       # Source-specific metadata (catalog version, total entries, etc.)
}
```

### New Feed Pullers to Register

In `secbot/threat_intel/feeds/__init__.py`:

```python
from secbot.threat_intel.feeds.nvd import pull_nvd
from secbot.threat_intel.feeds.malwarebazaar import pull_malwarebazaar
from secbot.threat_intel.feeds.feodo import pull_feodo
from secbot.threat_intel.feeds.otx import pull_otx
from secbot.threat_intel.feeds.exploit_db import pull_exploit_db
```

### API Trigger Extension

In `threat_intel_routes.py::handle_trigger_feed_pull()`, extend `valid_sources`:

```python
valid_sources = {"cisa_kev", "threatfox", "mitre", "nvd", "malwarebazaar", "feodo", "otx", "exploit_db"}
```

---

## 8. Industry CPE Matching

### 8.1 Purpose

When NVD provides CPE data (`affected_products`), check each CPE string against the `industry_cpe` table. If matched, set `is_supply_chain=True` on the ThreatVuln record.

### 8.2 Matching Algorithm

```python
async def check_supply_chain(session, cve_id: str, affected_products: list[str]) -> bool:
    """Check if any CPE in affected_products matches industry_cpe table."""
    if not affected_products:
        return False
    
    result = await session.execute(
        select(IndustryCPE.cpe_string)
    )
    industry_cpes = {row.cpe_string for row in result}
    
    for cpe in affected_products:
        # Exact match
        if cpe in industry_cpes:
            return True
        # Prefix match (CPE version wildcard)
        for ind_cpe in industry_cpes:
            if cpe.startswith(ind_cpe.rsplit(":", 3)[0]):  # Match up to version
                return True
    
    return False
```

### 8.3 Integration Point

CPE matching runs AFTER NVD upsert, BEFORE `finish_feed_pull_run`:

```python
# In pull_nvd(), after upsert_threat_vuln():
if affected_products:
    is_supply = await check_supply_chain(session, cve_id, affected_products)
    if is_supply:
        vuln.is_supply_chain = True
        vuln.source_refs = vuln.source_refs or []
        vuln.source_refs.append({
            "source": "industry_cpe_match",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.9,
            "metadata": {"matched_cpes": matched_list}
        })
```

### 8.4 Industry CPE Seed Data

P1 should seed the `industry_cpe` table with maritime/transport products:

| CPE Pattern | Product | Industry Tag |
|-------------|---------|-------------|
| `cpe:2.3:a:siemens:simatic*` | Siemens SIMATIC SCADA | maritime/scada |
| `cpe:2.3:a:schneider:modicon*` | Schneider Modicon PLC | maritime/scada |
| `cpe:2.3:a:aveva:in touch*` | AVEVA InTouch HMI | maritime/scada |
| `cpe:2.3:h:kongsberg:k-*` | Kongsberg K-Ship | maritime |
| `cpe:2.3:a:wondershare:*` | Wondershare (fleet mgmt) | transport |

---

## 9. Scheduler Extension

### 9.1 Cron Jobs

All jobs registered in `scheduler.py::register_threat_intel_cron_jobs()`. Implementation: `secbot/threat_intel/scheduler.py`.

| Job ID | Source | Schedule | Notes |
|--------|--------|----------|-------|
| `threat-intel-cisa-kev` | `cisa_kev` | `0 8 * * *` (daily 08:00 UTC) | CISA Known Exploited Vulnerabilities |
| `threat-intel-threatfox` | `threatfox` | `0 8 * * *` (daily 08:00 UTC) | ThreatFox IOC feed |
| `threat-intel-nvd` | `nvd` | `0 9 * * *` (daily 09:00 UTC) | After CISA KEV for merge |
| `threat-intel-malwarebazaar` | `malwarebazaar` | `0 10 * * *` (daily 10:00 UTC) | |
| `threat-intel-feodo` | `feodo` | `0 11 * * *` (daily 11:00 UTC) | Feodo Tracker C2 IPs |
| `threat-intel-otx` | `otx` | `0 6 * * 1` (weekly Mon 06:00 UTC) | AlienVault OTX industry search |
| `threat-intel-exploit-db` | `exploit_db` | `0 7 * * 1` (weekly Mon 07:00 UTC) | After OTX |
| `threat-intel-maritime-ukmto` | `ukmto` | `0 6 * * 2` (weekly Tue 06:00 UTC) | P2 maritime UKMTO events |
| `threat-intel-maritime-recaap` | `recaap` | `0 6 1 * *` (monthly 1st 06:00 UTC) | P2 maritime ReCAAP events |
| `threat-intel-expiry-sweep` | `expiry` | `0 2 * * 0` (weekly Sun 02:00 UTC) | P2 data expiry (IP 90d, maritime 365d) |

### 9.2 Handler Extension

`handle_cron_threat_intel()` in `scheduler.py` dispatches by source:

```python
if source == "cisa_kev":
    result = await pull_cisa_kev(session, trigger="schedule")
elif source == "threatfox":
    result = await pull_threatfox(session, trigger="schedule")
elif source == "mitre":
    result = await import_mitre_groups(session, trigger="schedule")
elif source == "nvd":
    result = await pull_nvd(session, trigger="schedule")
elif source == "malwarebazaar":
    result = await pull_malwarebazaar(session, trigger="schedule")
elif source == "feodo":
    result = await pull_feodo(session, trigger="schedule")
elif source == "otx":
    result = await pull_otx(session, trigger="schedule")
elif source == "exploit_db":
    result = await pull_exploit_db(session, trigger="schedule")
elif source in ("ukmto", "recaap", "imo"):
    result = await pull_maritime(session, trigger="schedule", source=source)
elif source == "expiry":
    result = await run_expiry_sweep(session)
```

---

## 10. Feed Pull Response Format

The response format is shared across all feed pullers. The frontend FeedsPage renders this structure:

```typescript
interface FeedPullResult {
  run_id: string;
  source: string;        // "cisa_kev" | "threatfox" | "nvd" | ...
  status: string;        // "ok" | "partial" | "failed"
  inserted: number;
  updated: number;
  skipped: number;
  unmapped: number;
  error: string | null;
  metadata?: Record<string, unknown>;
}
```

---

## 11. Forbidden Patterns

| Pattern | Why Forbidden | Do Instead |
|---------|--------------|------------|
| Creating new ThreatVuln from Exploit-DB | Exploit-DB lacks CVSS/CPE/severity | Only UPDATE existing records with `has_poc` |
| Creating pseudo-groups for unmapped IOCs | Pollutes ThreatGroup with low-confidence entries | `unmapped_count++`, skip the record |
| NVD pull without rate-limit handling | NVD will block the IP | Sleep 6s (no key) / 1s (with key) between requests |
| Writing CPE match results to CMDB | Violates module boundary | Only update `threat_vuln.is_supply_chain` |
| Fetching all NVD CVEs (no date filter) | Payload too large (>200MB) | Use `pubStartDate` for last 24h window |
| MalwareBazaar: creating family without group | Orphan families have no analysis value | Skip unmapped, count in `unmapped_count` |
| Feodo: creating IP without group_id | Violates NOT NULL FK constraint | Map via malware → group, skip if unmapped |
| OTX: storing full pulse description | Bloats DB with unstructured text | Store only structured indicators + pulse URL in source_refs |

---

## 12. Tests Required

For each new feed puller:

- [ ] **Upsert idempotency**: Running puller twice with same data → 0 inserts on second run.
- [ ] **Unmapped counting**: Records that can't map to ThreatGroup → `unmapped_count` increases.
- [ ] **Empty result**: API returns 0 results → status `ok`, all counts zero.
- [ ] **Partial failure**: Some records fail → status `partial`, successful records committed.
- [ ] **Total failure**: API error / network timeout → status `failed`, `error_message` set.
- [ ] **Rate-limit**: Mock 429/404 response → puller sleeps and retries (or fails gracefully).
- [ ] **CPE matching**: NVD vuln with industry CPE → `is_supply_chain=True` after pull.
- [ ] **KEV merge**: NVD vuln matching existing KEV → CVSS supplemented, `is_cisa_kev` preserved.

---

## Origin

Source: `docs/prd-threat-intelligence.md` §4 (数据源与接入策略) + §8 P1 + `开源情报.md` + P0 feed implementations (`secbot/threat_intel/feeds/cisa_kev.py`, `threatfox.py`).
