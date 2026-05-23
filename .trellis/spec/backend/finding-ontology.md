# Finding Ontology — 统一 finding 数据模型 + skill 输出归一

> **Status**: DRAFT (not implemented)
> **Implements**: PRD AC5 + Pi Agent.md §5「Finding Ontology = CWE / OWASP / asset / impact / confidence」
> **Code PR**: PR4 (FindingOntology + ReportBuilder v2)
> **Open issues**:
> - 是否引入 CVSS v3.1 计分（增加复杂度，先 placeholder）

---

## 1. Goal

现状：每个 skill 的 `SkillResult.findings[]` 是**自由 JSON**（见
`secbot/skills/types.py::SkillResult`），ReportBuilder 各做各的解析。

目标：定义统一 `Finding` ontology + skill 输出归一适配层，让 ReportBuilder / KB
检索 / 严重性评级 / 修复建议都能消费同一形状。

呼应 Pi Agent.md §5 末尾：
> Finding Ontology — CWE / OWASP category / asset type / impact type / confidence
> score

## 2. Non-Goals

- 不替换 SQLite findings 表的现有列；新增 `findings_v2` 表共存
- 不强制旧 skill handler 立即归一（PR4 提供适配 layer；旧 skill 输出由 layer
  自动 best-effort 映射）
- 不引入 CVSS 完整向量；仅记一个最终 severity 字符串 + score
- 不接 NVD/CVE 数据（V2 KnowledgeBase 范畴）

## 3. Schema

### 3.1 `Finding` 主结构

```python
from typing import Literal, Optional

Severity = Literal["info", "low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]
AssetType = Literal[
    "host", "service", "http_endpoint", "credential",
    "cloud_resource", "dns_record", "container", "code_snippet", "other",
]
ImpactType = Literal[
    "rce", "lfi", "rfi", "sqli", "xss", "ssrf", "ssti",
    "auth_bypass", "authz_bypass", "idor", "csrf",
    "info_disclosure", "credential_leak", "open_redirect",
    "ddos", "supply_chain", "config_weakness", "weak_crypto",
    "business_logic", "other",
]

@dataclass(frozen=True, slots=True)
class Finding:
    # ---- 标识 ----
    id: str                          # 12-char uuid; 与 BlackboardEntry.id 一致
    chat_id: str
    # ---- 内容 ----
    title: str                       # ≤ 120 chars
    description: str                 # ≤ 4000 chars (markdown 允许)
    # ---- 分类 ----
    cwe: tuple[str, ...]             # e.g. ("CWE-89", "CWE-20")
    owasp_category: Optional[str]    # e.g. "A03:2021-Injection"
    asset_type: AssetType
    impact_type: ImpactType
    # ---- 评级 ----
    severity: Severity
    severity_score: Optional[float]  # 0.0-10.0, optional CVSS-like
    confidence: Confidence
    # ---- 关联 ----
    asset_ref: str                   # human-readable, e.g. "https://app.example.com/api/v1/orders/{id}"
    evidence_ids: tuple[str, ...]    # EvidenceStore ids
    chain_of: tuple[str, ...] = ()   # parent finding ids（链式利用）
    hypothesis_id: Optional[str] = None  # 从哪个 hypothesis promote 来
    # ---- 修复 ----
    remediation_ref: Optional[str] = None    # KB 文档 id 或 inline summary
    retest_steps: Optional[str] = None
    # ---- 状态 ----
    status: Literal["draft", "confirmed", "false_positive", "wont_fix", "fixed"] = "confirmed"
    # ---- 元 ----
    source_tool: str                 # skill name / 'pi-manual' / 'worker:<id>'
    discovered_at: float
    confirmed_at: Optional[float] = None
```

### 3.2 SQLite Schema

```sql
CREATE TABLE findings_v2 (
  id                TEXT PRIMARY KEY,
  chat_id           TEXT NOT NULL,
  title             TEXT NOT NULL,
  description       TEXT NOT NULL,
  cwe               TEXT NOT NULL,         -- JSON list
  owasp_category    TEXT,
  asset_type        TEXT NOT NULL,
  impact_type       TEXT NOT NULL,
  severity          TEXT NOT NULL,
  severity_score    REAL,
  confidence        TEXT NOT NULL,
  asset_ref         TEXT NOT NULL,
  evidence_ids      TEXT NOT NULL DEFAULT '[]',     -- JSON list
  chain_of          TEXT NOT NULL DEFAULT '[]',     -- JSON list
  hypothesis_id     TEXT,
  remediation_ref   TEXT,
  retest_steps      TEXT,
  status            TEXT NOT NULL DEFAULT 'confirmed',
  source_tool       TEXT NOT NULL,
  discovered_at     REAL NOT NULL,
  confirmed_at      REAL
);

CREATE INDEX idx_findings_v2_chat ON findings_v2 (chat_id, discovered_at);
CREATE INDEX idx_findings_v2_severity ON findings_v2 (chat_id, severity);
CREATE INDEX idx_findings_v2_status ON findings_v2 (chat_id, status);
```

