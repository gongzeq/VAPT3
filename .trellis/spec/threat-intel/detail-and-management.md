# Detail Pages & Management UI Spec (P1)

> Spec for detail page APIs, frontend detail components, Watchlist management, APT alias management, and feed failure notifications.
> Source: `docs/prd-threat-intelligence.md` §6 (API) + §7.2 (frontend pages).

---

## 1. Detail Page APIs

P0 shipped list APIs (`GET /vulns`, `GET /ips`, `GET /malware`). P1 adds detail endpoints.

### 1.1 GET /api/threat-intel/vulns/:id

**Response**:
```json
{
  "id": "01HQ...",
  "cve_id": "CVE-2024-1234",
  "title": "Apache Log4j RCE",
  "description": "...",
  "cvss_score": 9.8,
  "severity": "critical",
  "affected_products": ["cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*"],
  "is_supply_chain": true,
  "has_poc": true,
  "exploit_available": true,
  "is_cisa_kev": true,
  "cisa_kev_date": "2021-12-10",
  "published_date": "2021-12-10",
  "primary_source": "cisa_kev",
  "sources": ["cisa_kev", "nvd", "exploit_db"],
  "source_refs": [
    {"source": "cisa_kev", "source_id": "CVE-2024-1234", "url": "https://...", "observed_at": "2021-12-10", "confidence": 1.0},
    {"source": "nvd", "source_id": "CVE-2024-1234", "url": "https://nvd.nist.gov/vuln/detail/CVE-2024-1234", "observed_at": "2021-12-10", "confidence": 1.0},
    {"source": "exploit_db", "source_id": "50592", "url": "https://www.exploit-db.com/exploits/50592", "observed_at": "2021-12-15", "confidence": 1.0}
  ],
  "tags": ["ransomware:known"],
  "exploiting_groups": [
    {"group_id": "01HQ...", "group_name": "APT41", "relationship_type": "exploited", "confidence": 0.9, "last_seen": "2024-06-15"}
  ],
  "last_ingested_at": "2026-06-16T08:00:00Z",
  "created_at": "2021-12-10T00:00:00Z",
  "updated_at": "2026-06-16T08:00:00Z"
}
```

**Repo function**: `get_threat_vuln(session, vuln_id) -> Optional[dict]`
- Query `ThreatVuln` by `id`.
- Query `ThreatGroupVulnAssoc` + `ThreatGroup` JOIN for `exploiting_groups`.
- Include all `source_refs`, `tags`, `affected_products`.

### 1.2 GET /api/threat-intel/ips/:id

**Response**:
```json
{
  "id": "01HQ...",
  "group_id": "01HQ...",
  "group_name": "APT41",
  "ip_address": "192.168.1.1",
  "ip_type": "c2",
  "malware_family": "ShadowPad",
  "geo_country": "Germany",
  "asn": "AS12345",
  "first_seen": "2026-06-01T00:00:00Z",
  "last_seen": "2026-06-15T00:00:00Z",
  "status": "active",
  "source": "threatfox",
  "confidence": 0.85,
  "source_refs": [
    {"source": "threatfox", "source_id": "12345", "url": "https://threatfox.abuse.ch/ioc/12345", "observed_at": "2026-06-15", "confidence": 0.85}
  ],
  "tags": ["botnet", "shadowpad"],
  "last_ingested_at": "2026-06-15T14:30:00Z",
  "created_at": "2026-06-01T00:00:00Z"
}
```

**Repo function**: `get_threat_infra_ip(session, ip_id) -> Optional[dict]`
- Query `ThreatInfraIP` by `id`, JOIN `ThreatGroup` for `group_name`.

### 1.3 GET /api/threat-intel/malware/:id

**Response**:
```json
{
  "id": "01HQ...",
  "group_id": "01HQ...",
  "group_name": "APT41",
  "family_name": "ShadowPad",
  "aliases": ["ShadowPad", "Sandbox"],
  "description": "Modular backdoor used by APT41...",
  "type": "backdoor",
  "platform": ["windows"],
  "sample_hashes": [
    {"md5": "abc123...", "sha256": "def456...", "source": "malwarebazaar"},
    {"md5": "ghi789...", "sha256": "jkl012...", "source": "malwarebazaar"}
  ],
  "yara_rules": ["ShadowPad_Generic"],
  "first_seen": "2017-01-01",
  "last_active": "2026-06-15",
  "source": "malwarebazaar",
  "confidence": 0.9,
  "source_refs": [...],
  "tags": ["apt41", "backdoor"],
  "last_ingested_at": "2026-06-15T14:30:00Z",
  "created_at": "2017-01-01T00:00:00Z"
}
```

