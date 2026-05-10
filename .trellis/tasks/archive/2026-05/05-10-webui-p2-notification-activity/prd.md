# WebUI P2 · 前端承接通知中心 + 大屏活动事件流

> Parent: [05-10-backend-api-gap-fill](../archive/2026-05/05-10-backend-api-gap-fill/prd.md)
> Upstream (已归档): [05-10-p2-notification-activity](../archive/2026-05/05-10-p2-notification-activity/prd.md)
> Priority: P2 · Est: 1-2d · Depends on: 已归档后端 P2（通知队列 + 事件 REST + `activity_event` WS 已上线）

## Goal

把后端 P2 已交付的三个 REST 端点（`/api/notifications*` + `/api/events`）与一个 WS 事件（`activity_event`）接入 WebUI：
- Navbar 右上角铃铛按钮升级为**下拉通知面板**：列表 / 未读红点 / 逐条已读 / 一键全读 / 条目 link 跳转；
- Dashboard 大屏新增**近 5 分钟活动事件流**面板：REST 初始拉取 + WS 追加，分级图标/颜色，断连回退轮询。

## What I already know

### 后端契约（已落地，见归档 PRD）
- `GET /api/notifications?unread=0|1&limit=50&offset=0` → `{ items, total, limit, offset, unread_count }`
- `GET /api/notifications/{id}/read` → `{ id, read:true }`（**GET，不是 POST**——websockets 库约束）
- `GET /api/notifications/read-all` → `{ updated }`
- `GET /api/events?since=&limit=50` → `{ items: [{ id, timestamp, level, source, task_id, message }] }`（默认近 5 分钟）
- WS `activity_event` payload：`{ event, chat_id, category: thought|tool_call|tool_result, agent, step, duration_ms, timestamp }`
- 通知类型：`critical_vuln | scan_failed | scan_completed | high_risk_confirm`
- 事件 level：`critical | warning | info | ok`；source：`weak_password | port_scan | asset_discovery | report | orchestrator`
- 内存队列（默认 500 条）+ 重启丢失——前端不需要考虑分页极大列表

