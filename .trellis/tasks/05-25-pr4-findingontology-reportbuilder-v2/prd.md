# PR4: FindingOntology + ReportBuilder v2

## Goal

实现统一的 Finding 数据模型（ontology）和 skill 输出归一化适配层，让所有 skill 的 findings 输出符合统一的结构化 schema，并更新 ReportBuilder 使用新的 Finding 模型。

**为什么需要这个**：
- 当前每个 skill 的 `SkillResult.findings[]` 是自由 JSON 格式，没有统一结构
- ReportBuilder 需要各自解析不同格式，维护成本高
- 无法统一进行严重性评级、修复建议、知识库检索
- Pi orchestrator 需要统一的 Finding 格式来进行 triage 和决策

## What I already know

从代码库检查发现：

1. **现有 Skill 结构** (`secbot/skills/types.py`)
   - `SkillResult` 包含 `findings: list[dict[str, Any]]` 字段
   - 每个 skill 返回的 findings 格式不同（自由 JSON）
   - 例如 nuclei 返回：`{"template_id", "severity", "host", "matched_at", "name"}`

2. **现有 CMDB 结构** (`secbot/cmdb/models.py`)
   - 已有 `Vulnerability` 表，但字段不完整
   - 缺少 CWE、OWASP category、confidence、evidence 关联等字段
   - 需要新建 `findings_v2` 表

3. **现有 ReportBuilder** (`secbot/report/builder.py`)
   - 使用 `ReportFinding` dataclass（简化版）
   - 从 CMDB `vulnerability` 表读取数据
   - 需要更新为使用新的 Finding ontology

4. **Blackboard 集成点**
   - `BlackboardEntry(kind="finding")` 已在 PR1 定义
   - 需要在 `Blackboard.write` 中添加 finding 验证和双写逻辑

5. **规范文档** (`.trellis/spec/backend/finding-ontology.md`)
   - 完整定义了 Finding schema（11 个核心字段 + 元数据）
   - 定义了 Adapter protocol 和内置 adapter 列表
   - 定义了 CWE/OWASP 查表机制和 severity matrix

## Requirements

### 1. Finding Ontology 核心

**1.1 Finding dataclass** (`secbot/ontology/finding.py`)
- 定义 `Finding` frozen dataclass，包含：
  - 标识：`id`, `chat_id`
  - 内容：`title` (≤120 chars), `description` (≤4000 chars, markdown)
  - 分类：`cwe: tuple[str, ...]`, `owasp_category: Optional[str]`, `asset_type`, `impact_type`
  - 评级：`severity`, `severity_score: Optional[float]`, `confidence`
  - 关联：`asset_ref`, `evidence_ids: tuple[str, ...]`, `chain_of`, `hypothesis_id`
  - 修复：`remediation_ref`, `retest_steps`
  - 状态：`status` (draft/confirmed/false_positive/wont_fix/fixed)
  - 元数据：`source_tool`, `discovered_at`, `confirmed_at`

**1.2 类型定义**
- `Severity = Literal["info", "low", "medium", "high", "critical"]`
- `Confidence = Literal["low", "medium", "high"]`
- `AssetType = Literal["host", "service", "http_endpoint", "credential", "cloud_resource", "dns_record", "container", "code_snippet", "other"]`
- `ImpactType = Literal["rce", "lfi", "rfi", "sqli", "xss", "ssrf", "ssti", "auth_bypass", "authz_bypass", "idor", "csrf", "info_disclosure", "credential_leak", "open_redirect", "ddos", "supply_chain", "config_weakness", "weak_crypto", "business_logic", "other"]`

**1.3 序列化方法**
- `Finding.to_dict() -> dict[str, Any]` - 转换为 JSON-serializable dict
- `Finding.to_row() -> dict[str, Any]` - 转换为 SQLite row（JSON 字段序列化）
- `Finding.from_dict(data: dict) -> Finding` - 从 dict 构造

### 2. SQLite Schema

**2.1 新建 `findings_v2` 表**
- 包含所有 Finding 字段
- JSON 字段：`cwe`, `evidence_ids`, `chain_of`
- 索引：`(chat_id, discovered_at)`, `(chat_id, severity)`, `(chat_id, status)`

**2.2 与旧表共存**
- 保留旧 `vulnerability` 表只读
- 新写都进 `findings_v2`
- Feature flag `report.use_v2` 控制 ReportBuilder 读取哪个表

### 3. Skill 输出归一化 Adapter

**3.1 Adapter Protocol** (`secbot/ontology/adapters/__init__.py`)
```python
class SkillFindingAdapter(Protocol):
    skill_name: str
    
    def map(
        self,
        raw: Mapping[str, Any],
        *,
        chat_id: str,
        evidence_id: Optional[str],
        source_tool: str,
    ) -> Finding: ...
    
    def confidence_floor(self) -> Confidence: ...
```

