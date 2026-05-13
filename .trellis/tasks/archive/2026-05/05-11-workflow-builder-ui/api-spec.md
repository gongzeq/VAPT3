# 工作流构建器 · 接口规范（API Spec v0.1）

> 范围：WebUI ↔ Secbot 后端之间的 HTTP REST 与 WebSocket 事件。
> 所有 HTTP 路径以 `/api` 为前缀；所有字段统一使用 **camelCase**（对齐现有 `secbot/cron/service.py::_save_store` 序列化约定）。
> 鉴权：沿用现有 Bearer token（来自 `bootstrap` 接口），请求头 `Authorization: Bearer <token>`。

---

## 1. 数据模型

### 1.1 Workflow

```jsonc
{
  "id": "wf_9a2b",                          // 8 字节 hex
  "name": "内网资产发现 + 端口指纹",
  "description": "每日 09:00 扫描 C 段并生成报告",
  "tags": ["recon", "daily"],
  "inputs": [ /* WorkflowInput[] */ ],
  "steps":  [ /* WorkflowStep[]  */ ],
  "scheduleRef": "cron_3f21",               // 关联的 cron jobId，可为空
  "createdAtMs": 1715412000000,
  "updatedAtMs": 1715412000000
}
```

### 1.2 WorkflowInput

> 字段层级全部由创建者自定义，**系统不预设任何字段名 / 类型 / 是否必填**。`required` 仅控制能否留空不传，不代表某个具体名称必须存在。以下两个示例仅展示不同 `type` 的字段形态，名称 `param_a` / `param_b` 为中性占位，不暗示任何业务语义。

示例A（基础 `type=string`）：

```jsonc
{
  "name": "param_a",                        // 变量名，只允许 [a-z0-9_]
  "label": "自定义入参 A",                  // UI 标签，由创建者填写
  "description": "（可选）一句话说明该入参用途",
  "type": "string",                         // string | cidr | int | bool | enum
  "required": true,
  "default": null,                          // 可选默认值
  "enumValues": null                        // 仅 type=enum 时有值
}
```

示例B（`type=enum` 需使用 `enumValues`）：

```jsonc
{
  "name": "param_b",
  "label": "自定义枚举 B",
  "description": null,
  "type": "enum",
  "required": false,
  "default": "b",
  "enumValues": ["a", "b", "c"]
}
```

可选 `type` 枚举：`string | cidr | int | bool | enum`（后续可扩充 `stringArray` 等）。`cidr` 在 `WorkflowRunner` 侧使用 `ipaddress.ip_network(strict=False)` 校验。

### 1.3 WorkflowStep

```jsonc
{
  "id": "s2",                               // 工作流内唯一
  "name": "脚本筛选 ERROR",
  "kind": "script",                         // tool | script | agent | llm
  "ref": "python",                          // ref 的含义随 kind 变化，见下表
  "args": { /* 随 kind 变化，见下方示例 */ },
  "condition": null,                        // 为空则始终执行；否则为受限表达式
  "onError": "stop",                        // stop | continue | retry
  "retry": 0
}
```

#### 四种 kind 的 `ref` / `args` 契约

| kind | `ref` 语义 | `args` schema |
|------|------------|---------------|
| `tool`   | 已注册工具名（`file_read` / `shell` / `message` / `web` / `search` …），由 `GET /_tools` 提供 | 依工具自身 `inputSchema` 动态渲染 |
| `script` | `python` \| `shell` | `{ code: string, timeoutMs?: number, env?: Record<string,string>, stdin?: string }` |
| `agent`  | YAML 智能体名（`asset_discovery` / `port_scan` / `report` …），由 `GET /_agents` 提供 | 依智能体自身 `inputSchema` 动态渲染 |
| `llm`    | 固定为 `chat`（`ref` 不做 provider 选择——由**全局 LLM 配置**决定 provider/model） | `{ systemPrompt: string, userPrompt: string, temperature?: number, maxTokens?: number, responseFormat?: "text" \| "json" }` |

**统一返回契约**（写入 `WorkflowRun.stepResults.<stepId>`，对 4 种 kind 一致）：

```jsonc
{
  "status": "ok",                           // ok | error | skipped | retried
  "startedAtMs": 1715412000500,
  "finishedAtMs": 1715412003000,
  "durationMs": 2500,
  "output": { /* kind 决定 shape，见下 */ },
  "error":  null
}
```

- `tool` / `agent` / `script`：`output` 为执行体原始结构化返回（工具/智能体遵循各自 `outputSchema`；script 将 stdout 按 JSON 优先解析，否则原样 `{ stdout, stderr, exitCode }`）
- `llm`：`output = { text: string, tokens: { prompt: number, completion: number }, finishReason: string }`

> **工作流终态的结果形态不固定**：可能是 `llm.text`（如日志诊断）、任意 tool/agent 的结构化输出（如 `report` 生成的 PDF 路径）、或仅为副作用（如 `tool:message` 推送 slack 后无业务产物）。前端按最后一个非 condition step 的 `output` 渲染查看入口（文本面板 / 下载链接 / 空态）。

