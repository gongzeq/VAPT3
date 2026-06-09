# brainstorm: 生成前后端开发文档

## Goal

前端模版已确认（VITE_UIUX_TEMPLATE=true），基于当前已实现的 120+ TSX 组件、47 TS 模块和完整的后端 API 表面，生成系统化的前后端开发文档，并实现所有后端 Gap 修复，使前端从 mock 数据切换到真实 API。

## Requirements

* 生成前端架构总览文档（技术栈、路由、组件树、hooks、API 层、类型系统）
* 生成后端 REST API 完整契约（16 个分组的全部 endpoint 请求/响应 schema）
* 生成前端-后端 Gap 分析文档（4 个 Gap 及修复方案）
* 后端扩展 `/api/sessions` 响应字段：scan_type, target, status, findings, tokens, duration_ms
* 后端支持 query 会话类型持久化
* 前端 `useSessionsList` 从 mock 切换到真实 `GET /api/sessions` API
* 前端 `useReports` 从 mock 切换到真实 `GET /api/reports` API（全局），per-session 暂用 mock fallback

## Acceptance Criteria

* [x] 前端架构文档覆盖全部 12 个页面路由和核心组件
* [x] 后端 API 契约覆盖全部 REST endpoint
* [x] Gap 分析文档列出 4 个 Gap 及修复状态
* [x] `list_sessions()` 返回扩展字段（scan_type, target, status, findings, tokens, duration_ms）
* [x] `_compute_session_rollups()` 从 JSONL 消息中计算会话元数据
* [x] 前端 `useSessionsList` 使用 `fetchSessionRows()` 真实 API
* [x] 前端 `useReports` 全局报告使用真实 API
* [x] `tsc -p tsconfig.build.json` 通过
* [x] `eslint` 0 errors
* [x] `vite build` 成功

## Decision (ADR-lite)

**Context**: 前端模版已确认，需要系统化文档 + 后端实现来消除前后端接口差距。

**Decision**: 选择「全量 API 契约 + 架构文档」深度 + 「文档 + 全部 Gap 后端实现」范围。
- 3 份文档：前端架构、后端 REST 契约、Gap 分析
- G1+G4 (P0): `_compute_session_rollups()` 从 JSONL 消息计算扩展字段，结果缓存到 metadata `_rollups`
- G3 (P1): 从用户首条消息和 orchestrator plans 推断 scan_type，支持 "query" 类型
- G2 (P1): 全局报告用真实 API；per-session 过滤因 `report_meta` 使用 `scan_id` 而非 `session_key`，暂用 mock fallback

**Consequences**:
- tokens rollup 始终为零（turn_end 事件不持久化到 JSONL，未来增强）
- per-session 报告过滤需后续添加 scan_id ↔ session_key 映射

## Technical Approach

### 后端 (`secbot/session/manager.py`)
- `_compute_session_rollups(messages)`: 遍历 JSONL 消息，推断 scan_type/target/status，聚合 findings 计数，计算 duration_ms
- `list_sessions()`: 优先使用 metadata `_rollups` 缓存（`_v: 1`），否则全文件计算
- WebSocket handler 自动透传扩展字段（仅 strip `path`）

### 前端
- `api.ts`: `fetchSessionRows()` 调用 `GET /api/sessions` 并映射 snake_case → camelCase
- `useSessionsList.ts`: 完全重写，使用 `fetchSessionRows()` + `useClient()` token
- `useReports.ts`: 全局报告用 `GET /api/reports`，per-session 用 mock fallback

## Definition of Done

* 文档覆盖前端全部页面路由和核心组件
* 文档覆盖后端全部 REST API endpoint
* Gap 分析中 G1/G3/G4 已实现，G2 部分实现
* tsc + eslint + build 全部通过

## Out of Scope (explicit)

* per-session 报告过滤（需 report_meta 表添加 session_key 列）
* tokens rollup（需 turn_end 事件持久化到 JSONL）
* 前端 mock-sessions.ts 文件删除（保留作为 fallback）

## Technical Notes

### 产出文件
| 文件 | 类型 | 行数 |
|------|------|------|
| `.trellis/spec/frontend/architecture.md` | 新建文档 | 283 |
| `.trellis/spec/backend/rest-api-contract.md` | 新建文档 | 532 |
| `.trellis/spec/guides/frontend-backend-gap.md` | 新建文档 | 152 |
| `secbot/session/manager.py` | 后端修改 | +150 |
| `webui/src/lib/api.ts` | 前端修改 | +40 |
| `webui/src/hooks/useSessionsList.ts` | 前端重写 | ~60 |
| `webui/src/hooks/useReports.ts` | 前端重写 | ~80 |

### 验证结果
- `tsc -p tsconfig.build.json`: 通过（5 个预存测试文件错误，非本次引入）
- `eslint`: 0 errors
- `vite build`: 成功 (7.43s)
- Python syntax: manager.py OK
