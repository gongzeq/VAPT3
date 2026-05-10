# Gap: 智能助手（HomePage）数据接口

## 前端数据需求清单

HomePage（`src/pages/HomePage.tsx` → `Shell.tsx` → `ThreadShell.tsx` + `PromptSuggestions.tsx`）当前混合使用真实接口 + 静态 mock：

### 对话核心（已有真实接口）

| 功能点 | 方法 | 路径 | 状态 | 备注 |
|--------|------|------|------|------|
| 新建会话 | WS | `{"type":"new_chat"}` | ✅ 已存在 | 隐式创建，无 HTTP 端点 |
| 列出会话 | GET | `/api/sessions` | ✅ 已存在 | 无搜索/归档/分页 |
| 获取会话消息 | GET | `/api/sessions/{key}/messages` | ✅ 已存在 | — |
| 删除会话 | GET | `/api/sessions/{key}/delete` | ✅ 已存在 | 语义应为 DELETE，已有 GET 兼容路径 |
| 发送消息（流式） | WS | `{"type":"message","chat_id":"...","content":"..."}` | ✅ 已存在 | — |
| 停止当前回复 | WS | `{"type":"stop","chat_id":"..."}` | ✅ 已存在 | — |
| 上传附件 | POST | `/v1/chat/completions` (multipart) | ✅ 已存在 | — |
| 列出快捷指令 | GET | `/api/commands` | ✅ 已存在 | — |
| 设置读取/更新 | GET | `/api/settings` / `/api/settings/update` | ✅ 已存在 | 不含语言/主题字段 |

### 右侧工作台（PromptSuggestions）— 全部静态 mock

| 模块 | 数据项 | 当前来源 | 后端接口状态 |
|------|--------|----------|-------------|
| **工作台速览** | 进行中任务数、今日新增告警数、本周扫描通过率 | `QUICK_STATS[]` 硬编码 | ❌ 无接口 |
| **快捷指令 chips** | 全网资产发现/弱口令检测/月度合规报告/CVE 影响排查 | `PROMPTS[]` 硬编码 | ❌ 无配置化接口 |
| **在线专家智能体** | 4 个 agent 名称/状态/图标 | `AGENTS[]` 硬编码 | 🔧 部分有，无实时状态 |

### 缺失的高级功能

| 功能点 | 方法 | 路径 | 状态 | 前端现状 |
|--------|------|------|------|----------|
| 搜索会话 | GET | `/api/sessions?q=...` | 🔧 待扩展 | 前端无搜索框 |
| 归档会话 | POST | `/api/sessions/{key}/archive` | 🛠️ 待开发 | 前端无归档功能 |
| 通知中心 | GET | `/api/notifications?unread=1` | 🛠️ 待开发 | Navbar 无铃铛图标 |
| 智能体实时状态 | GET | `/api/agents?include_status=true` | 🔧 待扩展 | PromptSuggestions 中状态为静态 mock |
| 实时黑板数据推送 | WS | `event:"blackboard_update"` | 🛠️ 待开发 | 未接入 |
| 智能体思维链推送 | WS | `event:"activity_event"` | 🛠️ 待开发 | 未接入 |
| 切换语言持久化 | GET/PUT | `/api/settings/update?language=zh-CN` | 🔧 待扩展 | 前端 i18n 仅本地切换 |

## 后端缺口

### 缺失接口（7 个）

| 端点 | 方法 | 说明 | 优先级 |
|------|------|------|--------|
| `GET /api/dashboard/summary` | GET | **复用 Dashboard 聚合接口** 作为工作台速览数据源 | P0 |
| `GET /api/agents?include_status=true` | GET | 在现有 `/api/agents` 基础上追加 `status/progress/current_task_id/last_heartbeat_at` | P0 |
| `GET /api/prompts` | GET | 快捷指令配置列表（管理员可动态调整） | P1 |
| `GET /api/sessions?q=...&archived=0\|1` | GET | 扩展现有列表接口：模糊搜索 + 归档过滤 + 分页 | P1 |
| `POST /api/sessions/{key}/archive` | POST | 归档/取消归档会话 | P1 |
| `GET /api/notifications` | GET | 通知中心列表 + unread_count | P2 |
| `POST /api/notifications/{id}/read` | POST | 单条已读 | P2 |

### `GET /api/prompts` — 快捷指令配置化接口