> 所有 kind 输出均可被后续 step 通过 `${steps.<id>.result.<jsonpath>}` 引用（D6）。

#### 四种 kind 示例

```jsonc
// kind=tool —— 读取日志
{ "id": "s1", "name": "读取日志", "kind": "tool", "ref": "file_read",
  "args": { "path": "${inputs.log_path}", "maxBytes": 262144 } }
```

```jsonc
// kind=script —— 筛选 ERROR 行
{ "id": "s2", "name": "脚本筛选 ERROR", "kind": "script", "ref": "python",
  "args": {
    "code": "import json,sys\nlines=stdin_text.splitlines()\nerr=[l for l in lines if 'ERROR' in l]\nprint(json.dumps({'errors':len(err),'samples':err[:20]}))",
    "stdin": "${steps.s1.result.content}",
    "timeoutMs": 15000
  } }
```

```jsonc
// kind=agent —— 专家智能体
{ "id": "s3", "name": "端口扫描", "kind": "agent", "ref": "port_scan",
  "args": { "target": "${inputs.target_ip}", "threads": 50 } }
```

```jsonc
// kind=llm —— SRE 视角诊断（provider/model 由全局配置决定，step 只关心 prompt 与输出格式）
{ "id": "s4", "name": "LLM 诊断", "kind": "llm", "ref": "chat",
  "args": {
    "systemPrompt": "你是资深 SRE，根据日志样本给出 3 条最可能的根因假设，按严重度排序。",
    "userPrompt": "errors=${steps.s2.result.errors}\n样本:\n${steps.s2.result.samples}",
    "temperature": 0.2,
    "maxTokens": 800,
    "responseFormat": "text"
  } }
```

**模板插值语法**（由 `WorkflowRunner` 解析，不在前端做求值）：

| 语法 | 含义 |
|------|------|
| `${inputs.<name>}` | 引用工作流 inputs 中的值 |
| `${steps.<stepId>.result.<jsonpath>}` | 引用前序 step 执行结果（4 种 kind 统一生效） |
| `${env.<key>}` | 引用后端 config 暴露的只读环境变量（白名单） |

**condition 表达式**（受限子集，禁止 `__import__` / 属性 `_` 前缀）：
- 运算：`+ - * / % == != > >= < <= and or not in`
- 变量：仅 `inputs.*`、`steps.<id>.result.*`、`steps.<id>.status`
- 典型示例：`steps.s2.result.errors > 0`（日志分析场景的早退判定）

### 1.4 WorkflowRun

```jsonc
{
  "id": "run_7c80",
  "workflowId": "wf_9a2b",
  "startedAtMs": 1715412000000,
  "finishedAtMs": 1715412180000,
  "status": "ok",                           // running | ok | error | cancelled
  "inputs": { "param_a": "<用户自定义入参的实际值>" },
  "stepResults": {
    "s1": {
      "status": "ok",                       // ok | error | skipped | retried
      "startedAtMs": 1715412000500,
      "finishedAtMs": 1715412030000,
      "durationMs": 29500,
      "output": { "openPorts": 183, "highRisk": 3 },
      "error": null
    }
  },
  "trigger": "manual",                      // manual | cron | api
  "error": null
}
```

---

## 2. REST 接口

### 2.1 工作流 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workflows` | 列表，支持 `?tag=&status=&search=` 过滤 |
| POST | `/api/workflows` | 创建，body=Workflow（无 id，后端生成） |
| GET | `/api/workflows/{id}` | 详情 |
| PUT | `/api/workflows/{id}` | 全量更新 |
| PATCH | `/api/workflows/{id}` | 增量更新（仅提供的字段） |
| DELETE | `/api/workflows/{id}` | 删除（会级联删除绑定的 cron job） |

**GET /api/workflows 响应样例**：

```json
{
  "items": [ /* Workflow[] */ ],
  "total": 12,
  "stats": {
    "running": 1,
    "scheduled": 5,
    "failed24h": 0
  }
}
```

### 2.2 运行控制

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workflows/{id}/run` | 立即运行。body：`{ "inputs": {...} }` |
| POST | `/api/workflows/{id}/cancel` | 取消当前正在运行的 run（若有） |
| GET | `/api/workflows/{id}/runs` | 最近运行记录，支持 `?limit=20` |
| GET | `/api/workflows/{id}/runs/{runId}` | 单次 run 详情 |

**POST /run 响应**：

```json
{ "runId": "run_7c80", "status": "running" }
```

### 2.3 调度管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workflows/{id}/schedule` | 创建或更新调度 |
| DELETE | `/api/workflows/{id}/schedule` | 解除调度 |

**POST /schedule 请求 body**：

```json
{
  "kind": "cron",                           // at | every | cron
  "cronExpr": "0 9 * * *",
  "tz": "Asia/Shanghai",
  "atMs": null,
  "everyMs": null,
  "inputs": { "param_a": "<用户自定义入参的实际值>" },
  "enabled": true
}
```

