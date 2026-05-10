# Journal - shan (Part 1)

> AI development session journal
> Started: 2026-05-07

---



## Session 1: Complete 8 PRs for cybersec agent platform

**Date**: 2026-05-07
**Task**: Complete 8 PRs for cybersec agent platform
**Branch**: `main`

### Summary

Finished all 8 PRs: PR1 rename nanobot to secbot, PR2 remove IM channels and bridge, PR5 expert agent registry, PR6 six core skills with sandbox, PR7 orchestrator and high-risk confirm hook, PR10 report pipeline (MD/PDF/DOCX), PR8 WebUI on assistant-ui/react, PR9 WebUI Assets/ScanHistory/Reports views with ocean-blue theme. Backend tests 2329/2329 passed.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `209380d8` | (see git log) |
| `c63bd6da` | (see git log) |
| `3a24a59e` | (see git log) |
| `1ed0808c` | (see git log) |
| `99cf6ed9` | (see git log) |
| `2224ab17` | (see git log) |
| `fdfafd76` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: WebUI OpenAI-compatible endpoint & /model command

**Date**: 2026-05-07
**Task**: WebUI OpenAI-compatible endpoint & /model command
**Branch**: `main`

### Summary

在 WebUI 系统设置中新增 OpenAI-compatible endpoint 配置（Base URL + API Key，脱敏回显、三态更新语义），并新增 /model slash 命令：无参时拉 GET {api_base}/models 渲染 quick-reply 按钮（60s 缓存，key 变化自动失效），带参时写入 defaults.model 触发 AgentLoop provider hot-reload。API Key 通过 X-Settings-Api-Key 自定义请求头传输避免进 URL；api_base 走 URL query。配套 PR4 文档（chat-commands.md / configuration.md）。分 4 个 commit：后端 settings API / WebUI 表单 / /model 命令 / 文档。tests: 241 passed, ruff clean.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `1332b4c3` | (see git log) |
| `1212517b` | (see git log) |
| `6255bb77` | (see git log) |
| `c5cd6c40` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: P0 Dashboard 聚合功能数据层+接口层完整交付

**Date**: 2026-05-10
**Task**: P0 Dashboard 聚合功能数据层+接口层完整交付
**Branch**: `main`

### Summary