**Repo function**: `get_threat_malware(session, malware_id) -> Optional[dict]`
- Query `ThreatMalwareFamily` by `id`, JOIN `ThreatGroup` for `group_name`.
- Include full `sample_hashes` array (not truncated).

### 1.4 API Handler Pattern

All three detail endpoints follow the same handler pattern:

```python
async def handle_get_vuln_detail(request: web.Request) -> web.Response:
    """GET /api/threat-intel/vulns/{id} — vulnerability detail."""
    await _ensure_engine()
    vuln_id = request.match_info["id"]
    async with get_session() as session:
        data = await get_threat_vuln(session, vuln_id)
    if data is None:
        return _error(404, "not_found", f"Vulnerability {vuln_id} not found")
    return web.json_response(data)
```

**Route registration** (add to `register_routes()`):
```python
router.add_get("/api/threat-intel/vulns/{id}", handle_get_vuln_detail)
router.add_get("/api/threat-intel/ips/{id}", handle_get_ip_detail)
router.add_get("/api/threat-intel/malware/{id}", handle_get_malware_detail)
```

### 1.5 Detail API Response Shapes

All detail APIs return a flat JSON object (not paginated). The `source_refs` array is always included in full (not truncated). The `exploiting_groups` field on vuln detail is a reverse-lookup from `ThreatGroupVulnAssoc`.

---

## 2. Frontend Detail Pages

### 2.1 Vulnerability Detail Page (`/threat-intel/vulns/:id`)

**Component**: `VulnDetailPage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ [← 返回漏洞列表]                          │
│                                          │
│ CVE-2024-1234                    [严重]  │
│ Apache Log4j RCE                         │
│                                          │
│ ┌─────────┬─────────┬─────────┐         │
│ │ CVSS    │ KEV     │ 供应链   │         │
│ │ 9.8     │ ✓       │ ✓       │         │
│ └─────────┴─────────┴─────────┘         │
│                                          │
│ 描述: ...                                │
│                                          │
│ 影响产品:                                │
│ • cpe:2.3:a:apache:log4j:2.14.1         │
│                                          │
│ 利用该漏洞的组织:                        │
│ • APT41 (exploited, 置信度 0.9)          │
│                                          │
│ 来源证据:                                │
│ • CISA KEV — https://...                │
│ • NVD — https://...                      │
│ • Exploit-DB — https://...               │
│                                          │
│ PoC: ✓ 可用  Exploit: ✓ 可用            │
└──────────────────────────────────────────┘
```

**Key components**:
- `SeverityBadge`: `critical` = red, `high` = amber. CISA KEV badge in blue.
- `SupplyChainBadge`: green badge if `is_supply_chain=true`.
- `SourceRefList`: renders `source_refs` as clickable links with source name.
- `ExploitingGroupsList`: table of groups with `relationship_type` and `confidence`.

### 2.2 IP Detail Page (`/threat-intel/ips/:id`)

**Component**: `IPDetailPage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ [← 返回IP列表]                           │
│                                          │
│ 192.168.1.1                     [活跃]   │
│ C2 Server                                │
│                                          │
│ 关联组织: APT41 → (链接到组织详情)        │
│ 恶意软件: ShadowPad                      │
│ 地理位置: Germany                        │
│ ASN: AS12345                             │
│                                          │
│ 时间线:                                  │
│ 首次发现: 2026-06-01                     │
│ 最近活跃: 2026-06-15                     │
│                                          │
│ 来源证据:                                │
│ • ThreatFox — https://...                │
└──────────────────────────────────────────┘
```

### 2.3 Malware Detail Page (`/threat-intel/malware/:id`)

**Component**: `MalwareDetailPage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ [← 返回木马列表]                         │
│                                          │
│ ShadowPad                       [后门]   │
│ 别名: Sandbox                            │
│                                          │
│ 关联组织: APT41 → (链接)                 │
│ 目标平台: Windows                        │
│                                          │
│ 样本哈希 (2):                            │
│ ┌──────────────────────────────────────┐ │
│ │ SHA256: def456...  来源: MalwareBazaar│ │
│ │ SHA256: jkl012...  来源: MalwareBazaar│ │
│ └──────────────────────────────────────┘ │
│                                          │
│ YARA规则: ShadowPad_Generic              │
│                                          │
│ 时间线:                                  │
│ 首次发现: 2017-01-01                     │
│ 最近活跃: 2026-06-15                     │
└──────────────────────────────────────────┘
```

### 2.4 Detail Page Common Patterns

