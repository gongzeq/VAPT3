# brainstorm: subagent prompt minimization & create_agent rename

## Goal

把"子智能体启动协议"从「丰满系统提示 + 黑板注入 + per-agent 工具」收敛到「`create_agent(name, task, target)` 单一入口 + 由主智能体在 `task` 里直接写完整 prompt」，让 orchestrator 拥有更直接的提示词控制权，移除子智能体侧的隐式上下文。

## What I already know

### 当前实现（基线）

- `secbot/agent/subagent.py::_run_subagent`
  - 构建 system prompt = `spec.system_prompt`（专家角色） + `subagent_system.md`（hard rules / 时间 / workspace / skills_summary）
  - 末尾 append 黑板快照（`_format_blackboard_context`，最多 1500 字符）
  - `messages = [{system: system_prompt}, {user: task}]`
- `secbot/agent/tools/spawn.py::SpawnTool` 名为 `delegate_task`，参数 `(task, label, agent)`
- `secbot/agents/registry.py::ExpertAgentSpec.to_tool_surface()` 把每个 yaml 暴露成独立 function
  - 例：`vuln_detec` 有 `input_schema {url, method, params, headers, cookies}`；`asset_discovery` 用 `target`；`vuln_scan` 用 `services` 数组
- 当前 orchestrator 同时拥有 per-agent function + `delegate_task`（双通道）

### 用户要求示例

```json
{
  "function": "create_agent",
  "parameters": {
    "name": "vuln_detec",
    "task": "Test https://example.com/search?q= for SQL injection.\nKnown info: PHP/MySQL stack,\nparameter 'q' reflects input unencoded.",
    "target": "https://example.com"
  }
}
```

## Assumptions (temporary)

- `name` = expert agent registry 名称（保留 `agent_registry` 校验/可用性检查）。
- `task` = orchestrator 已写好的"全量 prompt 文本"（含目标、已知信息、动作指令）。
- `target` = 路由/审计用的目标标识（待确认）。
- 现有 per-agent function tool surface 整体下线，统一为 `create_agent`。
- `delegate_task` 名称不再保留，改为 `create_agent`。

## Decisions

### D1. 消息结构 = A（极简骨架 + task 作 user）

- 子智能体 messages 形态：`[{role: system, content: <hard rules + workspace>}, {role: user, content: task}]`
- **移除**：`spec.system_prompt`（角色描述）、`skills_summary`（技能字典）、黑板快照（`_format_blackboard_context`）
- **保留**：极简 hard rules 骨架（约束"必须用 skill tool 而非伪造 shell"），workspace 路径
- 理由：兼容 OpenAI / MiMo 等 provider 对 user turn 的强依赖；守住 ExecTool 历史红线；orchestrator 通过 `task` 接管角色 prompt。

### D2. `target` 字段 = 纯元数据（**required**）

- 工具 schema：
  ```
  {
    name:           string  (required)  // 必须在 agent_registry 中
    task:           string  (required)  // orchestrator 写好的全量 prompt
    target:         string  (required)  // 路由/审计用，不进 LLM prompt
    endpoint_url:   string  (条件 required, 见 D8)
    endpoint_param: string  (条件 required, 见 D8)
  }
  ```
- `target`、`endpoint_url`、`endpoint_param` **均不进 LLM prompt**，由后端 `SubagentManager.spawn` 作为 metadata 接收
- `target` 用途：scan_id / 黑板 scope / CMDB 资产关联 / 审计日志的路由键
- `task` 文本由 orchestrator 自行书写（含目标 URL、已知信息、动作指令），后端零拼接
- yaml `input_schema` 不下线但**重命名**（见 D7）

### D3. 黑板访问 = 自动注入移除，工具保留

- system prompt 不再 append `_format_blackboard_context`
- `blackboard_read` / `blackboard_write` 工具仍注册到子智能体 ToolRegistry
- 是否读 peer 状态由 orchestrator 在 `task` 中显式指示（保持多智能体协作链路）

### D4. 极简 system prompt = 档位 3

