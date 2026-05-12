# brainstorm: security tools as first-class tools

## Goal

把全部安全工具（nmap / fscan / hydra / httpx / nuclei / ffuf / sqlmap）从"由 LLM 用 `exec` 拼 shell 命令"升级为"LLM 直接调用的一等 tool"。每个 tool 通过 Skill 实现（参数校验 + sandbox + 解析）。先内置 MVP 若干 skill，后续开放前端自定义 skill 的能力。

## What I already know

- 当前 `exec` 工具通过 `bash -l -c` 执行 LLM 生成的 shell 命令，导致 `#` 被当注释，且 LLM 需要自己拼参数，不安全也不稳定
- `secbot/skills/` 下已存在：`nmap-host-discovery`、`nmap-port-scan`、`fscan-asset-discovery`、`fscan-port-scan`、`fscan-vuln-scan`、`nuclei-template-scan`、`report-*`
- `_shared/sandbox.py` 的 `BINARY_WHITELIST` 已包含 `nmap/fscan/nuclei/hydra/masscan/weasyprint/python3/git`
- `secbot/agent/tools/` 体系支持注册 Tool 子类到 ToolRegistry，`to_schema()` 暴露给 LLM
- Skill 当前只通过 `build_skills_summary()` 文本化注入 system prompt，**未作为 tool 暴露**
- 已有 YAML 专家智能体（asset_discovery/port_scan/vuln_scan/weak_password/report）——其 `scoped_skills` 可直接复用为"该 agent 能看到的 tool 白名单"

## Assumptions (temporary)

- 安全工具增量（httpx / ffuf / sqlmap）只需扩展 `BINARY_WHITELIST` + 新增 skill 即可
- "Skill-as-Tool" 不替换现有 Tool 体系，而是新增一个 `SkillTool` 适配器把 skill 动态挂到 ToolRegistry
- 前端自定义 skill 是二期能力，本期保证后端接口/数据模型支持即可

## Open Questions

- _(all resolved — see Decision Log)_

## Decision Log

- **D1 Skill 粒度：按场景细粒度** — 一个 binary 可对应多个 skill，每个 skill 有明确目的（如 `nmap-host-discovery` / `nmap-port-scan` 分开）。
  - Pros：tool schema 简单、LLM 选错概率低、前端自定义以 skill 为独立单位

- **D2 MVP skill 清单：标准版13 skill**
  - 保留（6）：`nmap-host-discovery` / `nmap-port-scan` / `fscan-asset-discovery` / `fscan-port-scan` / `fscan-vuln-scan` / `nuclei-template-scan`
  - 新增（7）：`nmap-service-fingerprint` / `hydra-bruteforce` / `httpx-probe` / `ffuf-dir-fuzz` / `ffuf-vhost-fuzz` / `sqlmap-detect` / `sqlmap-dump`
  - BINARY_WHITELIST 新增：`httpx` / `ffuf` / `sqlmap`

- **D3 高风险 gate：按 metadata.risk 声明**
  - `SkillMetadata` 新增字段 `risk: Literal["low","medium","critical"]`
  - `risk=critical` 时 SkillTool 自动调 `ctx.confirm` 强制确认
  - MVP 分级：`sqlmap-dump` / `hydra-bruteforce` = critical；`sqlmap-detect` / `ffuf-*` / `nuclei-template-scan` = medium；其余 low

- **D4 exec 工具：MVP 默认关闭**
  - 保留 `ExecTool` 代码和测试，但把 `ExecToolConfig.enable` 默认值改为 `False`
  - LLM 不再看到 exec，所有 shell 需求必须通过 skill
  - 进阶用户仍可显式开启（未来可能移除，但本期不动）

## Requirements (evolving)

- 7 个内置安全工具作为 LLM 一等 tool：nmap / fscan / hydra / httpx / nuclei / ffuf / sqlmap（每个主 binary 按场景拆成若干 skill，合计13 skill）
- 所有工具调用统一走 Skill → sandbox（禁止再通过 `exec` 调这些 binary；MVP 默认 exec 关闭）
- 新增 `httpx` / `ffuf` / `sqlmap` 到 `BINARY_WHITELIST`
- 新增 `SkillTool` 适配器：把一个 skill 自动包成 `Tool`，tool 名 = skill 名，`to_schema()` 来自 skill 的 input schema
- `SkillMetadata` 新增 `risk: Literal["low","medium","critical"]`，critical 强制 `ctx.confirm`
- `AgentLoop._register_default_tools` 和 `SubagentManager._run_subagent` 均通过 `SkillsLoader` 反向查找并批量注册 SkillTool
- 专家子智能体裁剪：`SubagentManager._run_subagent(spec)` 只注册 `spec.scoped_skills` 对应的 SkillTool
- `SpawnTool` 新增 `agent: str` 参数，命中 AgentRegistry 后加载对应 spec
- Orchestrator（主 loop）system_prompt 头部注入 `render_orchestrator_prompt(registry)`，让 LLM 看到可选专家列表
- `report-*` skill 也随路注册为 tool（统一优化，不额外耗时）
- **智能体健康状态与离线标记**：启动时校验每个专家 agent 的 `scoped_skills` 所需 binary，若全部缺失 → 标为 `offline`；`spawn(agent="<offline>")` 返回明确错误；前端在 agent 列表/选择器中显示"不在线"

