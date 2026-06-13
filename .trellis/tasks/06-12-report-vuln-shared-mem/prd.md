# brainstorm: report_vulnerability 共享内存漏洞上报重设计

## Goal

重新设计 report_html 流程：子智能体发现漏洞后通过新的 `report_vulnerability` 技能立即写入全局共享内存列表，report_html 直接从该列表读取生成报告。简化数据流，消除 session JSONL 中间解析层的脆弱性。

## What I already know

### 现有数据流（3 跳）
1. **子 agent → asset_push(kind="vuln")** → 写入 `AssetFeed`（内存，asyncio.Lock 加锁）
2. **AgentLoop** → 持久化 `asset_pushed` 事件到 session JSONL 文件
3. **report-html handler** → `build_report_model_from_session_jsonl()` → 解析 JSONL 提取 `asset_push` tool_call 事件 → `build_report_model_from_asset_entries()` → `render_html()`

### 关键组件
- `AssetFeed` (`secbot/agent/asset_feed.py`): 已有 asyncio.Lock 保护的内存列表，per-chat_id 隔离
- `AssetPushTool` (`secbot/agent/tools/asset_feed.py`): 已有 `_vuln_to_cmdb_write()` 转换逻辑
- `Blackboard` (`secbot/agent/blackboard.py`): 自由文本黑板，有 `finding` kind
- `report/builder.py`: `ReportFinding` 数据类（含 severity/category/title/evidence_summary/evidence_detail/evidence_raw/verification_steps/remediation/references）
- `report/session_source.py`: `load_asset_entries_from_session_jsonl()` 解析 JSONL 提取 asset_push 事件
- `report/render.py`: `render_html()` HTML 渲染器

### 用户要求的新数据模型
**必填字段**:
- `title` — LLM 生成描述性标题
- `severity` — critical/high/medium/low/info（HackerOne CVSS 标准）
- `description` — 技术细节和风险描述
- `exploitation_proof` — 实际的命令输出、HTTP 响应或其他验证证据内容
- `verification_method` — 枚举值（manual_test, automated_scan, code_review 等）
- `cvss` — CVSS 评分；若未提供则服务端根据 severity 自动分配默认值

**选填字段**:
- `endpoint` — 受影响的端点路径
- `poc_description` — 概念验证过程描述
- `poc_script_code` — POC 脚本代码
- `remediation_steps` — 修复建议和步骤

## Decision (ADR-lite)

### D1: VulnerabilityStore 独立性
**Context**: 全局漏洞列表应如何实现
**Decision**: 独立 VulnerabilityStore（`secbot/agent/vulnerability_store.py`），不复用 AssetFeed 或 Blackboard
**Consequences**: 新增 Registry + ContextVar 绑定，但获得清晰的职责分离和精确的字段验证

### D2: 数据源优先级
**Context**: report-html 应从哪里读取漏洞数据
**Decision**: VulnerabilityStore 优先，session JSONL 作为 fallback
**Consequences**: 在线场景实时无延迟；离线/历史场景通过 JSONL fallback 保持可用

### D3: 技能替代策略
**Context**: 新旧漏洞上报通道如何过渡
**Decision**: `report_vulnerability` 成为唯一漏洞上报入口；`asset_push(kind="vuln")` 废弃但保持向后兼容
**Consequences**: 子 agent 提示词全部迁移到新技能；旧的 asset_push(kind="vuln") 写入仍被 AssetFeed 接受但 report-html 不再优先读取

### D4: 前端兼容双写
**Context**: 前端资产列表依赖 AssetFeed 的 `kind="vuln"` 条目展示漏洞
**Decision**: `report_vulnerability` 写入 VulnerabilityStore 的同时，自动向 AssetFeed 推一条 `kind="vuln"` 条目
**Consequences**: 子 agent 只需调用一次，前端资产列表 + 报告数据源两端都更新；无需前端改动

## Requirements

### 数据层
* 新建 `VulnerabilityEntry` 数据类，包含用户定义的全部字段（必填 + 选填）
* 新建 `VulnerabilityStore`，asyncio.Lock 保护的内存列表
* 新建 `VulnerabilityStoreRegistry`，per-chat_id 隔离
* CVSS 默认值自动分配（severity → CVSS 映射）
* verification_method 枚举验证

### 工具层
* 新建 `report_vulnerability` 工具（非 skill，是 Tool），接受结构化参数
* `asset_push(kind="vuln")` 保持向后兼容但标记废弃

### 报告层
* report-html handler 优先从 VulnerabilityStore 读取
* 新增 `build_report_model_from_vulnerabilities()` 将 VulnerabilityEntry 列表转为 ReportModel
* JSONL fallback 保留（进程重启后历史报告场景）

### 提示词层
* vuln_scan.md / vuln_detec.md 更新：使用 `report_vulnerability` 替代 `asset_push(kind="vuln")`

## Acceptance Criteria

* [ ] `report_vulnerability` 工具可被 vuln_scan / vuln_detec 子 agent 调用
* [ ] 并发写入场景（多个子 agent 同时上报）线程安全（asyncio.Lock）
* [ ] VulnerabilityStore 通过 ContextVar 在子 agent 间共享
* [ ] report-html 生成的 HTML 包含所有必填字段（title/severity/description/exploitation_proof/verification_method/cvss）
* [ ] CVSS 未提供时根据 severity 自动分配默认值
* [ ] verification_method 仅接受枚举值，非法值被拒绝
* [ ] 进程重启后 report-html 仍可通过 JSONL fallback 生成历史报告
* [ ] 单元测试覆盖并发写入、字段验证、CVSS 默认值分配
* [ ] 现有 asset_push(kind="vuln") 行为不被破坏

## Definition of Done

* Tests added/updated (unit + integration)
* Lint / typecheck / CI green
* 子 agent 提示词同步更新
* 现有 asset_push(kind="vuln") 向后兼容

## Out of Scope

* CMDB 持久化改动（本次仅关注内存层）
* 前端 UI 展示改动
* WebSocket 实时推送漏洞卡片（已有 asset_pushed 事件机制）
* PDF/DOCX 报告格式改动
* report_vulnerability 的 LLM 调用（字段由子 agent LLM 自行填充）

## Technical Notes

### 关键文件
- `secbot/agent/asset_feed.py` — AssetFeed/AssetFeedRegistry（参考模式）
- `secbot/agent/tools/asset_feed.py` — AssetPushTool（参考工具实现）
- `secbot/agent/blackboard.py` — Blackboard/BlackboardRegistry（参考模式）
- `secbot/agent/tools/skill.py` — bind_skill_context / ContextVar 机制
- `secbot/report/builder.py` — ReportFinding / build_report_model_from_asset_entries
- `secbot/report/render.py` — render_html
- `secbot/skills/report-html/handler.py` — report-html handler
- `secbot/report/session_source.py` — JSONL 解析逻辑
- `secbot/agents/prompts/vuln_scan.md` — vuln_scan 提示词
- `secbot/agents/prompts/vuln_detec.md` — vuln_detec 提示词

### CVSS 默认值映射（基于 severity）
| Severity | Default CVSS |
|----------|-------------|
| critical | 9.5 |
| high | 7.5 |
| medium | 5.0 |
| low | 2.5 |
| info | 0.0 |

### verification_method 枚举值
- `automated_scan` — 自动化工具扫描发现
- `manual_test` — 手动测试验证
- `code_review` — 代码审计发现
- `exploit_reproduction` — 漏洞复现验证
- `configuration_audit` — 配置审计发现