- **Back button**: `← 返回<entity>列表` links to the list page.
- **External links**: All `source_refs[].url` open in new window (`target="_blank"`), display source domain name.
- **Empty fields**: Display `—` (em dash) for null/empty values, never `null` or `undefined`.
- **CVSS display**: If `cvss_score` is null but `is_cisa_kev=true`, show `待补充` with tooltip "因在CISA KEV中而提升为high".
- **Loading state**: Skeleton placeholder while fetching.
- **Error state**: If 404, show "未找到" with back button.

### 2.5 Frontend API Client Extension

Add to `threat-intel-client.ts`:

```typescript
// ── Detail Types ──────────────────────────────────────────────────────

export interface ThreatVulnDetail extends ThreatVulnSummary {
  description: string | null;
  affected_products: string[];
  sources: string[];
  source_refs: SourceRef[];
  tags: string[];
  exploiting_groups: {
    group_id: string;
    group_name: string;
    relationship_type: string;
    confidence: number;
    last_seen: string | null;
  }[];
  last_ingested_at: string;
  created_at: string;
  updated_at: string;
}

export interface ThreatInfraIPDetail extends ThreatInfraIPSummary {
  group_name: string | null;
  source_refs: SourceRef[];
  tags: string[];
  last_ingested_at: string;
  created_at: string;
}

export interface MalwareFamilyDetail extends MalwareFamilySummary {
  group_name: string | null;
  aliases: string[];
  description: string | null;
  sample_hashes: { md5?: string; sha256?: string; source: string }[];
  yara_rules: string[];
  source_refs: SourceRef[];
  tags: string[];
  last_ingested_at: string;
  created_at: string;
}

// ── Detail API Functions ──────────────────────────────────────────────

export async function fetchVulnDetail(token: string, vulnId: string): Promise<ThreatVulnDetail> {
  return request<ThreatVulnDetail>(`${BASE}/vulns/${vulnId}`, token);
}

export async function fetchIPDetail(token: string, ipId: string): Promise<ThreatInfraIPDetail> {
  return request<ThreatInfraIPDetail>(`${BASE}/ips/${ipId}`, token);
}

export async function fetchMalwareDetail(token: string, malwareId: string): Promise<MalwareFamilyDetail> {
  return request<MalwareFamilyDetail>(`${BASE}/malware/${malwareId}`, token);
}
```

---

## 3. Watchlist Management UI

### 3.1 Location

New page: `/threat-intel/watchlist` — or a dedicated section in the Groups page.

**Recommended**: Dedicated page accessible from the Overview "关注组织动态" card and from Navbar sub-menu.

### 3.2 Component: `WatchlistPage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ 关注组织管理                              │
│                                          │
│ [搜索框]                    共 12 个组织  │
│                                          │
│ ┌──────────────────────────────────────┐ │
│ │ ★ APT41              [移除] [备注]   │ │
│   别名: Winnti, Barium                  │ │
│   备注: 重点关注C2活动                   │ │
│   最近活动: 2个新C2 IP (6月16日)         │ │
│ ├──────────────────────────────────────┤ │
│ │ ★ 海莲花 (APT-C-00)   [移除] [备注]   │ │
│   别名: OceanLotus, APT32               │ │
│   备注: —                               │ │
│   最近活动: 无                           │ │
│ └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### 3.3 Features

| Feature | Implementation |
|---------|---------------|
| List watched groups | `GET /groups?watched=true` (already in P0) |
| Remove from watchlist | `DELETE /groups/:id/watch` (already in P0) |
| Edit note | `POST /groups/:id/watch` with `{note: "..."}` (upserts note) |
| Search | Client-side filter on name/aliases |
| Activity indicator | Show `activities` from Overview API if group has recent activity |

### 3.4 API

No new API needed — P0 already has `GET /groups?watched=true`, `POST /groups/:id/watch`, `DELETE /groups/:id/watch`.

The `POST /groups/:id/watch` endpoint should be extended to support note updates:

```python
# In handle_watch_group(), note is already accepted from body:
# body = await request.json()
# note = body.get("note")
# This is already implemented in P0 — just ensure the UI uses it.
```

---

## 4. APT Alias Management UI

### 4.1 Location

New page: `/threat-intel/config/aliases` — admin configuration page.

### 4.2 Component: `AliasManagementPage.tsx`

