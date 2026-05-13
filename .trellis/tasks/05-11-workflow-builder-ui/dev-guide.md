# 工作流构建器 · 开发指南（Developer Guide v0.1）

> 读者：需要实现 / 维护「工作流构建器」子系统的后端 / 前端开发者。
> 前置阅读：[`prd.md`](prd.md)、[`api-spec.md`](api-spec.md)、`.trellis/tasks/05-09-uiux-template-refactor/prototypes/*.html`。

---

## 1. 模块总览

```
secbot/
├── workflow/                     # 新增模块
│   ├── __init__.py
│   ├── types.py                  # dataclass: Workflow / WorkflowStep / WorkflowInput / WorkflowRun / StepResult
│   ├── store.py                  # 持久化 + 并发安全（抄 cron/service.py 的 atomic_write + filelock）
│   ├── runner.py                 # WorkflowRunner：依 step.kind 分派到四种 executor
│   ├── expr.py                   # 表达式求值（sandbox）+ 模板插值
│   ├── executors/                # 四种 kind 的执行体，统一返回 StepResult
│   │   ├── __init__.py
│   │   ├── base.py               # StepExecutor 抽象基类 + 统一 timing / error 包装
│   │   ├── tool.py               # kind=tool  → tool_registry.get(ref).run(**args)
│   │   ├── script.py             # kind=script → 包装 shell 工具，timeout + stdin 注入
│   │   ├── agent.py              # kind=agent  → agent_registry.get(ref).run(args)
│   │   └── llm.py                # kind=llm    → providers.factory.create_default().chat(messages…)   (provider 由全局配置决定)
│   ├── templates.py              # 预置工作流模板（日志分析 / 内网扫描 / 邮箱巡检…）
│   └── service.py                # WorkflowService：对外门面，组装 store/runner/cron/executors
├── api/
│   └── server.py                 # +路由注册（/_tools、/_agents、/_templates；**不含** /_providers：LLM 直接使用全局配置）
└── secbot.py                     # +启动时装配 WorkflowService，+cron 回调识别 __workflow__:
webui/src/
├── pages/
│   ├── WorkflowListPage.tsx      # /workflows
│   └── WorkflowDetailPage.tsx    # /workflows/:id（4 Tab）
├── components/workflow/
│   ├── StepEditor.tsx            # 根据 step.kind 动态切换子表单（见 §3.2）
│   ├── StepCard.tsx              # 左侧色条 + kind 徽章（tool=蓝 / script=紫 / agent=靛 / llm=粉）
│   ├── InputsEditor.tsx          # 字段完全自定义，无任何预置名称
│   ├── ScheduleTab.tsx
│   ├── RunHistoryTab.tsx
│   ├── ConditionField.tsx
│   ├── kind-forms/               # 按 kind 拆的子表单
│   │   ├── ToolArgsForm.tsx      # 由 _tools JSON Schema 驱动；`ref=upload` 特例 → 渲染为文件/文本上传弹层（写入 inputs/media 后再驱动后续 step）
│   │   ├── ScriptArgsForm.tsx    # Monaco editor + timeoutMs + stdin 模板
│   │   ├── AgentArgsForm.tsx     # 由 _agents JSON Schema 驱动
│   │   └── LlmArgsForm.tsx       # systemPrompt / userPrompt / temperature / maxTokens / responseFormat（**不选 provider**——使用全局 LLM 配置）
│   └── TemplateGallery.tsx
├── lib/
│   └── workflow-client.ts        # REST + WS 订阅封装
└── i18n/{zh,en}.json             # +workflow.* 词条
```

---

## 2. 后端关键流程

### 2.1 启动装配（`secbot/secbot.py`）

```python
# 伪代码
cron_service = CronService(store_path=...)
workflow_service = WorkflowService(
    store_path=config_dir / "workflows" / "workflows.json",
    runs_path=config_dir / "workflows" / "runs.jsonl",
    tool_registry=tool_registry,
    agent_registry=agent_registry,
    bus=event_bus,
)

async def _on_cron_job(job: CronJob) -> str | None:
    msg = job.payload.message or ""
    if msg.startswith("__workflow__:"):
        _, wf_id, inputs_json = msg.split(":", 2)
        inputs = json.loads(inputs_json)
        await workflow_service.run(wf_id, inputs, trigger="cron")
        return None  # 不走 agent_turn
    return await default_agent_turn_handler(job)

cron_service.on_job = _on_cron_job
```

**要点**：
- 不改动 `CronPayload` 结构，仅通过 `message` 前缀派发，保持向后兼容
- `workflow_service.run` **不阻塞 cron 定时器**：内部 `asyncio.create_task` 跑 runner，立刻返回