### 前端现状
- [Navbar.tsx L117-124](file:///Users/shan/Downloads/nanobot/webui/src/components/Navbar.tsx#L117-L124) 铃铛目前**仅一个静态按钮**，无 onClick、无 badge、无面板。
- [DashboardPage.tsx](file:///Users/shan/Downloads/nanobot/webui/src/pages/DashboardPage.tsx) 不含活动事件流区块；需决定插入位置（顶部 KPI → 趋势 → 分布 → 集群，底部空）。
- [api.ts](file:///Users/shan/Downloads/nanobot/webui/src/lib/api.ts) 已具备 `request<T>` 基础 + Bearer 鉴权，可扩展 `fetchNotifications / markRead / markAllRead / fetchEvents`。
- [useNanobotStream.ts](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useNanobotStream.ts) 是**按 chatId 绑定**的流 hook，不适合全局通知；需要一个**全局订阅**的新 hook（`useNotifications` / `useActivityStream`）。
- WS 目前在 `secbot-client.ts` 内管理，需确认事件分发是否支持按 `event` 字段广播到多个订阅者。

### 跳转能力
- React Router 已启用，`notification.link`（如 `/tasks/TASK-2026-0510-014`）可直接 `navigate(link)`。

## Assumptions (temporary)

1. 铃铛面板用 shadcn `Popover`/`DropdownMenu`（项目已引入 shadcn/ui），不引入新依赖。
2. 大屏事件流面板放在 Dashboard **底部**作为独立 section，不抢占现有 KPI/分布区；高度固定 ≈ 320px，内部滚动。
3. WS `activity_event` 的 `chat_id` 对 Dashboard 场景**不过滤**（即展示全局任意 chat 的 agent 活动）；如需过滤再加。
4. 未读红点显示数字（≥99 显示 "99+"），与 Ant Design / GitHub 惯例一致。
5. i18n 复用现有 `t("nav.notifications")` key 规范，新增 zh/en 文案。
6. mark-as-read 时机：**点击条目时**触发（同时跳转 link），**不**在打开面板时批量 mark。
7. 断连回退：WS offline 时对 `/api/events` 做 5s 轮询；重连后立即补拉并关闭轮询。

## Open Questions

（见下文 Step 5 发散后的"MVP 边界"单选题；暂时只保留阻塞项）

- ~~Q1（阻塞）：事件流订阅生命周期~~ → **Resolved**：页面级订阅（方案 1），`<ActivityEventStream>` 在 `DashboardPage` 挂载/卸载时建立/销毁 WS 监听与轮询。
- ~~Q2（偏好）：badge 计数源~~ → **Resolved**：方案 A，仅依赖 `GET /api/notifications?unread=1` 的 `unread_count`；避免后端新增 WS 事件。

### 待回答（Step 5 发散后继续）

- ~~Q3（偏好 / MVP 边界）：未读数刷新策略~~ → **Resolved**：方案 b，30s 轮询 + `document.hidden` 暂停。
- ~~Q4（MVP 边界）：Step 5 发散扫视~~ → **Resolved**：严守 MVP + 预留签名钩子（见 D4）。

## Requirements (evolving)

### R1 · Navbar 铃铛下拉面板
- 铃铛按钮右上角挂一个未读数 badge（0 时隐藏、≥99 显示 "99+"）。
- **未读数来源**：`useUnreadCount()` hook 在 App 顶层挂载，30s 轮询 `GET /api/notifications?unread=1&limit=1`，`document.hidden` 时暂停，回前台立即补拉一次。mark-read / mark-all-read 成功后 optimistic 更新本地 `unread_count`，不等轮询。
- 点击打开 `Popover`，首次打开时拉 `GET /api/notifications?limit=50`；再次打开走缓存 + 后台静默刷新。
- 每条 item 展示：icon（按 type 映射）+ title + body 一行截断 + 相对时间（`format.ts::formatRelative` 若存在，否则新加）。
- item 点击：未读 → 发 `GET /.../{id}/read` → 本地 optimistic mark read → 若有 `link` 则 `navigate(link)` 并关闭面板。
- 面板顶部"全部已读"按钮：`GET /api/notifications/read-all` → 本地 unread_count 置 0。
- 面板空态：文案"暂无通知"。
- 面板显示最多 50 条，超过滚动；**不做分页加载更多**（后端上限也是 50，超出部分环形缓冲已丢弃）。

### R2 · Dashboard 大屏活动事件流面板
- 新增 `<ActivityEventStream>` 组件，放在 DashboardPage 底部作为独立 section。
- 初次挂载：拉 `GET /api/events?limit=50`（默认近 5 分钟）。
- 建立 WS 订阅：`activity_event` 追加到列表头部；同时 `/api/events` 的结果混入（按 timestamp 排序，去重 by id）。
- 每条展示：level 彩色小圆点（critical=red, warning=amber, info=blue, ok=emerald）+ source pill + agent（若 WS 事件带）+ message/step 文本 + 右侧相对时间。
- 列表最多保留 100 条（滚动 + 自动丢弃尾部），**不做虚拟列表**（100 条 DOM 可接受）。
- 无数据时显示占位插画 + "等待智能体活动..."。
- 可选过滤：level 多选（critical/warning/info/ok）与 source 多选；默认全选。

### R3 · 鉴权 / 错误处理 / 防御
- 所有新接口通过 `lib/api.ts::request<T>`，自动带 Bearer token（已有）。
- 铃铛面板失败：fallback 到最后一次成功结果 + alert 提示（遵循 WebUI 统一 alert 规范）。
- 事件流失败：WS 断连退回 5s 轮询 `/api/events`；重连后立即补拉并关闭轮询。
- **F2**：通知 `link` 指向已删除资源 → 由目标路由的 404 页兜底，通知中心不做预校验。
- **F3**：Popover 打开时与轮询 race → `useUnreadCount` / `useNotifications` 内置 `isFetching` flag + 最后请求 id 比对，丢弃陈旧响应。
- **F4**：`/{id}/read` 失败 → 回滚本地 optimistic 递减 + alert。
- **F5**：事件流 payload 出现未知 `level` / `category` → 降级为 `info` 渲染，不崩溃。
- 401 → 由现有 `ProtectedRoute` 处理，不在本任务范围。

### R4 · i18n
- 新增 key：`nav.notifications.empty / nav.notifications.markAll / activity.empty / activity.level.*` 等，zh + en 均需。

### R5 · 测试
- `webui/src/tests/Navbar.notifications.test.tsx`：badge 计数、点击打开、mark-as-read、跳转 link。
- `webui/src/tests/ActivityEventStream.test.tsx`：REST 初始化、WS 追加、排序 + 去重、level 过滤。
- 不做 e2e。

## Acceptance Criteria (evolving)

- [ ] Navbar 铃铛从静态升级为可交互下拉面板，未读数 badge 实时反映。
- [ ] 点击通知条目后 optimistic mark-as-read（不等 API），link 存在时正确跳转。
- [ ] "全部已读"按钮成功后 badge 归零且面板刷新。
- [ ] Dashboard 底部新增事件流 section，初始拉 REST + WS 追加 + 断连 5s 轮询兜底。
- [ ] level / source 过滤在客户端可用（不回后端）。
- [ ] 新增 API 适配函数有 happy-path + 一条错误 fallback 的 vitest 覆盖。
- [ ] 所有新组件 `vitest` + `tsc --noEmit` + `eslint` 全绿。
- [ ] 无新依赖（复用 shadcn/ui + lucide-react + i18next）。

## Definition of Done

- 代码通过 `bun run lint` + `bun run typecheck` + `bun run test`。
- 无新 npm/bun 依赖。
- `webui/src/gap/` 若有相关 gap 文档需同步（如果没有就不加）。
- Navbar 与 Dashboard 截图 / 录屏附 PR。

## Out of Scope (explicit)

- 通知**持久化**——归档 PRD 已明确只在内存，本任务前端不做 localStorage 缓存。
- **多租户 / 用户级过滤**——单用户场景。
- 通知的**桌面推送**（Web Notification API / Service Worker）——如果后续需要再开任务。
- **事件流导出 / 搜索 / 历史回放**——本任务仅 5 分钟滚动窗口。
- 通知 / 事件的**声音提醒**、震动、闪烁铃铛动画。
- **高危操作确认对话框**（`high_risk_confirm` 类通知）——该类通知点击后跳转现有确认页即可，不在本任务新建 Modal。
- **E1 后端 `notification_created` WS 事件 + 前端秒级 badge** → 仅在 `useUnreadCount` 里预留"刷新触发源数组"签名，不写空订阅代码；真需求来了单独开 follow-up。
- **E2 通知分页 "加载更多"** → 仅在 `fetchNotifications({ limit, offset })` 函数签名保留 `offset` 参数，UI 不出按钮。
- **通知 → Chat 高危横幅锚点跳转**（Related R1）→ 仅 `navigate(link)`，不追加 hash，不跨组件耦合。
- **`BroadcastChannel` 跨标签页 badge 同步** → 每个标签独立轮询即可。

## Research References

_（待 Step 4 研究后填入）_

## Technical Notes

- 前端主文件：
  - `webui/src/components/Navbar.tsx` — 铃铛升级（新增 Popover / 面板子组件）
  - `webui/src/components/NotificationPanel.tsx` — 新建，面板主体
  - `webui/src/components/ActivityEventStream.tsx` — 新建，大屏事件流
  - `webui/src/hooks/useNotifications.ts` — 新建，全局订阅 hook
  - `webui/src/hooks/useActivityStream.ts` — 新建，REST + WS 合流 hook
  - `webui/src/lib/api.ts` — 新增 `fetchNotifications / markRead / markAllRead / fetchEvents`
  - `webui/src/lib/secbot-client.ts` — 检查并（必要时）新增 `onActivityEvent` 订阅分发
  - `webui/src/pages/DashboardPage.tsx` — 底部插入 `<ActivityEventStream/>`
  - `webui/src/i18n/*` — 新增文案 key
- Spec 复用：
  - `.trellis/spec/frontend/*`（如有，brainstorm 阶段需要确认是否存在前端 spec；否则遵循 `webui/AGENTS.md` 与 `tsconfig` 规范）
  - 后端契约以归档 PRD 为准，前端不可改动后端合约。

## Decision (ADR-lite)

### D1 · 事件流订阅生命周期 = 页面级
- **Context**：事件流是 Dashboard 专属视觉；其他路由（Chat / Tasks / Settings）不消费。全局常驻会持续占内存 + 广播压力，且切回 Dashboard 后"近 5 分钟"语义依靠 `GET /api/events` 即可补齐历史，无需前端长期缓冲。
- **Decision**：`<ActivityEventStream>` 的 REST 初始拉取 + WS 订阅 + 轮询回退**全部在组件 `useEffect` 内管理**，卸载即清理；hook 写成 `useActivityStream()`，只在 Dashboard 挂载时被调用。
- **Consequences**：
  - ✅ 内存/CPU 成本最小，其他页面零开销；
  - ✅ 切换回 Dashboard 每次都会以"当前时刻往前 5 分钟"重新对齐视图（符合产品定义）；
  - ⚠ 后台页面无事件历史缓冲——这是可接受的（Dashboard 才是消费者）；
  - ⚠ 需要在 `secbot-client.ts` 的 WS 分发层支持"订阅/取消订阅"而非单例长驻（若当前实现是单例广播，按订阅者计数 gracefully close）。

### D2 · 铃铛未读 badge = REST 驱动
- **Context**：后端已归档 PRD 仅为"通知 CRUD 三件套"，未提供 `notification_created` 之类的 WS 事件。前端若要走"WS 主动推送 badge +1"需反推后端新增事件，超出本任务边界。
- **Decision**：铃铛未读数来源 = `GET /api/notifications?unread=1&limit=1` 返回的 `unread_count` 字段；刷新时机在 D3 定（Q3 未回答）。
- **Consequences**：
  - ✅ 零后端改动；
  - ✅ 读路径简单：一个 REST + 一个 state；
  - ⚠ 实时性不如 WS——最大延迟等于刷新策略窗口（待 Q3）；
  - ⚠ 若后续有"毫秒级 badge"需求，再单独开"后端加 `notification_created` WS"的 follow-up 任务。

### D4 · MVP 边界 = 严守核心 + 预留签名
- **Context**：P2 预算 1–2d；Step 5 发散识别出 E1/E2 演进点、R1 跨能力锚点、F1–F5 边缘场景。需要在"预留钩子"与"YAGNI"之间取舍。
- **Decision**：
  - **纳入 MVP**：D1/D2/D3 + R1/R2/R3/R4/R5；F1/F3/F4/F5 作为小防御直接写入；
  - **仅预留签名**（非代码）：E1 → `useUnreadCount` 内部"刷新触发源数组"命名；E2 → `fetchNotifications({ limit, offset })` 签名带 `offset`；
  - **显式排除**：E1 空订阅代码、E2 "加载更多" UI、R1 锚点跳转、F2 链接预校验、`BroadcastChannel` 多标签同步。
- **Consequences**：
  - ✅ 聚焦"让后端已落地能力前端可用"，1–2d 可交付；
  - ✅ 未来 E1/E2 落地时只需内部扩展、不改外部接口；
  - ⚠ R1 锚点/F2 预校验/秒级 badge 等若出现产品诉求，走独立 follow-up 任务。

### D3 · 未读数刷新策略 = 30s 轮询（可见时）
- **Context**：后端无 `notification_created` WS 事件（D2）；铃铛需要在所有页面都能"接近实时"反映新通知。按需刷新会让用户错过静默期的新通知；借 `activity_event` 做信号需 Dashboard 独占、与 D1 冲突。
- **Decision**：新建 `useUnreadCount()` hook 在 App 顶层挂载，`setInterval(fetchUnreadCount, 30_000)`；`document.visibilitychange` 监听：`document.hidden === true` 时 `clearInterval`，回前台时立即 fetch 一次并重启 interval。本地 mark-read / mark-all-read 成功后**不等轮询**，直接 optimistic 递减。
- **Consequences**：
  - ✅ 全页面一致，成本可控（每用户每分钟 ≤ 2 次轻量 REST，后端内存查询）；
  - ✅ 最大 badge 延迟 ≤ 30s，够 critical_vuln 用例；
  - ✅ 后台标签暂停 → 省电省流量，也防止多标签叠加风暴；
  - ⚠ 不是事件驱动；若后续提"秒级 badge"需求，单独任务加后端 WS；
  - ⚠ 需处理"多标签页"场景：每个标签独立轮询是可接受的（后端无压力），不做 `BroadcastChannel` 跨标签同步。

