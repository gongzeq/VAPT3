# brainstorm: 威胁情报模块spec文档-P1P2

## Goal

根据 `docs/prd-threat-intelligence.md`，为威胁情报模块的 P1 和 P2 阶段创建 Trellis spec 文档（coding guidelines），用于指导后续开发并注入到 implement/check sub-agent 上下文中。跳过已完成的 P0。

## What I already know

### P0 已完成（不需 spec）
- `secbot/threat_intel/` 后端模块完整：models.py（10张ORM表）、db.py、repo.py、scheduler.py、feeds/（mitre_groups, cisa_kev, threatfox, apt_aliases_seed）
- `secbot/api/threat_intel_routes.py`：17个API端点（overview/groups/ips/vulns/malware/maritime/feeds/config）
- `webui/src/pages/threat-intel/`：5个前端页面（Overview, Groups, GroupDetail, Feeds, ThreatIntelLayout）
- P0 质量加固已完成（28个测试通过、lint清理、i18n完善）

### P1 待开发内容
- 数据接入：NVD CVSS>=7.0、MalwareBazaar、Feodo Tracker、AlienVault OTX、Exploit-DB PoC标记
- 数据接入：Industry CPE匹配与供应链漏洞标记
- 前端：漏洞详情页、攻击IP详情页、木马样本详情页
- 前端：知识图谱全局页（reactflow力导向布局）
- 前端：组织详情页局部图谱（径向布局）
- API：图谱专用聚合接口 `GET /api/threat-intel/graph`
- 功能：Watchlist管理界面、APT别名维护界面与批量导入
- 运维：Feed拉取失败通知

### P2 待开发内容
- 数据接入：海事情报LLM提取（IMO GISIS/UKMTO/ReCAAP）
- 前端：海事动态详情页
- 运维：情报数据过期淘汰策略
- 运维：低置信映射人工复核队列

### 现有 Spec 结构
- `.trellis/spec/backend/` — 25个文件，包含领域契约（cmdb-schema.md, rest-api-contract.md 等）
- `.trellis/spec/frontend/` — 7个文件，包含UI规范（webui-design.md, visualization-libraries.md 等）
- Spec 格式：index.md 为入口 + 具体 guideline .md 文件
- 内容风格：实际约定 + 代码示例 + 禁止模式 + 常见错误

## Assumptions (temporary)

- Spec 文档应放在 `.trellis/spec/` 下，遵循现有 backend/frontend 分层
- P0 代码的架构模式（星形模型、Feed Pull upsert、独立数据库）应作为 spec 的基线
- 知识图谱使用 reactflow（项目已有依赖 11.11.4）

## Decision (ADR-lite)

**Context**: 需要为威胁情报模块 P1/P2 创建 spec 文档，现有 spec 按 backend/frontend/vapt3 分层。
**Decision**: 创建独立 package `.trellis/spec/threat-intel/`，按功能领域拆分 4 个 spec 文件 + 1 个 index.md。内容深度为详细契约级（包含 API 端点、数据结构、代码示例、禁止模式）。
**Consequences**: 模块内聚，知识图谱可跨前后端独立成文；需更新 `get_context.py --mode packages` 能发现新 layer。

## Requirements (evolving)

- 为 P1/P2 创建可注入 sub-agent 上下文的 coding guidelines
- 覆盖后端（数据接入、API、图谱聚合）和前端（详情页、知识图谱、管理界面）
- 基于 P0 现有代码模式，确保一致性
- 包含验收标准和禁止模式

## Acceptance Criteria

- [x] Spec 文档可通过 `implement.jsonl` 注入到 sub-agent
- [x] P1 的每个功能领域都有明确的编码约定
- [x] P2 的 LLM 提取管道有明确的技术规范
- [x] 知识图谱（后端聚合 + 前端 reactflow）有完整的交互规范
- [x] Spec 遵循现有格式（实际约定 + 代码示例 + 禁止模式）
- [x] `get_context.py --mode packages` 发现 `threat-intel` spec layer
- [x] 每个数据源有明确的 URL、API 格式、字段映射、预处理步骤

## Definition of Done

- Spec 文件创建完成并更新 index.md
- Spec 内容基于 PRD 和 P0 代码，无矛盾
- Lint / typecheck 不受影响（纯文档变更）

## Out of Scope (explicit)

- P0 相关的 spec（已开发完成）
- 实际编写 P1/P2 代码（本任务只产出 spec 文档）
- PRD 修改（PRD 已定稿）

## Spec 文件结构（已确认）

```
.trellis/spec/threat-intel/
├── index.md                    — 入口 + Pre-Development Checklist + P1/P2功能矩阵
├── feed-integration.md         — P1 Feed接入规范（NVD/MalwareBazaar/Feodo/OTX/Exploit-DB + Industry CPE匹配）
├── graph-contract.md           — P1 知识图谱全栈规范（后端聚合API + 前端reactflow + 交互 + 聚类）
├── detail-and-management.md    — P1 详情页API + 前端 + Watchlist/别名管理界面
└── p2-pipeline.md              — P2 LLM提取管道 + 海事详情页 + 过期淘汰 + 低置信复核
```

## Expansion Sweep 考虑（已融入 spec）

1. **未来演进**: 商业情报源扩展点、知识图谱时间轴回放预留、API 扩展约束
2. **相关场景**: 图谱 API 与 list API 一致性、Feed 通知与 WebSocket 集成、供应链跨库查询边界
3. **失败/边缘**: NVD API 限流(429)处理、reactflow >200节点性能、LLM 置信度<0.65 处理、过期淘汰数据完整性

## Technical Notes

- PRD 路径：`docs/prd-threat-intelligence.md`
- ADR：`docs/adr/0003-threat-intelligence-as-independent-apt-centric-workspace.md`
- P0 代码：`secbot/threat_intel/`（models.py 10表, repo.py 1355行, feeds/4个puller, scheduler.py）
- P0 API：`secbot/api/threat_intel_routes.py`（17个端点, aiohttp）
- 前端代码：`webui/src/pages/threat-intel/`（5页面）、`webui/src/lib/threat-intel-client.ts`（362行）
- 知识图谱技术选型：reactflow 11.11.4（复用现有依赖）
- UI 风格：亮色 #F5F7FA + 双色渐变节点
- P0 架构模式：ULID主键 + actor_id多租户 + upsert语义 + FeedPullRun计数 + CronJob调度
- Spec 格式参考：`.trellis/spec/backend/cmdb-schema.md`（表结构+验证矩阵+Good/Base/Bad+Wrong/Correct）