### 2.2 WorkflowRunner 执行循环 + 四 kind 分派

```python
async def run(self, wf: Workflow, inputs: dict, *, trigger: str) -> WorkflowRun:
    self._validate_inputs(wf.inputs, inputs)            # 必填 / 类型 / 枚举
    run = WorkflowRun(id=new_id(), workflow_id=wf.id,
                      started_at_ms=now_ms(), status="running",
                      inputs=inputs, step_results={}, trigger=trigger)
    self.bus.publish("workflow.run.started", {...})
    try:
        ctx = {"inputs": inputs, "steps": {}}
        for step in wf.steps:
            if step.condition and not expr.eval_bool(step.condition, ctx):
                run.step_results[step.id] = _skipped()
                continue

            args   = expr.interpolate(step.args, ctx)   # ${inputs.x} / ${steps.s1.result.y}
            result = await self._exec_with_retry(step, args)   # 四 kind 分派 + retry

            run.step_results[step.id] = result
            ctx["steps"][step.id] = {"result": result.output, "status": result.status}

            if result.status == "error" and step.on_error == "stop":
                run.status = "error"
                run.error  = result.error
                break
        else:
            run.status = "ok"
    except Exception as e:
        run.status = "error"
        run.error  = str(e)
    finally:
        run.finished_at_ms = now_ms()
        self._append_run(run)
        self.bus.publish("workflow.run.finished", {...})
    return run


async def _exec_step(self, step: WorkflowStep, args: dict) -> StepResult:
    """四 kind 统一分派，返回契约 {status, output, error, durationMs}。"""
    started = now_ms()
    try:
        if step.kind == "tool":
            output = await self._executors.tool.run(step.ref, args)        # registry.get(ref).run(**args)
        elif step.kind == "script":
            output = await self._executors.script.run(step.ref, args)      # ref ∈ python|shell
        elif step.kind == "agent":
            output = await self._executors.agent.run(step.ref, args)       # YAML agent
        elif step.kind == "llm":
            output = await self._executors.llm.run(step.ref, args)         # ref 固定 "chat"；provider/model 取自全局配置
        else:
            raise ValueError(f"unknown step.kind: {step.kind!r}")
        return StepResult(status="ok",  output=output, error=None,
                          started_at_ms=started, finished_at_ms=now_ms(),
                          duration_ms=now_ms() - started)
    except Exception as e:
        return StepResult(status="error", output=None, error=repr(e),
                          started_at_ms=started, finished_at_ms=now_ms(),
                          duration_ms=now_ms() - started)
```

**四种 executor 关键点**（`secbot/workflow/executors/*.py`）：

| Executor | 调用点 | 注意事项 |
|----------|--------|---------|
| `tool.py`   | `secbot/agent/tools/registry.py::get_tool(ref).run(**args)` | 执行前用工具 `inputSchema` 校验 args；不在 LLM 上下文中，仅程序化调用 |
| `script.py` | 将 `{code, timeoutMs, env, stdin}` 包装为 `shell` 工具调用：`python -c CODE` / `bash -c CODE` | stdin 可从 `${steps.<id>.result.*}` 模板注入；stdout 优先按 JSON 解析，解析失败保留原文本；超时即 `workflow.executor.script_timeout` |
| `agent.py`  | `secbot/agents/registry.py::get_agent(ref).run(args)` | 子智能体内部自带 LLM + tool 调用，executor 仅透传与计时 |
| `llm.py`    | `secbot/providers/factory.py::create_default().chat(messages, temperature=, max_tokens=)` | `messages = [system, user]` 由 args.systemPrompt / args.userPrompt 组装；`responseFormat="json"` 时传 `response_format={"type":"json_object"}`；**不接受 step.ref 作为 provider 切换**——始终使用全局 LLM 配置；失败映射到 `workflow.executor.llm_failed` |

> `_exec_with_retry` 包装 `_exec_step`：根据 `step.on_error` + `step.retry` 决定是否重试。所有 kind 重试退避策略一致（指数退避：250ms × 2^n，上限 8s）。

**并发**：
- 同一个 workflow 同时只允许一个 run；重复触发返回 `409 workflow.run.in_progress`
- 全局用 `asyncio.Lock` 字典按 `wf.id` 做串行

### 2.3 表达式与模板插值（`expr.py`）

- **插值**：正则 `\$\{([a-zA-Z_][\w.]*)\}`，递归处理 dict/list/str
- **求值**：禁止通过 `eval()`；采用 **`asteval.Interpreter(usersyms=ctx, readonly_symbols=True)`**，或自写 `ast` 节点白名单（`BinOp/BoolOp/Compare/Name/Attribute/Subscript/Constant/UnaryOp`）
- **禁止**：`Call`（不允许调用函数）、`Lambda`、`Import`、`__*__` 属性访问