### 3.3 Blackboard 联动

`BlackboardEntry(kind="finding", payload={...})` 的 payload 严格匹配上表必填字
段。`secbot/agent/blackboard.py::Blackboard.write` 在 kind=finding 时调用
`finding_validator.validate(payload)` 并把 finding 同步插入 `findings_v2`
（双写）。

## 4. Skill 输出归一 Adapter

### 4.1 `SkillFindingAdapter` Protocol

```python
class SkillFindingAdapter(Protocol):
    """Map a single skill's raw finding dict to canonical Finding."""

    skill_name: str

    def map(
        self,
        raw: Mapping[str, Any],
        *,
        chat_id: str,
        evidence_id: Optional[str],
        source_tool: str,
    ) -> Finding: ...

    def confidence_floor(self) -> Confidence:
        """Skill-wide confidence cap (e.g. scanner-only -> low)."""
```

### 4.2 内置 Adapter

| Skill | Adapter | confidence_floor | 备注 |
|---|---|---|---|
| `nuclei-template-scan` | `NucleiAdapter` | high | 直接读 nuclei JSON 字段（template-id → CWE 查表）|
| `sqlmap-detect` | `SqlmapDetectAdapter` | high | impact_type=sqli |
| `vuln-detec-manual` | `VulnDetecAdapter` | medium | 读 confidence 字段 |
| `fscan-vuln-scan` | `FscanVulnAdapter` | medium | 解析 fscan output |
| `httpx-probe` | `HttpxAdapter` | low | impact_type=info_disclosure（默认） |
| `qscan-port-scan` | `PortAdapter` | low | impact_type=info_disclosure，severity=info |
| `qscan-host-discovery` | `HostAdapter` | low | 同上 |
| `katana-crawl-web` | `CrawlAdapter` | low | 仅生成 asset，不直接 finding |
| `hydra-bruteforce` | `HydraAdapter` | high | impact_type=auth_bypass，severity=critical when success |
| `ffuf-*` | `FfufAdapter` | low | impact_type=info_disclosure |
| `report-html` | （无 finding 输出） | — | — |

新 skill 加入时**必须**提供 adapter（PR4 lint 检查）。

### 4.3 Best-effort Fallback

若 skill 未注册 adapter（旧 skill 或第三方）：

```python
class DefaultAdapter(SkillFindingAdapter):
    def map(self, raw, *, chat_id, evidence_id, source_tool):
        return Finding(
            id=str(uuid4())[:12],
            chat_id=chat_id,
            title=raw.get("title") or raw.get("name") or "unknown finding",
            description=raw.get("description") or json.dumps(raw, ensure_ascii=False)[:4000],
            cwe=tuple(raw.get("cwe", [])),
            owasp_category=raw.get("owasp_category"),
            asset_type=raw.get("asset_type", "other"),
            impact_type=raw.get("impact_type", "other"),
            severity=raw.get("severity", "low"),
            severity_score=None,
            confidence="low",     # fallback always low
            asset_ref=raw.get("url") or raw.get("host") or "unknown",
            evidence_ids=(evidence_id,) if evidence_id else (),
            source_tool=source_tool,
            discovered_at=time.time(),
            status="draft",       # fallback always draft (待 Pi 确认)
        )
```

Fallback 触发时写 `event_log(kind="finding_adapter_fallback", payload={skill, ...})`，
便于后续补 adapter。

## 5. CWE / OWASP 查表

### 5.1 静态映射文件

```
secbot/ontology/
  cwe_index.json          # CWE-ID → {name, owasp_category, suggested_impact_type}
  owasp_2021.json         # OWASP Top 10 2021 metadata
  template_to_cwe.json    # nuclei template-id → CWE-IDs（按 nuclei community 仓库整理）
  severity_matrix.json    # impact_type × asset_type → severity baseline
```

MVP 不接 NVD；CWE 表用静态 JSON（覆盖 CWE Top 25 即可），增量补全。

### 5.2 severity 推断

`severity_matrix.json` 提供 (impact_type, asset_type) → severity 基线：

```json
{
  "rce": {"host": "critical", "service": "critical", "http_endpoint": "critical"},
  "sqli": {"http_endpoint": "high", "service": "medium"},
  "xss": {"http_endpoint": "medium"},
  "info_disclosure": {"http_endpoint": "low", "credential": "high"},
  ...
}
```

`Adapter.map` 先尝试 raw 字段；缺省时按 matrix 推断；最低 floor `info`。

## 6. ReportBuilder v2 输入

```python
class ReportInput(BaseModel):
    scan_id: str
    chat_id: str
    scope: ScopeContract
    findings: list[Finding]                 # status in {confirmed, draft}
    evidence: dict[str, EvidenceRecord]     # evidence_id → record
    blockers: list[str]
    next_steps: list[str]
    metadata: dict[str, Any]                # budget summary, phase history, ...
```

