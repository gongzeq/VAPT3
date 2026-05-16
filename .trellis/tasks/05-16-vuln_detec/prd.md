# brainstorm: 注册 vuln_detec 漏洞检测智能体

## Goal

注册一个 `vuln_detec` 智能体，接收 URL 和参数，对 Web 端点进行快速手工漏洞验证测试。覆盖反射型 XSS、SQL 注入、模板注入、命令注入等常见漏洞类型的初步检测。

## What I already know

* 现有 agent 注册方式：`secbot/agents/*.yaml` + `prompts/*.md`，由 `registry.py` 加载验证
* 现有 skill 注册方式：`secbot/skills/<name>/SKILL.md` + `handler.py` + `input/output.schema.json`
* 现有 `vuln_scan` agent 使用 `nuclei-template-scan`, `fscan-vuln-scan`, `sqlmap-detect` 等 skill 进行漏洞扫描
* **ExecTool 在 subagent 中已被硬编码禁用** (`subagent.py:447-453`)，所有 shell 访问必须通过 SkillTool 路径
* `ExecToolConfig.enable` 默认 `False`，且即使设为 `True`，subagent 也不会获得 exec 工具
* 当前安全策略（PRD 05-11-security-tools-as-tools §D4）：LLM 不再直调 shell，所有安全 binary 通过 SkillTool / sandbox 路径

## Assumptions (temporary)

* `vuln_detec` 应该作为 `vuln_scan` 的补充，专注于快速手工验证而非全面扫描
* 测试命令以 `curl` 为主，属于只读网络请求，风险可控

## Open Questions

* **关键设计决策**：ExecTool 被硬禁用，如何满足执行 curl 命令的需求？
* 输入参数格式：单个 URL 还是批量 URL？参数如何传递（query string / POST body / cookies）？
* 输出格式：结构化 findings 还是文本报告？

## Requirements (evolving)

* 注册 `vuln_detec` agent YAML
* 支持以下手工测试步骤：
  1. BASELINE 请求建立基准
  2. 特殊字符处理测试
  3. 输入反射检测（XSS 初筛）
  4. SQL 错误信息测试
  5. 时间延迟测试（SQLi 确认）
  6. 数值参数算术测试
  7. 模板注入测试
  8. 命令注入测试

## Acceptance Criteria (evolving)

* [ ] `vuln_detec` agent 可以被 orchestrator 正确识别和调度
* [ ] agent 可用性不受缺失 binary 影响（curl 为系统标准工具）
* [ ] 输入/输出 schema 通过 registry 验证

## Definition of Done

* agent YAML + prompt + skill 文件完整
* Registry 加载无错误
* 测试通过

## Out of Scope (explicit)

* 不替代现有 `vuln_scan` 的全面扫描能力
* 不执行破坏性操作（不修改目标数据）

## Technical Notes

* Agent 注册路径：`secbot/agents/vuln_detec.yaml`
* Prompt 路径：`secbot/agents/prompts/vuln_detec.md`
* Skill 注册路径：`secbot/skills/vuln-detec-manual/` (或其他名称)
* 关键约束：`subagent.py` 中 ExecTool 被硬禁用，无法通过配置开启

## Research References

* `secbot/agents/vuln_scan.yaml` — 现有漏洞扫描 agent 结构参考
* `secbot/skills/httpx-probe/` — 只读网络探测 skill 结构参考
* `secbot/skills/sqlmap-detect/` — 漏洞检测 skill 结构参考
* `secbot/agent/subagent.py:447-453` — ExecTool 禁用策略
* `.trellis/tasks/archive/2026-05/05-11-security-tools-as-tools/prd.md` — 安全工具策略 PRD