### 2.4 持久化（`store.py`）

- 两个文件：`workflows.json`（全量对象，原子写） + `runs.jsonl`（只追加）
- 并发：`filelock.FileLock` + `_atomic_write`（temp file + `os.replace` + `os.fsync`）—— **完全复用 `secbot/cron/service.py::_atomic_write`**，建议把它提升到 `secbot/utils/atomic.py`
- `runs.jsonl` 定期截断：保留最近 7 天 / 最多 1000 条

---

## 3. 前端关键流程

### 3.1 路由接入（`App.tsx`）

```tsx
<Route path="/workflows" element={<WorkflowListPage />} />
<Route path="/workflows/:id" element={<WorkflowDetailPage />} />
```

Navbar（`components/Navbar.tsx`）追加条目：

```tsx
{ key: "workflows", path: "/workflows", icon: "workflow", label: t("nav.workflows") }
```

Feature flag：顶层读取 `import.meta.env.VITE_WORKFLOW_BUILDER`，默认 `"true"`，`"false"` 时菜单项和路由一起隐藏。

### 3.2 详情页 4 Tab 结构

| Tab | 组件 | 说明 |
|-----|------|------|
| 基本信息 | 内联表单 | 名称 / 描述 / tags；`InputsEditor` 编辑工作流级入参 |
| 步骤 | `StepEditor` | 线性列表 + HTML5 拖拽；右侧参数面板按 `step.kind` 动态渲染 4 种子表单（见下） |
| 调度 | `ScheduleTab` | 三种 cron kind 的表单 + 下次运行时间预览（前端 `cron-parser` 同源库，或服务端返回） |
| 运行记录 | `RunHistoryTab` | 每行一条 run；展开显示各 step 的 duration / status / output json |

**`StepEditor` 按 kind 分发**（对齐 `api-spec.md §1.3`）：

| step.kind | 左侧色条 | 右侧子表单 | 数据源 |
|-----------|---------|------------|-------|
| `tool`   | 蓝 (`bg-primary`)                    | `ToolArgsForm` —— 根据选定工具的 `inputSchema` 驱动；`ref=upload` 渲染为文件/文本上传区（用户粘贴文本或拖拽文件，结果 base64/路径写入 `step.args.payload`） | `GET /_tools` |
| `script` | 紫 (`bg-[hsl(var(--purple))]`)       | `ScriptArgsForm` —— Monaco 写 `code` + `timeoutMs` + `stdin` 模板插值辅助 | 前端硬编码 `ref ∈ python\|shell` |
| `agent`  | 靛 (`bg-indigo-500` 或 theme indigo) | `AgentArgsForm` —— 由智能体 `inputSchema` 驱动 | `GET /_agents` |
| `llm`    | 粉 (`bg-pink-500` 或 theme pink)     | `LlmArgsForm` —— `systemPrompt` / `userPrompt` / `temperature` / `maxTokens` / `responseFormat`（**无 provider/model 选择**） | 无数据源端点（`ref` 固定为 `chat`，由全局 LLM 配置决定 provider/model） |
| 条件分支 | 橙 (`bg-[hsl(var(--warning))]`)       | `ConditionField` —— 受限表达式输入框 + 变量可用范围提示 | 前端自用 |

⚠ **Gotcha：Tab / View 切换必须用 Tailwind 的 `hidden` 类，不要自定义 `[data-tab] { display:none }`**。原因：`hidden` 是 `display:none !important;`，优先级高于同单元上的 `grid`/`space-y-*` 等 Tailwind 布局类；自定义 `display:none` 与 `grid` 同优先级，会被布局类覆盖导致旧 Tab 内容残留（原型页 `prototype.html` 曾踩过这个坑）。标准写法：

```tsx
<div data-tab="steps" className={cn("grid lg:grid-cols-[1fr_380px] gap-6", tab !== "steps" && "hidden")}>...</div>
```

**InputsEditor 契约**：字段名 / 类型 / `required` 全部由用户自定义，UI **不得预设**任何固定名称（如 `target_ip`）。示例文案可提示多个场景配方（内网扫描 / 邮箱巡检 / 全网扫描），但创建者可任意增删。

### 3.3 客户端（`workflow-client.ts`）