```
You are a subagent. Your final reply will be reported back to the orchestrator.

{{ time_ctx }}

Workspace: {{ workspace }}

Hard rules:
- For external binaries (nmap/fscan/nuclei/sqlmap/...), use the corresponding skill tool. Do NOT invent shell commands.
- If a needed skill is missing, write a [blocker] entry via blackboard_write and return.

{% include 'agent/_snippets/untrusted_content.md' %}

Skills available: see SKILL.md of each skill via read_file (scoped to this agent).
```

- 删除：`spec.system_prompt`、`SkillsLoader.build_skills_summary()` 输出、`_format_blackboard_context`
- 保留：time_ctx、workspace、hard rules（2 条）、untrusted_content 防注入片段、SKILL.md 自查指引一行

### D5. 端点级并发互斥（新增需求）

**约束**：同一 `(url, parameter)` 端点全局至多 1 个 expert agent 在跑；端点不同（url 或 parameter 任一不同）可并发。

- 命中：直接拒绝 spawn，返回 `agent already running on endpoint <fingerprint>`
- 未命中：正常启动，并把端点 fingerprint 加入 in-flight 集合，子智能体结束时移除
- 后端需在 `SubagentManager.spawn` 前置校验
- 关键问题：后端**如何从 `create_agent(name, task, target)` 中提取端点指纹** —— 见下方提问

### D6. 调用参数严格校验（fail-fast，不做缺省兜底）

- **agent name 必须存在**：`name` 不在 `agent_registry` 中 → 直接 raise/工具返回错误，提示 LLM 选择已注册 agent
  - 错误体应附带可用 agent 列表（取自 registry），便于 LLM 自我修正
- **target 必须显式提供**：`target` 缺省 / 空字符串 → 直接 raise/工具返回错误，提示 LLM 必须补充 target
- 错误返回不杀进程、不静默兜底、不引入默认值；orchestrator 收到 tool error message 后自我修正
- 落地点：`SpawnTool.execute`（参数预校验）+ `SubagentManager.spawn`（registry lookup）

### D7. yaml `input_schema` = 不删除，重命名

- 保留 `secbot/agents/*.yaml` 中各 expert 的 `input_schema` 配置块（结构数据保留）
- 重命名为更弱语义的字段（候选：`legacy_input_schema` / `input_schema_doc` / `input_hints`），表明：
  - 不再用于 LLM 工具入参 schema（per-agent function tool 已下线）
  - 仅作文档/审计/未来重启可能性的参考资料
- `ExpertAgentSpec.to_tool_surface()` 整体下线（不再生成 per-agent function）
- 加载侧（`registry.py`）兼容旧字段名一段时间，给出 deprecation warning（避免现网 yaml 立即崩）

### MVP 范围（用户确认 = 做 1+2+4+5；3 不做）

1. **做** task 长度上限（`task` 文本字符数 / token 上限校验，超限报错）
2. **做** yaml `input_schema` 重命名（D7）
3. ~~target 缺省兜底~~ → **替换为 D6 严格校验**
4. **做** 回归测试覆盖（新协议 + ExecTool 红线 + 端点互斥 + 严格校验）
5. **做** orchestrator prompt 与 `diag_subagents.py` 自检脚本同步更新

### D8. 端点指纹来源 = 协议显式新增字段

- `create_agent` schema 新增 `endpoint_url` + `endpoint_param` 两字段（见 D2）
- 端点指纹 = `(endpoint_url, endpoint_param)` 元组（urlparse 标准化后比较，去掉 fragment、规范小写 host、保留 path/query）
- **条件 required**：是否必填取决于 expert agent 是否"端点级"
  - registry 给每个 ExpertAgentSpec 加 `endpoint_bound: bool`（默认 false）
  - 当前已知 `endpoint_bound=true` 的 expert：`vuln_detec`、`weak_password`
  - `endpoint_bound=true` 时缺省 endpoint_url / endpoint_param → 走 D6 严格校验，报错让 LLM 补充
  - `endpoint_bound=false`（如 asset_discovery / port_scan / vuln_scan / crawl_web / report）→ 不要求这两个字段，也不参与互斥集合