**Layout**:
```
┌──────────────────────────────────────────┐
│ APT别名映射管理                           │
│                                          │
│ [搜索框]  [新增别名]  [批量导入]          │
│                                          │
│ ┌──────────────────────────────────────┐ │
│ │ 别名       命名机构  关联组织  置信度  │ │
│ │ 海莲花      奇安信    G0040    0.95   │ │
│ │ APT-C-00   360       G0040    0.95   │ │
│ │ Winnti     Kaspersky G0044    0.85   │ │
│ │ ...                                  │ │
│ └──────────────────────────────────────┘ │
│                                          │
│ 批量导入:                                │
│ ┌──────────────────────────────────────┐ │
│ │ [拖拽CSV文件或点击上传]               │ │
│ │ 格式: alias_name,naming_org,mitre_id │ │
│ └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### 4.3 Features

| Feature | API | Notes |
|---------|-----|-------|
| List aliases | `GET /config/aliases` (P0) | Already returns all aliases |
| Add alias | `POST /config/aliases` (P0) | Body: `{alias_name, group_id, naming_org, confidence, source_url}` |
| Search | Client-side filter | Filter by alias_name or naming_org |
| Batch import | `POST /config/aliases/batch` (NEW) | Accept CSV/JSON array, upsert each |

### 4.4 Batch Import API (NEW)

```
POST /api/threat-intel/config/aliases/batch
Content-Type: application/json

{
  "aliases": [
    {"alias_name": "海莲花", "mitre_id": "G0040", "naming_org": "奇安信", "confidence": 0.95},
    {"alias_name": "蔓灵花", "mitre_id": "G0094", "naming_org": "奇安信", "confidence": 0.9}
  ]
}
```

**Response**:
```json
{
  "total": 10,
  "inserted": 6,
  "updated": 4,
  "failed": 0,
  "errors": []
}
```

**Handler**:
```python
async def handle_batch_import_aliases(request: web.Request) -> web.Response:
    """POST /api/threat-intel/config/aliases/batch — batch upsert APT aliases."""
    await _ensure_engine()
    body = await request.json()
    aliases = body.get("aliases", [])
    if not aliases or not isinstance(aliases, list):
        return _error(400, "invalid_body", "Field 'aliases' must be a non-empty array")

    # Build mitre_id → group_id lookup
    async with get_session() as session:
        result = await session.execute(select(ThreatGroup.id, ThreatGroup.mitre_id))
        mitre_to_group = {row.mitre_id: row.id for row in result if row.mitre_id}

        inserted = 0
        updated = 0
        failed = 0
        errors = []

        for entry in aliases:
            try:
                alias_name = entry.get("alias_name", "").strip()
                if not alias_name:
                    failed += 1
                    errors.append({"alias_name": "(empty)", "error": "alias_name is required"})
                    continue

                mitre_id = entry.get("mitre_id")
                group_id = mitre_to_group.get(mitre_id) if mitre_id else entry.get("group_id")

                alias, created = await upsert_apt_alias(
                    session,
                    alias_name=alias_name,
                    group_id=group_id,
                    naming_org=entry.get("naming_org"),
                    confidence=entry.get("confidence", 0.8),
                    source_url=entry.get("source_url"),
                )
                if created:
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                failed += 1
                errors.append({"alias_name": entry.get("alias_name", "?"), "error": str(exc)})

    return web.json_response({
        "total": len(aliases),
        "inserted": inserted,
        "updated": updated,
        "failed": failed,
        "errors": errors,
    })
```

### 4.5 CSV Import Format

Frontend parses CSV client-side and sends as JSON:

```csv
alias_name,naming_org,mitre_id,confidence
海莲花,奇安信,G0040,0.95
APT-C-00,360,G0040,0.95
蔓灵花,奇安信,G0094,0.9
```

---

## 5. Feed Pull Failure Notification

### 5.1 Trigger

When a Feed Pull Run finishes with `status="failed"`, emit a WebSocket event to connected WebUI clients.

### 5.2 WebSocket Event

```json
{
  "type": "agent_event",
  "event_type": "threat_intel_feed_failed",
  "data": {
    "source": "nvd",
    "run_id": "01HQ...",
    "error_message": "NVD API rate limit exceeded",
    "started_at": "2026-06-16T08:00:00Z",
    "failed_at": "2026-06-16T08:01:23Z"
  }
}
```

### 5.3 Backend Implementation

In `finish_feed_pull_run()`, after setting status to `failed`, broadcast event:

```python
# In repo.py or scheduler.py, after finish_feed_pull_run with status="failed":
if status == "failed":
    # Broadcast to WebSocket clients
    from secbot.bus import get_bus
    bus = get_bus()
    await bus.broadcast({
        "type": "agent_event",
        "event_type": "threat_intel_feed_failed",
        "data": {
            "source": source,
            "run_id": run_id,
            "error_message": error_message,
            "started_at": started_at.isoformat(),
            "failed_at": _utcnow().isoformat(),
        }
    })
