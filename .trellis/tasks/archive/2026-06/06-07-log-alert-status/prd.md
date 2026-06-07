# 日志告警状态与处理流转

## Goal

为"历史分析"中的每条日志分析记录引入「告警 / 已处理 / 正常」三态状态机；前端在告警日志卡片上提供"处理"按钮，一键将其置为"已处理"；告警类日志同步推送到顶部通知栏，便于运维及时跟进。

## What I already know

后端：
* [log_analysis_dashboard.py](file:///Users/shan/Downloads/nanobot/secbot/api/log_analysis_dashboard.py) 是 `log_analysis` 表的只读访问层（设计约束：strictly read-only，无写入/迁移），暴露 `latest()` / `history()`，对应 `/api/dashboard/log-analysis/*`。
* `log_analysis` 表由 [workflow/scripts.py](file:///Users/shan/Downloads/nanobot/secbot/workflow/scripts.py#L808-L844) 的 `_ensure_table()` 拥有与迁移（已用 `ALTER TABLE ADD COLUMN` 模式增量加列）。当前**无** `status` / `handled_at` 字段。
* 现有 `analysis_json.suggested_action` 取值：忽略 / 标记关注 / 告警 / 紧急处理（LLM 建议，非处理状态）。
* 通知栈：[NotificationQueue](file:///Users/shan/Downloads/nanobot/secbot/channels/notifications.py#L130-L227) 为**内存环形缓冲（重启丢失）**；`ALLOWED_TYPES = (critical_vuln, scan_failed, scan_completed, high_risk_confirm)`，**无日志告警类型**。WS 路由 `/api/notifications`、`/api/notifications/{id}/read`、`/api/notifications/read-all` 已就绪。
* 已有高危确认链路 [high_risk.py](file:///Users/shan/Downloads/nanobot/secbot/agents/high_risk.py) 作为「待确认→已确认」状态流转参考。

前端：
* [LogAnalysisDetailPage.tsx](file:///Users/shan/Downloads/nanobot/webui/src/pages/LogAnalysisDetailPage.tsx) 卡片式历史列表，`RecordCard`（L347）、`ActionBadge`（L108）、`needsAction()`（L79）。
* [log-analysis-client.ts](file:///Users/shan/Downloads/nanobot/webui/src/lib/log-analysis-client.ts)：`LogAnalysisHistoryItem` 类型 + `fetchLogAnalysisHistory()`。
* [useNotifications.ts](file:///Users/shan/Downloads/nanobot/webui/src/hooks/useNotifications.ts) + [NotificationPanel.tsx](file:///Users/shan/Downloads/nanobot/webui/src/components/NotificationPanel.tsx)：乐观更新 + 重开刷新模式可复用。

## 状态语义（已确认）

suggested_action 词表从四值简化为两值：**告警 / 正常**（需改 LLM 提示词）。三态状态机：
* **正常 normal**：suggested_action == "正常"（兼容旧值 忽略 / 标记关注）。
* **告警 alert**：suggested_action == "告警"（兼容旧值 紧急处理）且尚未被处理。
* **已处理 handled**：该 log_id 存在于 `log_analysis_handled` 表（覆盖告警态）。

状态优先级：handled > alert > normal。

## Decisions (resolved)

* [Q1] 持久化 → **方案B 独立处理状态表** `log_analysis_handled`，原表保持只读，读取时 LEFT JOIN 派生 status。
* [Q2] 状态口径 → suggested_action 简化为两值（告警/正常），改 LLM 提示词 + 存量旧值兼容映射。
* [Q3] 通知时机 → **workflow 分析落库时**判定为告警即 publish 通知（新增 `log_alert` 类型）。
* [Q4] 联动 → 点击"处理"时**同步标记**对应通知为已读（需 notification ↔ log_id 关联）。

## Requirements (evolving)

* 每条历史分析记录具备三态状态：告警 / 已处理 / 正常。
* 告警卡片显示"处理"按钮，点击后乐观更新为"已处理"并持久化（写 `log_analysis_handled`）。
* 告警记录在分析落库时推送到通知栏（`log_alert` 类型，link 跳转日志分析详情）。
* 点击"处理"同步将对应告警通知标记为已读。
* LLM 提示词输出 suggested_action 收敛为 告警/正常；history/latest 对存量旧值做兼容映射。

## Acceptance Criteria (evolving)

* [ ] history API 返回每条记录的 `status` 字段（alert/handled/normal）。
* [ ] 告警卡片渲染"处理"按钮；点击调用处理 API，UI 立即变"已处理"。
* [ ] 处理状态持久化，刷新/重启后保持。
* [ ] 新增告警记录在通知栏可见，点击跳转到日志分析详情页。
* [ ] 点击"处理"后对应通知在通知栏变为已读。
* [ ] suggested_action 新输出仅含 告警/正常；旧值记录仍能正确归类。

## Definition of Done

* 单元/集成测试覆盖：status 派生、处理 API、通知发布。
* 前端 lint / typecheck / vitest 绿。
* 文档/spec 按需更新。

## Out of Scope (explicit)

* 通知历史的长期持久化改造（当前内存态，重启清空）—— 除非 Q2 决策要求。
* 多用户处理人审计（handled_by）—— 视 Q1 决策可选保留扩展位。

## Technical Notes

[Q1] 处理状态持久化三方案：
* **方案A：log_analysis 表加列**。在 `_ensure_table()` 增加 `status TEXT` / `handled_at TEXT`，新增独立写入模块/端点更新该列。优点：单一数据源、随记录走；缺点：突破 dashboard "只读"约束，需新建写路径。
* **方案B：独立处理状态表**。新建 `log_analysis_handled(log_id, handled_at)` 小表，dashboard 读取时 LEFT JOIN 派生状态。优点：保留原表只读语义、解耦；缺点：多一张表 + JOIN。
* **方案C：内存态**。与通知一致，重启丢失。基本不可接受（验收要求持久化）。

[Q2] 通知产生时机（已定：落库时）的落地风险：
* 通知队列是**按进程内存态**。workflow step 脚本可能跑在独立子进程（`_emit` 写 stdout 回传），在那里 publish 会进不了 WS 服务进程的队列。
* 落地点应为**服务进程消费 step 输出 / 结果入库的入口**处 publish（语义仍是分析完成即告警）。实现阶段需确认 step 运行进程模型。

[Q4] notification ↔ log_id 关联：发布告警通知时在 item 内携带 log_id（或 link = `/dashboard/log-analysis?focus=<id>`）；处理端点按 log_id 定位对应通知并 mark_read（需 NotificationQueue 增加按 log_id 查找/标记的辅助方法）。

[Q2-prompt] LLM 词表简化涉及：[templates.py](file:///Users/shan/Downloads/nanobot/secbot/workflow/templates.py#L248-L266) 提示词、[llm_chunked.py](file:///Users/shan/Downloads/nanobot/secbot/workflow/executors/llm_chunked.py#L62-L68) 严重度排序表；同时保留旧值映射（忽略/标记关注→正常，紧急处理→告警）。

## Implementation Plan (small PRs)

* **PR1 后端状态与处理 API**：新建 `log_analysis_handled` 表 + 写入模块；history/latest 补充 `status` 字段（LEFT JOIN + 旧值兼容映射）；新增 `POST /api/dashboard/log-analysis/{id}/handle` WS 路由与处理器；单测。
* **PR2 告警通知推送**：`ALLOWED_TYPES` 增加 `log_alert`；在服务进程消费分析结果的入口判定告警并 publish（携 log_id + link）；处理端点同步 mark_read；单测。
* **PR3 前端三态与处理按钮**：`LogAnalysisHistoryItem` 增 `status`；`ActionBadge` 渲染三态；告警卡片加"处理"按钮（乐观更新）；NotificationPanel 支持 `log_alert` 图标；vitest。
* **PR4 LLM 词表简化**：提示词与排序表改为 告警/正常；回归验证存量旧值归类。