```ts
export class WorkflowClient {
  constructor(private http: HttpClient, private ws: SecbotClient) {}
  list(params?) { return this.http.get<WorkflowListResp>("/api/workflows", params); }
  get(id) { return this.http.get(`/api/workflows/${id}`); }
  create(body) { return this.http.post("/api/workflows", body); }
  update(id, body) { return this.http.put(`/api/workflows/${id}`, body); }
  run(id, inputs) { return this.http.post(`/api/workflows/${id}/run`, { inputs }); }
  schedule(id, body) { return this.http.post(`/api/workflows/${id}/schedule`, body); }
  onRunEvent(cb) { return this.ws.subscribe(["workflow.run.*", "workflow.step.*"], cb); }
}
```

### 3.4 视觉基线（务必一致）

| 元素 | 规范 |
|------|------|
| Navbar | `sticky top-0 h-16 backdrop-blur-xl border-b` |
| 页面容器 | `max-w-[1600px] px-6 py-6 space-y-6` |
| 卡片 | `gradient-card rounded-2xl border border-[hsl(var(--border))] p-5` |
| 主按钮 | `gradient-primary hover-lift shadow-md` |
| 运行状态徽章 | `rounded-full border bg-*/10 px-2.5 py-0.5 text-xs`，颜色按 severity：成功绿、运行蓝（`animate-pulse`）、失败红 |
| Step 卡左侧色条 | `border-l-4`：tool=蓝 / script=紫 / agent=靛 / llm=粉 / 条件分支=橙 |
| 入场动效 | `animate-fade-in-up` |

---

## 4. 本地开发

```bash
# 后端
uv run pytest tests/workflow -q
uv run ruff check secbot/workflow

# 前端
cd webui
npm run dev                       # Vite 开发服务 (localhost:5173)
npm run lint && npm run typecheck && npm run build
npm run test -- workflow          # Vitest

# 一键打通
bash entrypoint.sh                # 启动完整 secbot + webui 预览
```

测试数据：`tests/workflow/fixtures/*.json` 准备 2 条 workflow + 1 条 run 样本。

---

## 5. 提交顺序建议（与 prd.md 的 3 个 PR 对齐）

| PR | 变更 | 关键测试 |
|----|------|---------|
| PR1 | 后端 `workflow/*` + `api/server.py` + `secbot.py::_on_cron_job` 分派 | CRUD / 表达式 / retry / cron 集成 |
| PR2 | 前端路由 + 列表页 + 详情页 4 Tab 骨架 + CRUD | 编辑器状态机 / 表单校验 |
| PR3 | ScheduleTab + RunHistoryTab + 条件分支 UI | E2E：新建 → 调度 → 触发 → 运行记录 |

每个 PR 自带单测 + 文档增量更新。完工后走 `trellis-check` 再 `trellis-finish-work`。

---

## 6. 风险 & 备忘

| 风险 | 缓解 |
|------|------|
| condition 表达式注入 | `asteval` 或自写 ast 白名单，**严禁 `eval`** |
| runs.jsonl 无限膨胀 | 启动时按日期清理，运行时仅追加 |
| cron + workflow 双写竞争 | 对 `scheduleRef` 做幂等：workflow CRUD 内部串行修改 cron |
| 工具/智能体被删导致 step 悬空 | runner 启动前校验 `ref` 是否在 registry 中；不存在则 step 标记 `error` 并按 `on_error` 处理 |
| 前端步骤编辑大对象 re-render | `useMemo` 缓存；步骤列表按 id 走 `React.memo` |
| Tab 切换残留旧内容 | 一律用 Tailwind `hidden` 类控制显隐，不写自定义 `display:none`（避免被 `grid` 覆盖）；参见 §3.2 Gotcha |
| InputsEditor 模版变硬编码 | UI 不存在内置字段；名称 / 类型 / required 均由用户输入，提示文案只能用举例口吻 | 
| `kind=llm` step 成本失控 | `LlmArgsForm` 必填 `maxTokens`（默认 800）；后端添 `llm.dry_run=true` 模式只打 token 估算不真调 provider；由于 provider/model 来自全局配置，成本上限也可在全局配置侧再兜一道 |
| `kind=script` 任意代码执行 | 复用 `shell` 工具的白名单与超时；独立容器化沙箱 Out of Scope（PRD 已标禁）；PR1 强制 `timeoutMs ∈ [100, 60000]` |
| `kind=agent` / `kind=llm` 双层 LLM 调用 | WS 事件里 `workflow.step.progress` 为子智能体/LLM 暴露子进度；前端在 Step 卡增补一行 `animate-pulse` 状态行 |
| 国际化漏翻 | `i18next` key 前缀统一 `workflow.*`，CI 加 key 缺失检查 |

---

## 7. 对外文档（非本文档）

用户使用说明（`docs/workflow.md`）在 PR3 合入前补齐；本开发指南只面向贡献者。
