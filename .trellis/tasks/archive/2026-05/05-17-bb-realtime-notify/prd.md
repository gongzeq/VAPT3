# brainstorm: 扩展 blackboard_write 实时通知

## Goal

把"前端展示"与"智能体间实时协作"两条数据通路分开：

- **黑板（blackboard）**：只写**聚合统计 / 总数**（如"已发现 50 个端口、12 个 URL、3 个 SQL 注入"），作为前端仪表盘和 orchestrator 全局视图。**每条资产发现不再写黑板。**
- **资产清单（asset feed）**：新增一个独立的、逐条 push 的资产队列。子智能体每发现一个资产（URL / 端口 / 凭据 / 漏洞）就 append 一条。orchestrator 监听该队列，实时拿到新资产后决定转发给哪个下游 agent。

最终支持多智能体的实时协作与回溯，且不让黑板被高频细节淹没。

## Final Decision

### 存储方案：**内存 Registry（不入库 CMDB）**

- 新增 `AssetFeed` / `AssetFeedRegistry`（仿 [BlackboardRegistry](file:///Users/shan/Downloads/nanobot/secbot/agent/blackboard.py) 实现），按 `chat_id → list[AssetEntry]` 内存存储。
- 每条 `AssetEntry` 携带：`id`(自增) / `kind`(url|port|credential|vuln|tech) / `agent_name` / `payload`(dict) / `created_at`。
- 进程重启即丢失，**与会话生命周期对齐**；不引入持久化（CMDB / 文件）副作用。
- 后续若需持久化，可在 Registry 顶层挂一个可选 sink（不属于本次范围）。

### 写入入口：**新增独立工具 `asset_push`**

- 子智能体每发现一个资产即调用 `asset_push(kind, payload)`，由 `AssetFeedRegistry.append` 入队 + 通过 `bus.publish_inbound` 注入 `InboundMessage(metadata.injected_event="asset_discovered")` 唤醒 orchestrator。
- **不依赖 SkillResult.cmdb_writes**（避免与 CMDB 写入路径耦合）。每个 skill / 子智能体在 prompt 中按自己输出特点决定调用 `asset_push` 的内容（URL 写 url 类型、端口写 port 类型……）。

### 黑板：保留，语义收敛

- `BlackboardWriteTool` 仅用于阶段总结 / 聚合统计；逐条资产一律走 `asset_push`。
- Tool description + 各 expert prompt 同步更新。

## What I already know

来自仓库探查：

- `BlackboardWriteTool`（[secbot/agent/tools/blackboard.py](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/blackboard.py)）当前仅写 `BlackboardRegistry` + 触发 `on_write` 回调（前端 WS），不会触发 orchestrator turn。
- Orchestrator 是事件驱动：只有 `bus.publish_inbound(InboundMessage)` 才能触发新一轮（[secbot/agent/loop.py](file:///Users/shan/Downloads/nanobot/secbot/agent/loop.py)）。
- 既有先例：`subagent._announce_result` 通过 `bus.publish_inbound` 注入 `subagent_result` 系统消息（[secbot/agent/subagent.py:548-569](file:///Users/shan/Downloads/nanobot/secbot/agent/subagent.py#L548-L569)）。
- BlackboardRegistry 已是内存 + per-chat_id 模型，可作为 AssetFeedRegistry 的实现参考。

## Requirements

- [R1] 新增 `AssetFeedRegistry`（内存，按 chat_id 隔离），提供 `append(chat_id, entry)`、`since(chat_id, since_id?)`、`group_by_kind(chat_id)` API。
- [R2] 新增子智能体工具 `asset_push(kind, payload)`：写入 Registry 后通过 `bus.publish_inbound` 注入 `injected_event="asset_discovered"` 系统消息（携带 `count`、`kinds`、`since_id`）。
- [R3] 新增子智能体工具 `read_assets(kind?, since_id?)`：按当前 chat_id 拉取增量资产，便于 orchestrator 与下游 expert 消费。
- [R4] `BlackboardWriteTool.description` + expert prompt 收敛为"只写聚合统计"；逐条资产走 `asset_push`。
- [R5] 通知必须在子智能体仍运行时也能传达；不依赖子智能体退出。
- [R6] 前端 API：`GET /api/assets?chat_id=&kind=&since_id=`（直读 Registry），与黑板原通道并存。

## Acceptance Criteria

- [ ] 子智能体调用 `asset_push(kind="url", payload={...})` 后，主智能体在 1 个调度周期内被唤醒，能读到该条目。
- [ ] `asset_push` 高频（10+ 次/秒）下 orchestrator 不死锁、不漏读（去重靠 `since_id`）。
- [ ] 写入 `[milestone]` / `[progress]` 黑板不触发 orchestrator 唤醒（行为不变）。
- [ ] 进程重启后 Registry 清空（明确的非持久化预期）。
- [ ] 单测：`test_asset_push_publishes_event`、`test_read_assets_since_cursor`、`test_blackboard_write_no_wakeup`。

## Implementation Plan

### Task 1：AssetFeedRegistry（内存存储）

新文件：`secbot/agent/asset_feed.py`

- `AssetEntry` dataclass：`id: int / kind: str / agent_name: str / payload: dict / created_at: datetime`
- `AssetFeedRegistry`：`{chat_id: list[AssetEntry]}` + 自增 id；提供 `append / since / group_by_kind`。
- 仿照 [BlackboardRegistry](file:///Users/shan/Downloads/nanobot/secbot/agent/blackboard.py)，通过 DI 注入到 subagent / orchestrator。

### Task 2：`asset_push` 工具（核心）

新文件：`secbot/agent/tools/asset_feed.py`

- 类似 `BlackboardWriteTool`，构造时注入 `registry / bus / origin / agent_name`。
- `execute(kind, payload)`：
  1. `entry = registry.append(chat_id, kind, agent_name, payload)`
  2. `await bus.publish_inbound(InboundMessage(channel="system", metadata={"injected_event": "asset_discovered", "count": 1, "kind": kind, "since_id": entry.id - 1}, ...))`
  3. 返回 `"asset pushed (id=...)"`。
- 支持 `kind` 枚举：`url / port / service / credential / vuln / tech`（在 prompt 中说明，不在工具内强校验）。

### Task 3：`read_assets` 工具

新文件：`secbot/agent/tools/asset_feed.py`（同上）

- `execute(kind?, since_id?)` → 按 chat_id 拉取增量资产（list of dict）。
- 限制单次返回 200 条，超出走分页。

### Task 4：注册到 subagent + orchestrator

- [secbot/agent/subagent.py:446 附近](file:///Users/shan/Downloads/nanobot/secbot/agent/subagent.py#L446)：注册 `AssetPushTool` + `ReadAssetsTool`。
- [secbot/agent/loop.py `_register_orchestrator_tools` / `_register_operational_tools`](file:///Users/shan/Downloads/nanobot/secbot/agent/loop.py#L632)：同步注册。
- orchestrator 收到 `injected_event="asset_discovered"` 时，下一 turn 自动注入 system 提示："新增资产 N 条（kind=...），可调用 read_assets 查看"。

### Task 5：黑板语义收敛 + prompt

- [secbot/agent/tools/blackboard.py](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/blackboard.py) `BlackboardWriteTool.description` 改为"仅写阶段总结 / 聚合统计；逐条资产走 asset_push"。
- 同步 [secbot/agents/prompts/](file:///Users/shan/Downloads/nanobot/secbot/agents/prompts) 下专家智能体提示词（asset_discovery、port_scan、crawl_web、vuln_detec、vuln_scan、weak_password）。

### Task 6：API + 前端

- [secbot/api/blackboard.py](file:///Users/shan/Downloads/nanobot/secbot/api/blackboard.py) 同侧新增 `secbot/api/asset_feed.py`：`GET /api/assets?chat_id=&kind=&since_id=`。
- 前端：黑板面板保持不变；新增"资产清单"侧栏（轮询或 WS 推送，MVP 先轮询）。

### Task 7：测试

- `tests/agent/test_asset_feed_registry.py`
- `tests/agent/tools/test_asset_push_tool.py`（含 bus event assertion）
- `tests/agent/tools/test_read_assets_tool.py`
- `tests/api/test_asset_feed_api.py`

## Out of Scope

- **不**入库 CMDB（明确选择内存方案）。
- **不**改造 teammate（持久 mailbox）通信。
- **不**实现"中止/重启已运行子智能体"的强制取消。
- **不**实现"运行时动态加载新 skill"（另起任务）。
- **不**做去重 / 合并逻辑（同一 URL 多次 push 会有多条记录）；后续按需求增加。

## PR 拆分建议

1. **PR-1**：Task 1 + 2 + 3 + 4（Registry / 工具 / 注册），核心机制。
2. **PR-2**：Task 5 黑板语义 + prompt。
3. **PR-3**：Task 6 API + 前端。
4. **PR-4**：Task 7 端到端测试与文档。

## Technical Notes

- 触点文件：
  - `secbot/agent/asset_feed.py`（新建）
  - `secbot/agent/tools/asset_feed.py`（新建）
  - [secbot/agent/subagent.py](file:///Users/shan/Downloads/nanobot/secbot/agent/subagent.py)
  - [secbot/agent/loop.py](file:///Users/shan/Downloads/nanobot/secbot/agent/loop.py)
  - [secbot/agent/tools/blackboard.py](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/blackboard.py)
  - [secbot/agents/prompts/](file:///Users/shan/Downloads/nanobot/secbot/agents/prompts)
  - `secbot/api/asset_feed.py`（新建）
- 既有事件注入参考：`subagent._announce_result` 中 `bus.publish_inbound`。
- 前端 `on_write` 黑板回调链路保持不变。