**响应 200**
```json
{
  "prompts": [
    {
      "key": "scanAsset",
      "title": "全网资产发现",
      "subtitle": "扫描内网所有存活主机并入库 CMDB",
      "prefill": "对资产 192.168.1.0/24 发起一次轻量端口扫描，重点看 Web 服务",
      "icon": "Radar"
    },
    {
      "key": "weakPwd",
      "title": "弱口令检测",
      "subtitle": "SSH/RDP/SMB 常见服务字典爆破",
      "prefill": "对最近一周新增的资产做一轮弱口令探测，结果按高危聚合",
      "icon": "Key"
    },
    {
      "key": "summarize",
      "title": "月度合规报告",
      "subtitle": "汇总当月扫描数据导出 PDF",
      "prefill": "把今天的扫描发现按业务系统聚合，生成一份执行摘要",
      "icon": "FileText"
    },
    {
      "key": "drill",
      "title": "CVE 影响排查",
      "subtitle": "输入 CVE 编号，自动定位受影响资产",
      "prefill": "针对最近一条高危漏洞，给我一个验证 PoC 与修复建议",
      "icon": "Bug"
    }
  ]
}
```

**实现建议**：
- 初版：从 `secbot/agents/` 目录下的 YAML 文件或配置文件读取，无需数据库表
- 进阶：支持管理员通过 `/api/prompts` PUT 接口在线修改（延后到平台设置功能落地后）

### 缺失 WebSocket 事件（3 个）

| 事件 | 说明 | 使用场景 |
|------|------|----------|
| `blackboard_update` | 聚合 stats 推送（discovered_assets/open_ports/critical_findings） | PromptSuggestions 实时刷新工作台速览 |
| `activity_event` | 单条智能体活动（thought/tool_call/tool_result） | 未来 TaskDetail 页思维链 |
| `task_update` | 任务状态/进度/KPI 变化 | PromptSuggestions 中 agent 状态实时更新 |

### 数据模型缺口

1. **Agent 缺少运行时状态表**
   - 当前 `/api/agents` 返回的是 YAML 注册表静态信息（`name/display_name/description/scoped_skills`）
   - 前端需要运行时状态：`idle|running|queued|offline`、`progress`、`current_task_id`、`last_heartbeat_at`
   - **建议**：在 `secbot/agent/subagent.py` 或心跳服务中维护一个内存/Redis 状态表，由 HTTP 接口读取

2. **会话缺少 `archived` 标志**
   - 当前 `ChatSummary` 类型和 `_handle_sessions_list` 均无 `archived` 字段
   - **建议**：在 session 存储层（JSONL metadata 或内存）新增 `archived: boolean`，默认 false

3. **通知中心无数据模型**
   - 当前后端无任何 notification 表或队列
   - **建议**：可先用内存队列（`secbot/channels/websocket.py` 内维护）过渡，后续迁移到表

## Mock 数据现状

| 模块 | 位置 | 切换成本 |
|------|------|----------|
| 工作台速览 KPI | `PromptSuggestions.tsx` 内 `QUICK_STATS[]` | 低：替换为 `useDashboardSummary()` hook |
| 快捷指令 chips | `PromptSuggestions.tsx` 内 `PROMPTS[]` | 中：建议后端提供 `/api/prompts` 配置化接口 |
| 在线智能体列表 | `PromptSuggestions.tsx` 内 `AGENTS[]` | 低：替换为 `useAgents({ includeStatus: true })` |

## 已有但可直接复用的后端能力

| 能力 | 位置 | 用途 |
|------|------|------|
| `SessionManager` + `list_sessions()` | `secbot/session/manager.py` | 会话列表、消息读取、删除 |
| `AgentRegistry` | `secbot/agents/registry.py` | `/api/agents` 静态信息源 |
| `SubagentManager` + `SubagentStatus` | `secbot/agent/subagent.py` | 运行时任务状态追踪（可扩展为 agent 状态源） |
| `HeartbeatService` | `secbot/heartbeat/` | 定时任务执行记录，可作为 agent 心跳参考 |

## 建议后续任务

1. **P0 — 工作台速览接入 Dashboard Summary**（0.5d）
   - 前端 `PromptSuggestions` 中的 `QUICK_STATS` 直接复用 `GET /api/dashboard/summary` 的子集字段
   - 无需新增后端接口，与 Dashboard 共用同一份聚合数据

2. **P0 — Agent 实时状态扩展**（1-2d）
   - 后端：在 `/api/agents` 响应中追加运行时字段（从 subagent/heartbeat 读取）
   - 前端：`PromptSuggestions` 中 `AGENTS[]` 替换为动态请求 + WebSocket `task_update` 事件

3. **P1 — 会话搜索与归档**（1-2d）
   - 后端：扩展 `/api/sessions` 支持 `q/archived/limit/offset`
   - 前端：Sidebar 顶部增加搜索输入框 + 归档筛选 tab

4. **P1 — 快捷指令配置化**（1d）
   - **已确认**：提供 `/api/prompts` 配置化接口，让后端/管理员动态调整快捷指令
   - 接口设计：`GET /api/prompts` → `{ "prompts": [{"key":"scanAsset","title":"全网资产发现","subtitle":"...","prefill":"...","icon":"Radar"}] }`

5. **P2 — 通知中心**（2-3d）
   - 后端：内存通知队列 + `/api/notifications` 端点
   - 前端：Navbar 增加铃铛图标 + 下拉面板
