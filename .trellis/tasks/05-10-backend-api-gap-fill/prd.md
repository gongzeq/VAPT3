# Backend API Gap Fill — Dashboard & Assistant

## Goal

基于 `webui/src/gap/dashboard-data.md` 与 `webui/src/gap/home-assistant-data.md` 所识别的数据缺口，补齐「智能助手」与「大屏分析」两个核心页面所需的后端聚合接口、模型扩展与实时事件，使前端可以摘除 `PromptSuggestions.tsx` 与 `data/mock/dashboard.ts` 中的静态 mock。

## Scope

共计 **13 个 HTTP 接口 + 3 个 WS 事件 + 3 项模型变更**，按优先级分 3 批子任务交付：

| 子任务 | 覆盖范围 | 优先级 | 预估 |
|--------|----------|--------|------|
| [05-10-p0-dashboard-aggregation](../05-10-p0-dashboard-aggregation/prd.md) | `/api/dashboard/summary` + `/vuln-trend` + `/vuln-distribution` + `/asset-distribution` + `/asset-cluster` + `/api/agents?include_status=true` + WS `task_update` / `blackboard_update` | P0 | 3–4d |
| [05-10-p1-report-session-prompts](../05-10-p1-report-session-prompts/prd.md) | `report_meta` 表 + `/api/reports` + `/api/sessions` 搜索/归档 + `/api/prompts` 配置化 | P1 | 2–3d |
| [05-10-p2-notification-activity](../05-10-p2-notification-activity/prd.md) | `/api/notifications` + `/api/events` 事件流 + WS `activity_event` | P2 | 2d |

## Design Decisions（已在 brainstorm 锁定）

1. **Asset 业务系统 / 资产类型**：复用现有 `asset.tags: JSON`，资产发现 agent 写入 `{"system": "CRM", "type": "web_app"}`，不新增列。
2. **Vulnerability.category 扩展**：直接扩展 `VALID_VULN_CATEGORIES` 枚举，新增 `injection / auth / xss / other`，统一一级分类。
3. **KPI 卡片无合规等级字段**：当前 mock 仅有 6 项（活跃任务/已完成扫描/高危漏洞/资产总量/待处理告警/智能体在线），`/api/dashboard/summary` 仅返回这 6 项必要字段，不下发 compliance_grade/score。
4. **Report 持久化**：新增 `report_meta` 表（Alembic migration），Orchestrator 在报告生成完成后写入元数据。
5. **快捷指令**：新增 `GET /api/prompts` 从 YAML 配置读取（`secbot/config/prompts.yaml`），不入库。
6. **多语言暂不处理**：不引入 `?lang=` 参数、不在 settings 中新增 language 字段（本次明确排除）。

## Requirements

### 功能性

- R1 前端可通过 REST 接口一次性获取 Dashboard 全量数据（6 KPI + 4 分布/趋势 + 历史报告），响应时间 P95 < 500ms（小数据量）。
- R2 `/api/agents?include_status=true` 返回运行时状态（idle / running / queued / offline）、进度、当前任务 ID、最近心跳时间。
- R3 历史扫描完成后，Orchestrator 自动向 `report_meta` 插入一条记录；`GET /api/reports` 支持按时间范围、状态、类型筛选 + 分页。
- R4 前端 `PromptSuggestions` 可从 `/api/prompts` 拉取快捷指令，YAML 热加载（修改 YAML 无需重启）。
- R5 会话列表接口 `/api/sessions` 支持 `q`（模糊搜索）、`archived`、`limit`、`offset`。
- R6 WS 事件 `task_update` / `blackboard_update` 可在扫描运行期间持续下发。

### 非功能性

- N1 所有新接口遵循 `api-design.md` 0 节全局规范（鉴权、分页、时间戳、错误响应）。
- N2 CMDB 访问严格经由 `secbot/cmdb/repo.py`，不新增裸 SQL 通道。
- N3 Alembic migration 必须与 `.trellis/spec/backend/cmdb-schema.md` 描述保持一致。
- N4 所有聚合查询在 SQLite 上以单索引扫描可完成；若无现有索引，随 migration 一并新增。

## Acceptance Criteria

- [ ] 3 个子任务的 PRD 均已创建，验收标准独立可测。
- [ ] `.trellis/spec/backend/cmdb-schema.md` 补充 `asset.tags.system/type` 约定、`vulnerability.category` 新值、`report_meta` 表。
- [ ] `.trellis/spec/backend/dashboard-aggregation.md`、`report-meta.md`、`prompts-config.md` 新增并进入 backend index。
- [ ] 前端 `webui/src/data/mock/dashboard.ts` 与 `PromptSuggestions.tsx` 的静态数组全部替换为 API 调用。
- [ ] 旧接口 `/api/sessions/{key}/delete` 保留 GET 兼容，新增接口 DELETE 语义规范。
- [ ] 单元测试覆盖：聚合 SQL 在空表/单扫描/多扫描场景下结果正确；`task_update` WS 推送在扫描状态变更时被触发。

## Definition of Done

- 每批子任务完成后可以独立合并（前端 mock 可按批替换）。
- 后端 `pytest tests/` 全绿；新接口至少补 1 条 happy-path 测试。
- 前端 `vitest` 全绿；mock 替换后快照不退步。
- Alembic `alembic upgrade head` 在全新 SQLite 上执行无异常。
- 相关 spec 文档已更新并在 `backend/index.md` 索引。

## Out of Scope

- 多语言 i18n 持久化 / `?lang=` 查询参数 / settings 中 language 字段。
- 登录页 / 任务详情页 / 设置页所需接口（详见 `api-design.md` §1、§4、§5）。
- Dashboard 快照导出 `/api/dashboard/snapshot`（属于 03-dashboard 原型的"立即扫描"功能，不在本次差距文档中）。
- Agent 运行时状态的持久化存储（本次在内存/SubagentManager 中维护即可）。

## Technical Notes

- 参考文档：
  - `webui/src/gap/dashboard-data.md` — Dashboard 数据需求
  - `webui/src/gap/home-assistant-data.md` — 智能助手数据需求
  - `.trellis/tasks/05-09-uiux-template-refactor/api-design.md` §2-3 — 既有接口契约草案
- 既有能力：
  - `secbot/cmdb/repo.py::list_scans/list_assets/list_vulnerabilities` — 聚合查询底层
  - `secbot/agent/subagent.py::SubagentManager` — agent 运行时状态
  - `secbot/report/builder.py::build_report_model` — 报告生成（需包装持久化）
  - `secbot/channels/websocket.py` — HTTP + WS 路由分发，所有新 HTTP 端点在此注册

## Decision (ADR-lite)

**Context**: 前端 Dashboard 与智能助手页面多处使用静态 mock，亟需后端接口支撑，但改动涉及模型/持久化/WS 多个层面，一次性 PR 风险高。

**Decision**: 按优先级拆 3 批子任务交付：P0 聚合查询（只读）优先上线驱动 Dashboard 实装；P1 引入新表（report_meta）与 Session 扩展；P2 补事件流与通知中心。每批独立可 merge，前端 mock 按批替换。

**Consequences**:
- ✅ 每批 PR 规模可控（单 PR < 600 行），降低 review 成本。
- ✅ P0 完成后前端 Dashboard 80% 数据已接入真实后端，用户可见价值最大。
- ⚠ P0 不含 `report_meta`，历史报告模块需在 P1 完成后才能去 mock；短期内前端 `recentReports` 继续用 mock。
- ⚠ Agent 运行时状态不持久化，重启丢失；如未来需要历史查询再考虑入库。