**3.2 内置 Adapters** (`secbot/ontology/adapters/`)
实现以下 skill 的 adapter（按优先级）：
1. `nuclei.py` - NucleiAdapter (confidence=high)
2. `sqlmap.py` - SqlmapDetectAdapter (confidence=high, impact_type=sqli)
3. `hydra.py` - HydraAdapter (confidence=high, impact_type=auth_bypass)
4. `vuln_detec.py` - VulnDetecAdapter (confidence=medium)
5. `fscan.py` - FscanVulnAdapter (confidence=medium)
6. `default.py` - DefaultAdapter (fallback, confidence=low, status=draft)

**3.3 Adapter Registry**
- `get_adapter(skill_name: str) -> SkillFindingAdapter`
- 未注册的 skill 使用 DefaultAdapter
- Fallback 时写 event_log 记录

### 4. CWE / OWASP 查表

**4.1 静态映射文件** (`secbot/ontology/`)
- `cwe_index.json` - CWE-ID → {name, owasp_category, suggested_impact_type}
- `owasp_2021.json` - OWASP Top 10 2021 metadata
- `template_to_cwe.json` - nuclei template-id → CWE-IDs
- `severity_matrix.json` - (impact_type, asset_type) → severity baseline

**4.2 Severity 推断逻辑**
- 优先使用 raw finding 的 severity 字段
- 缺省时按 severity_matrix 推断
- 最低 floor 为 "info"

### 5. Blackboard 集成

**5.1 Finding 验证** (`secbot/agent/blackboard.py`)
- 在 `Blackboard.write(kind="finding")` 时调用 `validate_finding(payload)`
- 验证必填字段和类型
- 验证 severity/confidence/asset_type/impact_type 枚举值

**5.2 双写机制**
- `Blackboard.write(kind="finding")` 同步写入 `findings_v2` 表
- 双写失败时：blackboard entry 仍写入，event_log 记录错误
- 下次启动时 reconcile（V2 feature）

### 6. ReportBuilder v2

**6.1 新的 ReportInput** (`secbot/report/builder.py`)
```python
@dataclass
class ReportInput:
    scan_id: str
    chat_id: str
    scope: ScopeContract
    findings: list[Finding]  # status in {confirmed, draft}
    evidence: dict[str, EvidenceRecord]
    blockers: list[str]
    next_steps: list[str]
    metadata: dict[str, Any]
```

**6.2 渲染分段**
1. Executive Summary - 按 severity 统计 + top 3 严重 finding
2. Findings - 按 severity desc 排序，每条含 finding + evidence + remediation
3. Evidence Appendix - evidence.summary + raw_ref 链接
4. Risk Rating - severity matrix 表
5. Remediation - 按 remediation_ref 聚合
6. Retest Notes - retest_steps 汇总
7. Methodology - phase history + budget usage

**6.3 更新 report-html skill**
- 接受新的 ReportInput 结构
- 从 `findings_v2` 表读取数据（当 `report.use_v2=true`）
- 保留旧路径兼容（feature flag 控制）

### 7. Worker → Pi Promotion Flow

**7.1 Worker 写 hypothesis**
- Worker 调用 skill 后，通过 adapter 转换为 Finding
- Worker 写入 blackboard 为 `kind="hypothesis"`（不是 finding）
- PolicyEngine 的 CallerKindRule 阻止 worker 直接写 finding

**7.2 Pi promote finding**
- Pi 调用 `promote_finding(hypothesis_id)` tool
- 从 hypothesis 提升为 confirmed finding
- 写入 blackboard `kind="finding"` + 双写 `findings_v2`

## Acceptance Criteria

- [ ] `Finding` dataclass 定义完整，包含所有必填字段
- [ ] `findings_v2` SQLite 表创建成功，包含索引
- [ ] 至少实现 6 个 skill adapter（nuclei, sqlmap, hydra, vuln_detec, fscan, default）
- [ ] Adapter registry 正确返回对应 adapter，未注册时返回 DefaultAdapter
- [ ] CWE/OWASP 查表文件存在且格式正确（至少覆盖 CWE Top 25）
- [ ] Severity matrix 推断逻辑正确
- [ ] `Blackboard.write(kind="finding")` 验证 payload 并双写 `findings_v2`
- [ ] ReportBuilder v2 从 `findings_v2` 读取数据并正确渲染 7 个分段
- [ ] Worker → hypothesis → Pi promote → finding 流程测试通过
- [ ] 所有测试通过（至少 15 个新测试）

