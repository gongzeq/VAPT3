# 注册 vuln-detec 可执行技能

## Goal

将当前仅作为占位符的 `vuln-detec-manual` 技能改造为真正可执行的漏洞探测技能，使其能够：
- 接收从 `port_scan`、`crawl_web` 等上游阶段发现的 Web 服务列表
- 对每个服务自动执行 `vuln_detec.md` 中定义的 8 种手动探测测试
- 返回结构化的 findings（含 confidence 评级）
- 在全部探测完成后，将发现的漏洞以 `cmdb_writes` 形式写入 CMDB

## What I already know

- 当前 `vuln-detec-manual` 是占位 skill（[handler.py](file:///Users/shan/Downloads/nanobot/secbot/skills/vuln-detec-manual/handler.py) 只返回 guidance message）
- `vuln_detec` agent（[vuln_detec.yaml](file:///Users/shan/Downloads/nanobot/secbot/agents/vuln_detec.yaml)）当前引用 `vuln-detec-manual` skill，且 `allow_exec: true`
- `vuln_detec.md` prompt 中描述了 8 种手工测试（baseline、特殊字符、XSS 反射、SQL 错误、时间盲注、数字运算、模板注入、命令注入）
- 技能发现机制：`scan_skills()` 扫描 `secbot/skills/` 下每个包含 `SKILL.md` + `handler.py` 的子目录
- `cmdb_writes` 支持三张表：`assets`、`services`、`vulnerabilities`
- `SkillResult` 结构：`summary`、`raw_log_path`、`findings`、`cmdb_writes`

## Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Scope | **替换 `vuln-detec-manual`**（保持 skill 名不变，agent yaml 无需改动） |
| 2 | 触发 vuln_scan / 黑板 | **Skill 只返回 findings + cmdb_writes**，agent 根据结果决定后续行为（已有 prompt 指导） |
| 3 | 输入格式 | **混合模式** — `targets` 数组，每个元素含 `url`/`method`/`params`/`headers`/`cookies` |
| 4 | HTTP 客户端 | **httpx**（项目已有依赖 `httpx>=0.28.0`） |
| 5 | 并发策略 | **串行** — URL 之间串行，每个 URL 的 8 种测试串行（时间盲注需要精确基准） |

## Requirements

- [ ] 重写 `vuln-detec-manual/handler.py`：对传入的每个 target 执行 8 种探测测试
- [ ] 更新 `input.schema.json`：`targets` 数组 + 可选全局 `headers`/`cookies`/`timeout_sec`
- [ ] 更新 `output.schema.json`：返回 `findings` 数组（test_name/result/confidence/evidence/payload）
- [ ] 8 种测试：BASELINE、特殊字符、XSS 反射、SQL 错误、时间盲注、数字运算、模板注入、命令注入
- [ ] 将 `confidence: high` 的 findings 转换为 `cmdb_writes`（`vulnerabilities` 表）
- [ ] 更新 `SKILL.md`：描述实际功能，移除 placeholder 说明
- [ ] 单元测试覆盖核心探测逻辑（至少 3 种测试 + cmdb_writes 生成）

## Acceptance Criteria

- [ ] Skill 可以独立运行，接收 URL 列表并返回结构化的 findings
- [ ] 发现 high-confidence 漏洞时返回 `cmdb_writes`（vulnerabilities 表）
- [ ] 所有 8 种测试都能正确执行并返回结果
- [ ] 单元测试覆盖核心探测逻辑

## Definition of Done

- 测试通过
- Lint / typecheck 通过
- SKILL.md 和 schema 文档更新

## Out of Scope

- 修改 vuln_detec agent 的 prompt 或 yaml（除非 skill 接口变更需要同步更新）
- 实现 agent 级别的 vuln_scan 调用和黑板写入逻辑（这是 agent/orchestrator 的职责）
- 图形化报告生成

## Technical Notes

- `vuln_detec.md` 中 8 种测试的详细流程见 agent prompts
- 参考 `nuclei-template-scan` 的 `cmdb_writes` 生成方式
- 参考 `httpx-probe` 的 HTTP 请求实现方式
- 时间盲注测试需要精确计时，避免并发干扰