```

> **Note**: Use the existing `secbot.bus` event system. The event type `threat_intel_feed_failed` is new but follows the `agent_event` protocol.

### 5.4 Frontend Handling

In the WebUI WebSocket handler, add a case for `threat_intel_feed_failed`:

```typescript
// In useWebSocket or message handler:
case "threat_intel_feed_failed":
  // Show toast notification
  toast({
    title: "Feed拉取失败",
    description: `${event.data.source} 拉取失败: ${event.data.error_message}`,
    variant: "destructive",
  });
  // If on FeedsPage, refresh the list
  if (location.pathname === "/threat-intel/feeds") {
    refetchFeedRuns();
  }
  // If on OverviewPage, refresh freshness data
  if (location.pathname === "/threat-intel") {
    refetchOverview();
  }
  break;
```

### 5.5 Notification Scope

- Only `status="failed"` triggers notification. `status="partial"` does NOT (partial success is expected).
- Notification is a toast, not a blocking alert.
- User can dismiss the toast; it does not persist.

---

## 6. Industry CPE Management UI

### 6.1 Location

New page: `/threat-intel/config/industry-cpes` — admin configuration page.

### 6.2 Component: `IndustryCPEPage.tsx`

**Features**:
- List all CPE entries (P0 API: `GET /config/industry-cpes`)
- Add new CPE (P0 API: `POST /config/industry-cpes`)
- Filter by `industry_tag` (maritime/transport/scada/port)
- Delete CPE entry (NEW API: `DELETE /config/industry-cpes/:id`)

### 6.3 Delete API (NEW)

```python
async def handle_delete_industry_cpe(request: web.Request) -> web.Response:
    """DELETE /api/threat-intel/config/industry-cpes/{id} — remove an industry CPE."""
    await _ensure_engine()
    cpe_id = int(request.match_info["id"])
    async with get_session() as session:
        result = await session.execute(
            select(IndustryCPE).where(IndustryCPE.id == cpe_id)
        )
        cpe = result.scalar_one_or_none()
        if cpe is None:
            return _error(404, "not_found", f"Industry CPE {cpe_id} not found")
        await session.delete(cpe)
    return web.json_response({"id": cpe_id, "deleted": True})
```

---

## 7. Route Registration Summary

New routes to add in `register_routes()`:

```python
# Detail pages (P1)
router.add_get("/api/threat-intel/vulns/{id}", handle_get_vuln_detail)
router.add_get("/api/threat-intel/ips/{id}", handle_get_ip_detail)
router.add_get("/api/threat-intel/malware/{id}", handle_get_malware_detail)

# Batch import (P1)
router.add_post("/api/threat-intel/config/aliases/batch", handle_batch_import_aliases)

# CPE delete (P1)
router.add_delete("/api/threat-intel/config/industry-cpes/{id}", handle_delete_industry_cpe)
```

---

## 8. Forbidden Patterns

| Pattern | Why Forbidden | Do Instead |
|---------|--------------|------------|
| Detail page fetching list + client-side filter | Wasteful, slow for large datasets | Use dedicated `GET /:id` endpoint |
| Toast notification for `partial` status | Partial is expected (unmapped records) | Only notify on `failed` |
| Blocking alert for feed failure | User cannot dismiss | Use dismissible toast |
| CPE management without delete | Users cannot remove incorrect entries | Add `DELETE` endpoint |
| Batch import without error reporting | Silent failures confuse users | Return per-entry errors array |

---

## 9. Tests Required

### Backend

- [ ] **Vuln detail**: Returns full vuln + exploiting_groups + source_refs.
- [ ] **IP detail**: Returns full IP + group_name.
- [ ] **Malware detail**: Returns full malware + sample_hashes (not truncated).
- [ ] **404 on missing**: Detail endpoints return 404 for non-existent IDs.
- [ ] **Batch alias import**: 10 aliases → 6 inserted, 4 updated, 0 failed.
- [ ] **Batch alias with errors**: Invalid entries counted in `failed` with error messages.
- [ ] **CPE delete**: Existing CPE deleted, non-existent returns 404.

### Frontend

- [ ] **Vuln detail page**: All fields render, source refs clickable.
- [ ] **CVSS 待补充**: Null CVSS + KEV shows "待补充" with tooltip.
- [ ] **Watchlist page**: List, remove, edit note all work.
- [ ] **Alias management**: List, add, batch import CSV work.
- [ ] **Feed failure toast**: Failed pull triggers dismissible toast.

---

## Origin

Source: `docs/prd-threat-intelligence.md` §6 (API routes) + §7.2 (page structures) + P0 API baseline (`threat_intel_routes.py`).