## Definition of Done

- Tests added/updated (unit/integration where appropriate)
- Lint / typecheck / CI green
- Docs/notes updated if behavior changes
- Feature flag `report.use_v2` 默认为 true
- 旧 `vulnerability` 表保留只读（兼容性）

## Technical Approach

### 实现顺序

**Phase 1: Ontology 核心**
1. 创建 `secbot/ontology/` 目录结构
2. 实现 `Finding` dataclass + 序列化方法
3. 创建 SQLite migration（`findings_v2` 表）
4. 创建静态映射文件（cwe_index.json 等）

**Phase 2: Adapter 层**
1. 定义 `SkillFindingAdapter` Protocol
2. 实现 6 个内置 adapter
3. 实现 adapter registry + fallback 逻辑
4. 添加 adapter 单元测试

**Phase 3: Blackboard 集成**
1. 在 `Blackboard.write` 添加 finding 验证
2. 实现双写 `findings_v2` 逻辑
3. 添加 event_log 错误记录
4. 测试 worker → hypothesis → Pi promote 流程

**Phase 4: ReportBuilder v2**
1. 定义新的 `ReportInput` dataclass
2. 更新 `build_report_model` 从 `findings_v2` 读取
3. 更新 HTML 渲染逻辑（7 个分段）
4. 更新 `report-html` skill handler
5. 添加 feature flag 控制

**Phase 5: 测试 + 文档**
1. 添加集成测试（完整流程）
2. 更新相关文档
3. 验证所有 acceptance criteria

## Out of Scope

- ❌ CVSS v3.1 完整向量计算（仅记录 severity_score placeholder）
- ❌ NVD/CVE 数据接入（V2 KnowledgeBase 范畴）
- ❌ 强制旧 skill 立即归一（通过 adapter 自动映射）
- ❌ 删除旧 `vulnerability` 表（保留兼容）
- ❌ Finding 持久化到外部系统（仅本地 SQLite）
- ❌ Reconcile 机制（双写失败恢复，V2 feature）
- ❌ Finding 去重逻辑（V2 feature）
- ❌ Chain-of 循环引用检测（简化版：最多深度 5）

## Technical Notes

### 文件清单

**新建文件**：
- `secbot/ontology/__init__.py`
- `secbot/ontology/finding.py` - Finding dataclass + 序列化
- `secbot/ontology/cwe_index.json` - CWE 查表（~200 行，覆盖 Top 25）
- `secbot/ontology/owasp_2021.json` - OWASP Top 10 metadata
- `secbot/ontology/template_to_cwe.json` - Nuclei template 映射
- `secbot/ontology/severity_matrix.json` - Severity 推断矩阵
- `secbot/ontology/adapters/__init__.py` - Adapter protocol + registry
- `secbot/ontology/adapters/nuclei.py`
- `secbot/ontology/adapters/sqlmap.py`
- `secbot/ontology/adapters/hydra.py`
- `secbot/ontology/adapters/vuln_detec.py`
- `secbot/ontology/adapters/fscan.py`
- `secbot/ontology/adapters/default.py`
- `tests/ontology/test_finding.py`
- `tests/ontology/test_adapters.py`
- `tests/integration/test_finding_promotion.py`

**修改文件**：
- `secbot/agent/blackboard.py` - 添加 finding 验证 + 双写
- `secbot/report/builder.py` - 新增 ReportInput + 更新 build_report_model
- `secbot/report/render.py` - 更新 HTML 渲染逻辑
- `secbot/skills/report-html/handler.py` - 接受新 ReportInput
- `secbot/cmdb/models.py` - 可能需要添加 findings_v2 ORM model（可选）

### 依赖关系

- 依赖 PR1（StructuredBlackboard）- `kind="finding"` 已定义
- 依赖 PR2（PolicyEngine）- CallerKindRule 阻止 worker 写 finding
- 依赖 PR3（BudgetTracker）- ReportBuilder metadata 包含 budget summary
- 被 PR5（EventStream）依赖 - event_log 记录 adapter fallback

### 约束

- Python 3.10+ 兼容
- SQLite 3.35+ (JSON 函数支持)
- 保持向后兼容（旧 skill 通过 DefaultAdapter 自动映射）
- Feature flag 控制新旧路径切换

### 参考文档

- `.trellis/spec/backend/finding-ontology.md` - 完整规范
- `.trellis/spec/backend/structured-blackboard.md` - Blackboard kind 定义
- `.trellis/spec/backend/policy-engine.md` - CallerKindRule
- OWASP Top 10 (2021) - https://owasp.org/Top10/
- MITRE CWE Top 25 - https://cwe.mitre.org/top25/