## Acceptance Criteria

- [ ] LLM 无法看到 `exec` 工具（默认配置下）
- [ ] 13 个 skill 全部以 tool 形式在 `AgentLoop.tools.to_schema()` 中出现，每个有标准 JSON Schema
- [ ] `sqlmap-dump` 或 `hydra-bruteforce` 在 CLI/WebUI 调用时触发 `ctx.confirm` 确认框（非交互模式自动拒绝）
- [ ] `spawn(agent="port_scan", task="...")` 启动的子 loop，ToolRegistry 只包含 `port_scan.yaml` 的 3 个 scoped skill（或现存子集）+ blackboard_read/write
- [ ] 端到端：对 `http://111.228.2.47:8080/` 发起扫描，前端同时出现思维链卡 + 子智能体卡 + blackboard 卡 + 具体 skill tool_call 卡（如 nmap-port-scan）
- [ ] `BinaryNotAllowed` / `SkillBinaryMissing` / `InvalidArgvCharacter` 三种异常都被 SkillTool catch 并转为 LLM 可读的 tool error 文本
- [ ] 单测：`SkillTool` 注册/调用/错路各一份；risk gate 交互/非交互两种模式；子 loop scoped 注册
- [ ] 健康检查：人为移除 `nmap` binary 后，`asset_discovery` / `port_scan` 在 `/api/agents` 返回 `status=offline`；前端 agent 选择器显示灰色"不在线"；`spawn(agent="port_scan")` 直接返回 tool error 而不启动子 loop

## Definition of Done

- 测试：上述单测全部绿；tests/agent 和 tests/skills 的回归全部通过
- Lint（ruff）/ typecheck（mypy）绿
- `docs/my-tool.md` 增补 "Skill-as-Tool" 节（如何写一个 skill / 如何设置 risk）
- `.trellis/spec/backend/tool-invocation-safety.md` 同步：标明 "LLM 不再直调安全 binary"

## Technical Approach

```
AgentLoop (orchestrator)
│  system_prompt ← render_orchestrator_prompt(registry)
│  tools ← [SpawnTool(agent=...), BlackboardWrite, BlackboardRead, … 无 exec]
│
├─ LLM 调 spawn(agent="port_scan", task="测试 111.228.2.47")
│     └─ SubagentManager 查 AgentRegistry 拿到 spec
│          └─ 新 child AgentLoop
│                system_prompt ← spec.system_prompt + skills_addendum(spec.scoped_skills)
│                tools ← [SkillTool(nmap-port-scan), SkillTool(fscan-port-scan), …, BlackboardRead/Write]
│                └─ LLM 调 nmap_port_scan({targets:[...], ports:"1-1024"})
│                     └─ SkillTool → runner.execute() → sandbox.run_command(binary="nmap", args=...)
```

### 核心组件
1. `secbot/agent/tools/skill_tool.py` 新建
   - `class SkillTool(Tool)`：构造传入 `SkillMetadata`，`execute()` 走 `SkillsLoader.run(skill_name, args, ctx)`
   - `to_schema()` 直接放出 skill input schema
   - 若 `metadata.risk == "critical"`：`execute()` 先调 `ctx.confirm(title, detail)`，拒绝则返回 tool error

2. `secbot/skills/metadata.py` 扩展
   - `SkillMetadata` 新增 `risk: Risk = Risk.LOW`
   - 每个新 skill 的 `SKILL.md` front-matter 体现该字段

3. `secbot/skills/_shared/sandbox.py`
   - `BINARY_WHITELIST` 增加 `httpx, ffuf, sqlmap`

4. 新增 7 个 skill 目录（每个含 `SKILL.md` + `handler.py` + `schema.json`）：
   - `nmap-service-fingerprint` (`-sV`)
   - `hydra-bruteforce` (`-L/-l` + `-P/-p` + 协议)
   - `httpx-probe`（注意：PATH 中需 `httpx` 指 projectdiscovery/httpx 而非 Python 库）
   - `ffuf-dir-fuzz` / `ffuf-vhost-fuzz`
   - `sqlmap-detect`（`--batch --level=1 --risk=1`）
   - `sqlmap-dump`（`--dump` + `--batch`，risk=critical）

5. `AgentLoop._register_default_tools` / `SubagentManager._run_subagent`
   - 移除 `exec_config.enable` 默认 True；新默认 False
   - 新增 `_register_skill_tools(tools, skills, scoped: set[str] | None)` 工具方法

6. `secbot/agent/tools/spawn.py`
   - input_schema 新增 `agent: string` （可选）
   - `execute()` 按 agent 名查 registry，拿到 spec 后传给 `SubagentManager.spawn(spec=...)`

7. `SubagentManager._run_subagent(spec: ExpertAgentSpec | None)`
   - 若有 spec：system_prompt 拼接：`spec.system_prompt + "\n\n" + skills_addendum(spec.scoped_skills)`
   - ToolRegistry：按 `spec.scoped_skills` 筛选注册
   - 缺失 skill 记 warning 不阻塞