后端实现：转换为 `CronPayload(kind="agent_turn", message="__workflow__:{id}:{inputsJson}", deliver=false)`，调用 `CronService.add_job`/`update_job`，并把返回的 `cronJobId` 写回 `workflow.scheduleRef`。

### 2.4 元数据端点（供编辑器下拉 / Schema 驱动表单）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workflows/_tools` | 列出 `kind=tool` 可选的工具（来自 `secbot/agent/tools/*`，含内置 `upload`——由前端唤起文件/文本上传弹层） |
| GET | `/api/workflows/_agents` | 列出 `kind=agent` 可选的子智能体（来自 `secbot/agents/*.yaml`） |
| GET | `/api/workflows/_templates` | 列出预置工作流模板 |

> `kind=script` 固定两个 `ref`（`python` / `shell`），不需要独立端点；前端硬编码下拉即可。
> `kind=llm` 固定 `ref=chat`，**不提供 `/_providers` 端点**——Runner 直接使用全局 LLM 配置（`secbot/providers/factory.py::create_default()`）；如需切换 provider，请改全局配置。

**/_tools 响应样例**：

```json
{
  "items": [
    {
      "name": "file_read",
      "title": "读取本地文件",
      "description": "读取路径下文本，返回 content 字段",
      "inputSchema": {
        "type": "object",
        "properties": {
          "path":     { "type": "string" },
          "maxBytes": { "type": "integer", "default": 262144 }
        },
        "required": ["path"]
      },
      "outputSchema": { "type": "object", "properties": { "content": { "type": "string" } } }
    }
  ]
}
```

**/_agents 响应样例**：

```json
{
  "items": [
    {
      "name": "port_scan",
      "title": "端口扫描智能体",
      "description": "并行扫描目标 IP/CIDR 的开放端口，输出指纹",
      "inputSchema": {
        "type": "object",
        "properties": {
          "target":  { "type": "string", "description": "IP / CIDR" },
          "threads": { "type": "integer", "default": 50 }
        },
        "required": ["target"]
      },
      "outputSchema": { /* JSON Schema */ }
    }
  ]
}
```

---

## 3. WebSocket 事件

沿用现有 WS 通道（`bootstrap.wsPath`）。所有事件外层结构：

```jsonc
{ "type": "workflow.run.started", "ts": 1715412000000, "data": { /* payload */ } }
```

| `type` | `data` 字段 | 说明 |
|--------|------------|------|
| `workflow.run.started` | `{ runId, workflowId, inputs }` | 开始执行 |
| `workflow.step.started` | `{ runId, stepId, name }` | 单步开始 |
| `workflow.step.progress` | `{ runId, stepId, message, pct? }` | 单步进度心跳（可选） |
| `workflow.step.finished` | `{ runId, stepId, status, durationMs, output }` | 单步完成 |
| `workflow.run.finished` | `{ runId, status, durationMs }` | 运行结束 |
| `workflow.run.failed` | `{ runId, stepId?, error }` | 运行失败 |
| `workflow.run.cancelled` | `{ runId }` | 手动取消 |
| `workflow.schedule.updated` | `{ workflowId, nextRunAtMs }` | 调度变更通知（跨客户端同步） |

客户端订阅方式（与现有 chat 事件一致，不需单独订阅命令；服务端广播给所有认证连接）。

---

## 4. 错误码

统一使用 HTTP 状态码 + 业务错误体：

```json
{ "error": { "code": "workflow.validation.input_missing", "message": "input 'param_a' is required" } }
```

| HTTP | code 前缀 | 触发场景 |
|------|-----------|---------|
| 400 | `workflow.validation.*` | 字段校验失败（必填/类型/枚举/cron 表达式） |
| 400 | `workflow.validation.llm_config` | `kind=llm` 的 step 缺 `systemPrompt` / `userPrompt`，或全局 LLM 配置尚未就绪 |
| 400 | `workflow.validation.script_config` | `kind=script` 的 step 缺 `code` 或 `ref` 不是 `python` / `shell` |
| 404 | `workflow.not_found` / `run.not_found` | id 不存在 |
| 409 | `workflow.run.in_progress` | 重复触发 |
| 422 | `workflow.dag.invalid` | 结果引用的前序 step 不存在；condition 语法错 |
| 424 | `workflow.executor.tool_failed` / `workflow.executor.script_timeout` / `workflow.executor.agent_failed` / `workflow.executor.llm_failed` | 单步执行体失败（runner 按 `onError` 决定是否终止） |
| 500 | `workflow.runner.internal` | Runner 内部异常 |

---

## 5. 兼容性 & 版本

- `apiVersion` 字段不放在 URL；响应头带 `X-Api-Version: workflow/1`
- 模型字段新增遵循"向前兼容"：服务端返回新字段时客户端忽略即可
- 破坏性变更须在 `prd.md::Out of Scope` 上提 ADR