- 互斥集合维护：
  - in-flight set: `Set[(name, normalized_url, param)]`（仅 endpoint_bound=true 入集）
  - spawn 前 check，命中拒绝；子智能体 `_run_subagent` finally 块 remove
- 字段不进 LLM prompt（与 target 同性质，仅作 metadata + 互斥键）

## Open Questions (Blocking)

- 无（全部 blocker 已收敛）

## Open Questions (Preference)

- ~~`endpoint_bound` 配置载体~~ → **已决定：yaml 字段**（默认 false，逐 expert 在 yaml 中显式声明，便于后续无代码扩展）

## Status

- Brainstorm: ✅ 完成（D1–D8 全部收敛）
- Next: Phase 2 Prepare for Implementation（trellis-before-dev → 任务拆解）

## Requirements (final)

- [ ] `delegate_task` → 重命名为 `create_agent`（schema 见 D2）
- [ ] `SpawnTool.execute` 前置参数校验：name 在 registry / target 非空 / endpoint_bound=true 时端点字段非空 / task 长度上限
- [ ] `_run_subagent` 使用主智能体提供的 `task` 作为唯一指令源（不再叠加 spec.system_prompt + 旧 subagent_system.md 全量）
- [ ] `subagent_system.md` 模板瘦身到 D4 档位 3
- [ ] `_format_blackboard_context` 注入路径移除（`blackboard_read/write` 工具仍保留）
- [ ] `SubagentManager` 维护 endpoint in-flight set，spawn 前 check + finally remove
- [ ] `ExpertAgentSpec` 新增 `endpoint_bound: bool` 字段（yaml 配置，默认 false）
- [ ] yaml `input_schema` → 重命名为 `legacy_input_schema`，loader 兼容旧名 + warning
- [ ] `ExpertAgentSpec.to_tool_surface()` 下线（不再生成 per-agent function tool）
- [ ] orchestrator system prompt + render 同步更新（仅暴露 `create_agent`）
- [ ] `scripts/diag_subagents.py` 自检脚本与新协议对齐
- [ ] 回归测试：新协议 / 端点互斥 / 严格校验 / ExecTool 红线 / task 长度上限

## Acceptance Criteria (final)

- [ ] orchestrator tool surface 仅有一个 `create_agent`，无 per-agent function
- [ ] 子智能体 LLM 收到的 messages = `[{system: D4 档位 3 渲染结果}, {user: task}]`，**不**包含 spec.system_prompt / skills_summary / 黑板快照
- [ ] `tests/agent/tools/test_subagent_tools.py::test_subagent_never_registers_exec_tool` 仍通过
- [ ] 同 `(endpoint_url, endpoint_param)` 第二次 spawn 立刻返回 `agent already running on endpoint <fp>`
- [ ] 缺 target / 未知 name / endpoint_bound 必填字段缺省 → 工具返回结构化 error，进程不崩
- [ ] 至少一条用例验证「task 文本逐字进入 user message，未被框架包裹」

## Definition of Done

- 单元 + 集成测试覆盖新协议
- mypy / ruff / pytest 全绿
- 更新 `.trellis/spec/backend/agent-registry-contract.md`
- 更新 orchestrator system prompt 模板
- `scripts/diag_subagents.py` 自检脚本与新协议一致

## Out of Scope (explicit)

- 黑板写入语义改造（仅讨论"读"路径）
- 高危执行（exec）能力变更
- 前端展示层改造（除非 tool name 暴露到 UI）
- 端点指纹做"主机+端口"级（本期只做 url+param 级）

## Technical Notes

- 主智能体侧：`secbot/agents/orchestrator.py` + `render_orchestrator_prompt`
- 子智能体侧：`secbot/agent/subagent.py` + `secbot/templates/agent/subagent_system.md`
- 注册侧：`secbot/agents/registry.py`（per-agent input_schema → legacy_input_schema + endpoint_bound）
- 工具入口：`secbot/agent/tools/spawn.py`
- 关键约束（不可破坏）：ExecTool 在 subagent 中绝对不注册（见 expert_experience: "secbot ExecTool 绝对禁止注册"）