ReportBuilder 渲染分段：

1. **Executive Summary** —— 按 severity 统计 + top 3 严重 finding 一句话
2. **Findings** —— 按 severity desc 列出；每条含 finding + evidence + remediation
3. **Evidence Appendix** —— `evidence.summary` + 链接到 raw_ref
4. **Risk Rating** —— matrix 表
5. **Remediation** —— 按 finding.remediation_ref 聚合
6. **Retest Notes** —— retest_steps 汇总
7. **Methodology** —— phase history + budget usage（来自 event_log replay）

现有 `secbot/skills/report-html` skill 改为接受 `ReportInput`；旧 `summary_json`
模式保留 1 个 milestone 后删除。

## 7. Error / Edge Cases

| Case | Behavior |
|---|---|
| Adapter map 抛异常 | 降级 DefaultAdapter；写 event_log warn |
| `cwe` 字段无效（不在 CWE_INDEX） | 保留但 ReportBuilder 渲染时加 "未识别" 徽章 |
| `severity` 与 matrix 推断冲突 | 优先 raw；写 event_log 记差异 |
| `confidence` 高于 adapter.confidence_floor | 强制按 floor 截断 |
| 双写 SQLite findings_v2 失败 | 黑板 entry 仍写入；event_log 记 db_write_fail；下次启动 reconcile（V2） |
| `evidence_ids` 含已 GC 的 id | ReportBuilder 渲染 "evidence not available" |
| `chain_of` 循环引用 | 检测后截断（最多深度 5） |

## 8. Migration & Compatibility

### 8.1 与旧 findings 表共存

旧 `findings` 表保留只读；新写都进 `findings_v2`。前端 ReportBuilder v1 路径继
续读旧表（feature flag `report.use_v2=false` 时）。PR4 设 `report.use_v2=true`
默认；旧路径在 V2 删除。

### 8.2 旧 Skill 兼容

旧 skill 不需要改 handler；Adapter 在 `SkillTool.execute` 后挂钩：

```python
async def execute(self, **args):
    result = await self._handler_run(args, ctx)   # SkillResult
    if result.findings:
        adapter = get_adapter(self._meta.name)
        for raw in result.findings:
            finding = adapter.map(raw, chat_id=ctx.chat_id, ...)
            await blackboard.write("worker:<id>", "hypothesis",
                payload=finding_to_hypothesis(finding))
            # 注意：worker 写 hypothesis 不写 finding（PolicyEngine 限制）
    return serialise(result)
```

Pi 在后续 turn 调用 `promote_finding(hypothesis_id)`：

```python
async def promote_finding(hypothesis_id: str) -> str:
    entry = await blackboard.get(hypothesis_id)
    finding = Finding(**entry.payload, status="confirmed",
                       confirmed_at=time.time())
    await blackboard.write("pi", "finding", payload=finding.to_dict())
    db.insert("findings_v2", finding.to_row())
    return finding.id
```

## 9. Test Plan

### Schema

- `test_finding_required_fields`
- `test_severity_matrix_lookup_table`
- `test_cwe_owasp_mapping_consistency`

### Adapters

- `test_nuclei_adapter_maps_high_confidence`
- `test_sqlmap_adapter_sets_sqli_impact`
- `test_hydra_adapter_critical_on_success`
- `test_default_adapter_handles_arbitrary_dict`
- `test_adapter_confidence_floor_enforced`

### Promotion flow

- `test_worker_writes_hypothesis_not_finding`（与 `policy-engine.md` §4.2 复用）
- `test_pi_promote_writes_finding_v2_row`
- `test_promote_links_evidence_ids`

### ReportBuilder

- `test_report_input_v2_renders_sections`
- `test_report_missing_evidence_marker`
- `test_report_v1_v2_feature_flag`

## 10. Implementation Anchors (PR4)

- `secbot/ontology/__init__.py`
- `secbot/ontology/finding.py::Finding` + serialisation
- `secbot/ontology/cwe_index.json` + `severity_matrix.json` + ...
- `secbot/ontology/adapters/__init__.py::get_adapter`
- `secbot/ontology/adapters/{nuclei,sqlmap,vuln_detec,hydra,...}.py`
- `secbot/cmdb/migrations/0008_findings_v2.sql`
- `secbot/skills/report-html/handler.py` (改造接受 ReportInput)
- `secbot/agent/blackboard.py::Blackboard.write` (kind=finding 时双写)

## 11. References

- Pi Agent.md §3（Triage Worker / Knowledge Worker） + §5（Finding Ontology） +
  §6（Phase 6 Triage）
- 关联 spec: `structured-blackboard.md` / `policy-engine.md` /
  `event-stream.md`
- OWASP Top 10 (2021) — used in `owasp_2021.json`
- MITRE CWE Top 25 — seed for `cwe_index.json`
