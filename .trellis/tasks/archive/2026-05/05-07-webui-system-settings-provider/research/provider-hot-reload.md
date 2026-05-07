# Provider 热重载调研

## 结论（TL;DR）

**Agent loop 已经天然支持热重载，无需新代码。**
只要 `_handle_settings_update` 把新值写进 `config.json`，下一条用户消息进入时
`AgentLoop._refresh_provider_snapshot()` 会重新 load config + 对比 signature（覆盖
`api_key` / `api_base` / `model` / `extra_headers` 等），不同就自动重建 provider。
进行中的 turn 用旧 provider 跑完当前请求，不受影响。

## 关键调用链

**启动（一次性构造）**

1. `secbot/cli/commands.py:658` → `build_provider_snapshot(config)`
2. `secbot/providers/factory.py:117` → 返回 `ProviderSnapshot(provider, model, context_window_tokens, signature)`
3. `secbot/cli/commands.py:699` → AgentLoop 持有 `provider_snapshot_loader=load_provider_snapshot`（函数引用，非快照值！）

**运行时（每条消息）**

1. `secbot/agent/loop.py:922` → `_process_message()` 入口调 `_refresh_provider_snapshot()`
2. `secbot/agent/loop.py:348-358` → 调用 loader（每次都会重新 load config）→ 生成新 signature → 与 `self._provider_signature` 对比 → 不同则 `_apply_provider_snapshot(snapshot)`
3. `secbot/agent/loop.py:330-346` → 原子替换 `provider` / `model` / `runner.provider` / `subagents` / `consolidator` / `dream`

**Signature 覆盖范围**（`secbot/providers/factory.py:95-114`）

- `defaults.model`
- `defaults.provider`
- `get_provider_name(model)`
- `get_api_key(model)` ← 动态从 config 读
- `get_api_base(model)` ← 动态从 config 读
- `extra_headers` / `extra_body` / `region` / `profile`
- `max_tokens` / `temperature` / `reasoning_effort` / `context_window_tokens`

修改 `providers.custom.api_key` / `providers.custom.api_base` / `defaults.model` 任一都会
让 signature 变化 → 触发重建。

## 设置更新现状

`secbot/channels/websocket.py:720-751` `_handle_settings_update`：

- 目前只处理 `model` / `provider`，未处理 `api_key` / `api_base`
- 写磁盘用 `save_config(config)` → config.json 更新
- 返回 `requires_restart=changed` ← **这个标志实际可以恒为 `false`**，因为热重载自动发生

## 方案对比（历史记录，最终不采用热重载相关方案）

| 方案 | 结论 |
|---|---|
| A. 零缓存（每次都拿） | 当前就是这样，但带 signature 短路 |
| B. 主动 invalidate | 不需要，signature 已经能识别变化 |
| C. 事件总线广播 | 过度设计 |

## 对本任务的影响

- PR1/PR2 **不需要**任何 agent loop 改动
- `_settings_payload` 里 `requires_restart` 可以永远返回 `false`
- 唯一要做的是让 `_handle_settings_update` 接受 `api_key` / `api_base` 字段并调 `save_config`

## 边界与风险

1. **磁盘 I/O**：每条消息都会 re-load config.json（~3-5ms）。这是当前已有成本，不是本任务引入的。
2. **进行中的 turn**：`_apply_provider_snapshot` 只替换下一轮引用，当前 turn 仍用旧 provider（见注释 `Swap model/provider for future turns without disturbing an active one`），符合预期。
3. **多 channel / 多 worker**：每个 AgentLoop 实例各自 refresh，单进程无问题；若未来拆多进程，各自都会从磁盘重新读，也能工作。
4. **config 文件写入中途崩溃**：`save_config` 用 `open("w")` 非原子写，极端情况下可能读到半个文件，`load_config` 有 try/except 兜底（fallback 默认 config）。非本任务范围，但值得记一笔。

## 推荐

直接利用现有机制。PR1 只改 `_handle_settings_update` 和 `_settings_payload`，PR2 只改前端，PR3 写 `/model` 命令时依赖同一机制，不需要任何 reload hook。
