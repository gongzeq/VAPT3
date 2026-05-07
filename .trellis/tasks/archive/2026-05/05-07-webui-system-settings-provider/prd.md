# WebUI 系统设置：Provider 端点 / API Key / /model 命令

## Goal

让用户不用改配置文件、不用重启就能在 Web UI 里接入任意 OpenAI 兼容的 LLM 服务，并在对话中用 `/model` 切换模型。

## Requirements

1. **设置页新增「OpenAI 兼容端点」区块**（复用现有 `providers.custom` 数据结构）：
   - `API Key`：password 输入框，支持眼睛切换显隐。
   - `Base URL`：endpoint URL 输入框，如 `https://api.openai.com/v1` 或 `http://localhost:11434/v1`。
   - 保留既有 `Model` 输入。
   - 原来的 `Provider` 下拉隐藏或固定为 `custom`（由实现阶段决定具体 UI），`provider=auto` 仍可工作。
2. **`/api/settings` 调整**（受 `websockets` 库限制，HTTP 方法必须是 GET 且无 body；见下方约束说明）：
   - `GET /api/settings` 返回 `custom.api_base` 明文、`custom.api_key_masked`（如 `sk-****abcd`）。
   - `GET /api/settings/update` 作为写入端点：
     - **非敏感字段走 URL query**：`model`、`api_base`（URL 本身常公开，非敏感）。
     - **敏感字段走自定义请求头**：`X-Settings-Api-Key`（浏览器 fetch 通过 headers 传递，不进 URL / access log）。
   - 保留语义：
     - `X-Settings-Api-Key` header **不存在** → 保留原 Key。
     - header 存在且非空 → 更新 Key。
     - header 存在且为空串 → 清空 Key。
     - URL query 字段省略 → 不修改；传空串 → 清空（仅对 `api_base` 有意义，`model` 空串拒绝）。
3. **热重载**：保存后下一轮消息自动生效（无需额外代码，见 Technical Approach）。
4. **`/model` 斜杠命令**：
   - `/model`：调用 `GET {api_base}/v1/models` 拉列表，在对话里渲染为可点击按钮（复用现有 `buttons` 协议）；加 60 秒内存缓存。
   - `/model <name>`：把 `name` 写入 `config.agents.defaults.model`（全局生效），触发热重载，回执当前模型。
   - 拉取失败时输出错误提示，引导用户 `/model <name>` 手动输入。
5. **安全**：
   - API Key 绝不出现在 URL 查询串、日志、session payload、`/status` 输出中。
   - WebUI Input 使用 `type="password"`，默认展示脱敏值；未修改保存时保持原值。

## Acceptance Criteria

- [ ] 设置页可填 API Key / Base URL / Model 并保存成功；刷新后 Base URL 明文回显，Key 显示为 `sk-****abcd` 脱敏形式。
- [ ] 未修改 Key 直接点 Save，不会清空已保存的 Key。
- [ ] 保存后无需重启即可开新会话对话成功（至少在 OpenAI 和 Ollama 两类端点上验证）。
- [ ] `/model` 在能拉到 `/v1/models` 的端点上渲染出可点击按钮；点击或 `/model <name>` 切换后立即回执并生效。
- [ ] `/model` 拉取失败时给出人类可读的错误，并提示 `/model <name>` 备用路径。
- [ ] `grep api_key` 不会在 WebSocket 帧、HTTP access log、session 历史里发现明文 Key。
- [ ] 单元/集成测试覆盖：settings POST JSON、脱敏回显、`/model` 路由 + fetch + 错误分支。

## Definition of Done

- 测试：更新 `tests/channels/test_websocket_channel.py`、新增 `tests/command/test_model_command.py`、`webui/src/tests` 覆盖新 UI。
- `pytest` / `ruff` / webui `vitest` / `tsc` 全绿。
- 文档：`docs/configuration.md` 或 `docs/quick-start.md` 新增「从 WebUI 接入 OpenAI 兼容端点」一节。

## Technical Approach

**后端（写入路径）**

- 在 `secbot/channels/websocket.py` 改 `_handle_settings_update`（保持 GET 方法）：
  - 从 `_parse_query(request.path)` 读 `model`、`api_base`。
  - 从 `request.headers.get("X-Settings-Api-Key")` 读 API Key（header 缺失 = 保留；空串 = 清空；非空 = 更新）。
  - 读写 `config.providers.custom.{api_key, api_base}`；`model` 继续写 `defaults.model`。
- `_settings_payload` 新增 `custom.api_key_masked`、`custom.api_base`；`requires_restart` 始终返回 `false`（热重载已天然支持）。
- **敏感 header 处理**：
  - 不把 `X-Settings-Api-Key` header 的值写进任何日志 / `logger.info` / session 事件。
  - 其他地方已有 `Authorization: Bearer <token>` 的 header 使用范式可参考。
- **热重载机制已存在**（见调研 [`research/provider-hot-reload.md`](research/provider-hot-reload.md)）：
  - `AgentLoop._process_message` 每条消息前调 `_refresh_provider_snapshot()`，通过 `load_provider_snapshot()` 重新加载磁盘 config 并对比 signature（signature 覆盖 model/api_key/api_base/extra_headers 等）。
  - 保存 config.json → 下一轮消息自动拉新值 → signature 变化 → provider 重建。**零改动**。
  - 当前会话正在进行的 turn 用旧 provider 完成，不受影响。