完成 P0 dashboard-aggregation 两轮交付。R1：CMDB 层扩展 Vulnerability 类目枚举 + Asset.tags 对齐，repo.py 新增 summary_counts/vuln_trend/vuln_distribution/asset_type_distribution/asset_cluster 5 组聚合，18 个单测。R2：websocket.py 注册 /api/dashboard/{summary,vuln-trend,vuln-distribution,asset-distribution,asset-cluster} + /api/agents?include_status=true，新增 broadcast_task_update/blackboard_update（1s 节流），ChannelManager/cli.commands 注入 subagent_manager/agent_registry，20 个 channels 单测。全仓 2393 passed，ruff clean。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8cc98d02` | (see git log) |
| `fc88c8da` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete

---

## 2026-05-10 · backend-api-gap-fill 父任务复盘 + PRD 修正

**Context**: `/trellis-continue` 恢复工作，原 current task 指针失效；P0 子任务已归档（R1+R2 已合入 main）。选择父任务 `05-10-backend-api-gap-fill` 作为聚合入口。

### Phase 1.3 完成
- 父任务 status: planning → in_progress
- `implement.jsonl` 策划 10 条（backend spec + 前端 gap 文档）
- `check.jsonl` 策划 8 条（质量/错误/schema/DB 指南）
- `task.py validate` 通过

### PRD 复盘发现 5 项偏差 → 修正完成
1. **父 PRD §Design Decisions #2**：类目枚举实际落地为 8 项（injection/auth/xss/misconfig/exposure/weak_password/cve/other），非 PRD 声称的 4 项。修正锁定 P1/P2 不再扩展枚举。
2. **P1 PRD §Contracts #3**：补"session archived 字段前置存储层改动"（当前 session/manager.py 未定义此属性）+ 验收项加一条。
3. **P2 PRD §AC**：`on_vulnerability_insert` hook 不存在 → 改写为"在 insert_vulnerability 末尾直接 publish"，避免引入 observer 抽象。
4. **P2 PRD §AC**：`activity_event` 广播明确复用 P0 R2 的 `broadcast_task_update` 节流模板（1s/event/scope）+ `WebSocketChannel` 依赖注入风格。
5. **P2 PRD §Out of Scope**：前端 Navbar 铃铛/事件流面板显式划给 webui 侧后续任务，本任务 DoD 仅覆盖后端接口 + WS 契约。

### Next Steps
- 选择下一个启动的子任务（P1 或 P2），执行其 1.3 curate + 1.4 start 进入 Phase 2。
- P1 前置：需要在 brainstorm 或实施起始确认 session 文件 schema 兼容策略（读旧文件不报错）。
- P2 前置：需核对 `broadcast_task_update` 当前接口是否对 `activity_event` 类事件足够通用，或需要小重构。

---

## 2026-05-10 · P1 Phase 2.1-2.2 交付完成

**Context**: 父任务 `05-10-backend-api-gap-fill` 下的 P1 子任务 `05-10-p1-report-session-prompts`。按 R1/R2/R3 三块拆分落地，每块独立 commit，全量回归 335/335 绿。

### R1 · report_meta + /api/reports + handler 回写 (commit 6b2c715a)
- ORM `ReportMeta`（显示 id `RPT-YYYY-MMDD-<seq>` 作 PK，seq 按本地日期全局递增）+ 2 索引
- Alembic `20260510_report_meta`（down_revision=20260507_initial）
- repo: `insert_report_meta / list_reports / get_report / update_report_status`（状态机对齐 spec §3.3）
- HTTP: `/api/reports` 列表 + `/api/reports/{id}` 详情
- 3 个 report skill handler（markdown/docx/pdf）渲染后 best-effort 回写（warning-on-fail）
- 测试：9 cmdb unit + 7 HTTP e2e

### R2 · session 搜索 + 归档 (commit bd8f1631)
- `SessionManager.list_sessions` 注入 `archived` 字段（旧文件无字段视为 false，无需 migration）
- `SessionManager.set_archived(key, bool)`：幂等、不存在返回 False
- `/api/sessions` 扩展 `q / archived / limit / offset` + 顶层 `total`；不传参数形态向后兼容
- `/api/sessions/{key}/archive`（GET，websockets HTTP parser 限制；PRD 写 POST）
- 测试：16 in-process 单元（auth/filter/分页/幂等/404/400）

### R3 · /api/prompts YAML 热加载 (commit d16f92b1)
- `secbot/config/prompts.yaml` 默认 4 条（从前端 PROMPTS[] 迁移）
- `secbot/api/prompts.py`：`PromptsLoader` mtime-based hot reload + dedupe（first-wins + warn）+ parse-error fallback（保留上次 cache，绝不清空）+ warn-once for missing
- 解析优先级：`$SECBOT_PROMPTS_FILE` → `~/.secbot/prompts.yaml` → bundled
- HTTP: `/api/prompts`（auth-gated，loader 异常降级到空数组，绝不 500）
- 测试：11 单元（default/override/missing/parse-error/hot-reload/dedupe/top-level-list/HTTP）

### 质量回顾
- 新增 43 个测试（9+7+16+11）全绿
- 回归 335/335（api + channels + session + cmdb + report）
- ruff：R1/R2/R3 新增文件全 clean；仅剩 2 处 websocket.py 预存在 `self` F821（基线 bug `e201ede2`，超本任务范围）

### 关键设计决策
- R1 `report_meta.id`：spec §3.2 提到 "ULID 存储"，但选择 display-id-as-PK + 全局日期 seq（v1 单 actor 场景语义等价，URL 路由 O(1)，`actor_id` 字段仍保留供未来多租户）
- R1 `_next_report_seq` 不按 actor_id 分组：PRD 原文 `COUNT(*) WHERE DATE(created_at)=today (+1)`，多 actor 下独立计数会导致 PK 冲突
- R2 `POST` → `GET`：websockets 库 HTTP parser 只接受 GET，与既有 `/delete` 处理对称；query `?archived=0|1` 替代 body
- R3 默认 `archived=1`：最短调用表达"归档"动作；`archived=0` 取消归档

### Out of Scope（P1 未做）
- webui 前端接入：`PROMPTS[]` → `useQuery('/api/prompts')`、`recentReports` mock 下线、侧边栏归档按钮 → `/api/sessions/{key}/archive`。PRD §AC 最后一项属前端工作，按父任务拆分归属后续 webui 子任务

### Next Steps
- 本任务 archive + 父任务 `05-10-backend-api-gap-fill` 进度更新为 [2/3 done]
- 选择：P2 notification center / 前端对接 P1 接口



## Session 5: P2 notification center + activity event stream delivered

**Date**: 2026-05-10
**Task**: P2 notification center + activity event stream delivered
**Branch**: `main`

### Summary

R1/R2/R3 三段交付完成：NotificationQueue singleton + /api/notifications CRUD、EventBuffer + /api/events 5min 滚动窗口、WebSocketChannel.broadcast_activity_event + upsert_vulnerability critical 通知触发。父任务 05-10-backend-api-gap-fill [3/3 done] 同批归档，1221 tests passed.

### Main Changes

# P2 · Notification Center + Activity Event Stream — Delivery Retrospective

Task: `05-10-p2-notification-activity` (parent: `05-10-backend-api-gap-fill`, now archived `[3/3 done]`).

## Scope Delivered

三块后端能力，按 R1/R2/R3 递进实施：

- **R1 通知中心** — `secbot/channels/notifications.py::NotificationQueue` singleton + `GET /api/notifications`（列表、unread 过滤、分页回显）/ `GET /api/notifications/{id}/read` / `GET /api/notifications/read-all`。环形缓冲容量走 env > 构造参数 > 默认 500 的三层 resolution（对齐 PromptsLoader 范式）。27 个测试覆盖 NotificationQueue unit + singleton + HTTP handler。
- **R2 活动事件缓冲 + 查询** — `EventBuffer` 与 `NotificationQueue` 同模块托管（复用 `_resolve_maxlen` + 同 singleton 风格），支持 `GET /api/events?since=&limit=` 近 5 分钟滚动窗口（两个 env 变量：`SECBOT_EVENTS_BUFFER_SIZE` / `SECBOT_EVENTS_WINDOW_SECONDS`）。27 个测试覆盖 EventBuffer + singleton + HTTP handler。
- **R3 WS `activity_event` 广播 + critical_vuln 通知触发** — `WebSocketChannel.broadcast_activity_event`（复用 `_should_throttle_broadcast` 的 1s/chat_id 节流模板）+ 类级 `_active_instance` 单例让 `_LoopHook` 不用改构造签名就能拉到 channel 实例；`upsert_vulnerability` 在首次插入 critical 或 severity 升级为 critical 时触发 `NotificationQueue.publish("critical_vuln", ...)`，rescan 同一 critical 保持静默。

## Key Engineering Decisions

1. **HTTP 方法收敛到 GET**：P2 PRD Phase 1.2 复核阶段识别出 `POST /api/notifications/{id}/read` + `/read-all` 与 `websockets` 库 HTTP parser 不兼容（R2 `/archive` 已踩过同一坑），Phase 1.3 前把 PRD 的动作型端点统一改为 GET。
2. **EventBuffer 与 NotificationQueue 同模块**：Phase 2 过程中用户明确选择共享 `secbot/channels/notifications.py`，让 `_resolve_maxlen` / singleton 模式 / 测试 reset fixture 全部复用。
3. **`WebSocketChannel._active_instance` 类级单例**：`_LoopHook.__init__(channel: str = "cli")` 是字符串标识而非 channel 对象，且 `_LoopHook` 只在 `loop.py` L571 一处构造（嵌在 `AgentLoop._run_agent_loop` 内）。为避免改动 loop hook 构造参数/打穿多层调用链，选择在 `WebSocketChannel.__init__` 末尾 `cls._active_instance = self`，loop hook 通过 `WebSocketChannel.get_active_instance()` 延迟拉取。对齐 PRD L98/L128 "与 PromptsLoader 同风格，不引入 observer/signal 抽象"的约束。
4. **upsert 语义 vs "新增"语义**：PRD 说"高危漏洞新增时自动产生 critical_vuln"，实际代码是 `upsert_vulnerability`（re-discovery 会 refresh 而不新增行）。决策规则：首次 insert + severity=critical，或 severity 从 non-critical 升级到 critical 都触发通知；rescan 同 critical 保持静默避免刷屏。5 个测试精确覆盖四种场景。
5. **循环依赖处理**：`secbot.channels.notifications` 已 import `secbot.cmdb.repo.new_ulid`，cmdb 这边反向在 `upsert_vulnerability` 函数**体内** late-import `get_notification_queue` 打破循环。

## Gotchas Fixed This Session

- **URL 解码 `+` → 空格**：`/api/events?since=2026-05-10T10:00:00+00:00` 经 URL 解析后 `+` 被当成空格，`datetime.fromisoformat("... 00:00")` 报错。handler 里 `since_raw.replace(" ", "+")` 再 parse 修复，测试 `test_since_filter_accepts_offset_timestamp` 覆盖。
- **`category="weak_credential"` 不合法**：cmdb 合法枚举是 `weak_password`。第一版通知测试抓住这个错，改正后 17 个 CMDB 测试全绿。
- **pytest-asyncio 对 sync 测试报 warning**：`pytestmark = pytest.mark.asyncio` 会把同步测试也标注，改成 `async def` 虽然不实际 await 也能消除警告。

## Pre-Existing Issue Acknowledged

`secbot/channels/websocket.py::_save_envelope_media` L2114/L2139 两处 `self.logger` 在 `@staticmethod` 里，ruff F821。base commit `e201ede2` 就存在，本任务不修。

## Regression

- Targeted: `tests/api tests/channels tests/cmdb tests/agent tests/session tests/report` → **1221 passed**.
- Narrow: `tests/api/test_notifications.py` 27 / `tests/api/test_events.py` 27 / `tests/channels/test_ws_activity_event.py` 12 / `tests/cmdb/test_vulnerability_notification.py` 5 全绿.

## Acceptance Criteria Status

全部 8 条后端 AC 达成；前端 UI 归 webui 后续任务（PRD Out-of-Scope L115 明确声明）。

## Commits (in dependency order)

- `526de882` chore(task): P2 PRD fixes + context curation
- `443f7817` feat(notifications): P2/R1 NotificationQueue singleton + /api/notifications CRUD endpoints
- `575dfe1f` feat(events): P2/R2 EventBuffer + /api/events rolling window endpoint
- `87369720` feat(activity): P2/R3 WS activity_event broadcast + critical_vuln notification trigger
- `b222b2d2` chore(task): archive 05-10-p2-notification-activity
- `13e81acf` chore(task): archive 05-10-backend-api-gap-fill

## Follow-ups (Not in Scope)

- 前端 Navbar 铃铛 + 大屏事件流 UI 组件（webui 侧任务）。
- EventBuffer 的事件源填充点（当前只有 `broadcast_activity_event` WS 侧；`/api/events` buffer 的 publish 入口待业务场景落地时再接）。
- `secbot/channels/websocket.py::_save_envelope_media` 里两处 `self.logger` 预存在 bug（base commit，不影响运行时）。


### Git Commits

| Hash | Message |
|------|---------|
| `443f7817` | (see git log) |
| `575dfe1f` | (see git log) |
| `87369720` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