8. `secbot/config/schema.py::ExecToolConfig`
   - `enable` default 从 `True` 改为 `False`

9. **智能体健康检查**（新增）
   - `AgentRegistry.load()` 完成后走一轮 `check_availability()`：
     - 收集 `spec.scoped_skills` 对应的 binary 集合（空集视为 `online`）
     - `all(shutil.which(b) is None for b in binaries)` → `status=offline`
     - `any(... is None)` 但非全部 → `status=online`（MVP 不引入 degraded 等级）
     - 结果写入 `ExpertAgentSpec.availability: Literal["online","offline"]`（运行时字段）+ `missing_binaries: tuple[str, ...]`
   - `SpawnTool.execute(agent=X)` 先检查 `spec.availability`；`offline` 直接返回 tool error 文本：
     `"Agent '{name}' is offline: missing binaries {missing}. Install them and retry."`
   - 新增 `GET /api/agents` 返回数组：`[{name, display_name, description, status, missing_binaries}]`
   - agent_event 协议预留：可选新增 `agent_offline` 事件（仅在 LLM 尝试 spawn 离线 agent 时发送）——MVP 默认不开启
   - 前端（Agents 页面 / 任务发起器的 agent 选择器）：读 `status=offline` 显示灰色徽章 + tooltip 列出 `missing_binaries`

## Implementation Plan (small PRs)

- **PR1：SkillTool 骨架**
  - 新建 `skill_tool.py`；SkillMetadata.risk 字段；HighRisk confirm 架构接入
  - 单测：注册 / 调用 / critical confirm / error 映射
- **PR2：BINARY + 7 个新 skill**
  - 扩 `BINARY_WHITELIST`；新建 7 个 skill 目录 + handler + schema + 解析器
  - 每个 skill 有至少 1 个 smoke 单测（mock sandbox 返回）
- **PR3：专家 agent 裁剪 + spawn 扩展 + 健康检查**
  - SubagentManager 接 spec；SpawnTool 新增 agent 参数
  - AgentRegistry.check_availability + `/api/agents` 端点 + 前端"不在线"徽章
  - orchestrator prompt 注入（离线 agent 不列入可选列表）；output 验证端到端
- **PR4：exec 默认关 + report-* 注册 + 文档**
  - `ExecToolConfig.enable=False`；report-* 一同注册；doc + spec 更新
  - 手动验证：扫描 `http://111.228.2.47:8080/` 观察四种卡片

## Out of Scope (explicit)

- 前端"自定义 skill"UI（本期只做后端/schema 支撑，UI 下一期）
- 现有 `report-*` skill 的改造（它们已经是 skill 形态，本期仅打通 tool 暴露）
- 重写 orchestrator prompt 体系（独立任务）
- 修复 bash `#` 注释问题（迁移到 Skill-as-Tool 后 exec 不再跑安全工具，自然规避）

## Technical Notes

### 相关文件
- [secbot/agent/tools/registry.py](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/registry.py) — ToolRegistry
- [secbot/agent/tools/base.py](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/base.py) — Tool 抽象
- [secbot/agent/tools/shell.py](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/shell.py) — ExecTool（需要加黑名单）
- [secbot/agent/skills.py](file:///Users/shan/Downloads/nanobot/secbot/agent/skills.py) — SkillsLoader
- [secbot/skills/metadata.py](file:///Users/shan/Downloads/nanobot/secbot/skills/metadata.py) — skill 元数据模型
- [secbot/skills/_shared/sandbox.py](file:///Users/shan/Downloads/nanobot/secbot/skills/_shared/sandbox.py) — `BINARY_WHITELIST`
- [secbot/skills/_shared/runner.py](file:///Users/shan/Downloads/nanobot/secbot/skills/_shared/runner.py) — `execute()`
- [secbot/agents/*.yaml](file:///Users/shan/Downloads/nanobot/secbot/agents) — 专家 agent 的 `scoped_skills`

### 关键约束
- Skill 已经规定走 sandbox（安全）；exec 工具是明显的"逃逸口"，必须关闭
- Skill input schema 需要规范化到 JSON Schema，才能作为 Tool.to_schema
- 高风险 skill（sqlmap / hydra / exploit 类）必须经过 HighRiskGate 确认

### 新引入的边界注意事项（来自 diverge sweep）
- `httpx` 在 PATH 中可能指向 Python 的 httpx 库 shim；skill 启动时需验证 `httpx -version` 输出字样包含 "projectdiscovery"，否则报清晰错误
- `critical` skill 在非交互模式（定时、API 调用）：`ctx.confirm` 需返回 `False`，而非挂起等待
- `SkillsLoader` 并发执行同一 skill 多次：sandbox 已支持 per-proc，但需确认 `raw_log_path` 不互覆盖
- `ExecToolConfig.enable` 默认改 False 后：现有依赖 exec 的任何隐式用例（如某些 skill 高级用法、用户文档中的 CLI 小技巧）需在 PR4 中走查