- `/model` 命令：
  - 注册在 `register_builtin_commands`，`exact("/model", ...)` + `prefix("/model ", ...)`。
  - 列表：`httpx.AsyncClient.get(f"{api_base}/v1/models", headers={"Authorization": f"Bearer {key}"})`，按 `data[].id` 渲染 buttons；60s TTL 内存缓存。
  - 设置：写 `defaults.model`，`save_config`，触发热重载，返回 `Model set to ...`。

**前端**

- `webui/src/lib/types.ts` `SettingsPayload` 扩展 `custom: { api_base: string; api_key_masked: string }`。
- `webui/src/lib/api.ts` `updateSettings`：保持 GET；`model` / `api_base` 放 URL query；**仅当用户修改了 Key** 时附加 `X-Settings-Api-Key` header（携带用户输入的新值或空串）。
- `webui/src/components/settings/SettingsView.tsx` 新增两行：API Key（`type=password` + 眼睛切换；初始显示 masked，用户点击输入后视为修改）、Base URL。隐藏 Provider 下拉或固定为 `custom`。
- 复用既有 buttons 渲染（`MessageBubble` 已支持）展示 `/model` 返回的模型列表。

## Decision (ADR-lite)

- **Context**：需要在 UI 里为无法改 JSON config 的用户提供 OpenAI 兼容接入；同时保留多 provider 的能力。
- **Decision**：
  1. UI 面向「OpenAI 兼容」单一形态，数据落到 `providers.custom`。
  2. `/model` 走 `GET /v1/models` 动态列表 + `/model <name>` 手动 fallback，写全局默认并热重载。
  3. 更新接口保持 GET；`model`/`api_base` 走 URL query，API Key 走自定义请求头 `X-Settings-Api-Key`；Key 脱敏回显、保留语义（header 缺失 = 不改）。
- **Consequences**：
  - 用户继续在 JSON config 中手工维护的非 custom provider 不受影响。
  - 热重载**已有机制**，PR 不需要动 agent loop。
  - 受 `websockets` 库限制被迫使用 GET+header 模式；偏离常规 REST 风格，但已由 `/api/sessions/{key}/delete` 这类现有路由树立先例。
  - `/v1/models` 拉不到时用户要知道手动 `/model <name>`。

## Out of Scope

- 多套 endpoint 档案（profiles/presets）、切换预设。
- 非 OpenAI 格式（Anthropic messages、Bedrock Converse、Responses API）在 UI 的接入。
- 团队/多用户密钥托管、加密存储。
- per-session model override（只做全局）。

## Implementation Plan (small PRs)

- **PR1 — 后端数据与 API 改造**
  - `_settings_payload` 返回 `custom.api_base`、`custom.api_key_masked`；`requires_restart` 始终 `false`。
  - `_handle_settings_update`（GET）：URL query 读 `model`/`api_base`；`X-Settings-Api-Key` header 读 Key；保留语义（header 缺失 = 不改，空串 = 清空）。
  - 前端 `types.ts` SettingsPayload 扩展 `custom`；`api.ts` `updateSettings` 支持 `apiKey` 可选参数（附加 header）。
  - 测试：settings 新字段、脱敏回显、header 缺失保留 / 空串清空 / 非空更新、明文 Key 不落 URL query 不落日志。
- **PR2 — WebUI 表单**
  - SettingsView 新增 API Key / Base URL 输入（password + 眼睛切换）；Provider 下拉隐藏或固定 `custom`。
  - 因热重载已天然支持，**无需**后端改动；提示文案去掉「重启生效」。
  - 测试：UI 交互 + 保存后下一轮对话用新端点（可用集成测试验证）。
- **PR3 — `/model` 命令**
  - `register_builtin_commands` 注册 `exact("/model")` + `prefix("/model ")`，新增 `BUILTIN_COMMAND_SPECS` 条目。
  - `/v1/models` 拉取 + 60s 缓存 + buttons 渲染；失败 fallback 提示。
  - `/model <name>` 写 `defaults.model` + `save_config`（依靠现有热重载）。
  - 测试：路由、fetch 成功/失败、设置落盘。
- **PR4 — 文档**
  - `docs/configuration.md` / `docs/quick-start.md` 补图文说明。

## Research References

- [`research/provider-hot-reload.md`](research/provider-hot-reload.md) — Agent loop 每 turn 自动比对 signature，热重载已然支持，无需新代码。

## Technical Notes

- 相关文件：
  - `webui/src/components/settings/SettingsView.tsx`
  - `webui/src/lib/api.ts` / `webui/src/lib/types.ts`
  - `secbot/channels/websocket.py`（`_settings_payload` / `_handle_settings_update`）
  - `secbot/config/schema.py`（`ProvidersConfig.custom`） / `secbot/config/loader.py`
  - `secbot/command/builtin.py` / `secbot/command/router.py`
  - `secbot/providers/registry.py`（`custom` spec → `openai_compat` backend）
- **已知约束（已验证）**：`websockets` 库 HTTP 解析器硬校验 method = `GET`（`Request.parse` 里 `if method != b"GET": raise ValueError`），`Request` 对象只有 `path` 和 `headers`，无 `body` / `method` 字段。因此 POST / PUT / DELETE 都不可用；body 也不可用。本任务最终采用 **GET + URL query（非敏感）+ 自定义请求头（敏感 Key）** 方案。
- 热重载：**已然天成**。`AgentLoop._refresh_provider_snapshot` 每条消息前重新 load config + 对比 signature，signature 覆盖 `api_key`/`api_base`/`model` 等。无需新增 reload hook。详 [`research/provider-hot-reload.md`](research/provider-hot-reload.md)。

