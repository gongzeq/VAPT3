# 将 nanobot 改造为 secbot —— 网络安全多智能体平台

> **🔄 Naming Update (2026-05-07):** Rename target changed from `secbot` to **VAPT3** (package: `vapt3`, CLI: `vapt3`, branding: VAPT3). Treat any subsequent `secbot` reference in this PRD as a stale artifact for the same slot now filled by `vapt3`. Source-of-truth naming reference: `.claude/projects/.../memory/project_vapt3_rename.md`.

> 全仓重命名：`nanobot` → `secbot`（PyPI: `secbot-ai`，CLI: `secbot agent`）

## Goal

把现有 nanobot（轻量级 LLM agent runtime）改造成一个对话式的"网络安全智能体平台"，命名 **secbot**：
一个主调度智能体（Orchestrator）解析用户意图，动态路由到一组解耦的专家智能体（资产探测 / 端口扫描 / 漏洞扫描 / 弱口令 / 渗透 / 报告生成），由专家智能体调用功能粒度的 skill（如 `fscan-asset-discovery` / `nmap-port-scan`）执行底层安全工具。

**为什么**：复用 nanobot 已经打磨好的 `agent loop / sub-agent / tool calling / skills` 三件套与 `webui` 主框架，避免从 0 写编排框架与对话前端；同时根据上层 PRD 砍掉所有 IM 通道、保留 4 个对话入口（WebUI / CLI / OpenAI API / Python SDK），刷新 UI 与品牌为安全平台。

---

## ✅ Locked Decisions

| # | 维度 | 决策 |
|---|------|------|
| 1 | **主调度架构** | OpenClaw 风格 tool-calling 循环，复用 nanobot subagent + tool registry |
| 2 | **架构层级** | 两层：Orchestrator → Expert Agent → Skill |
| 3 | **工具执行模型** | 功能粒度 skill 化：1 工具的 1 个功能 = 1 个 skill |
| 4 | **保留交付表面** | WebUI + WS gateway / CLI REPL / OpenAI-compat HTTP API / Python SDK |
| 5 | **删除范围** | `channels/{im 13 个}` + `tests/channels/{im}` + `bridge/`（WhatsApp 桥）+ `tests/test_msteams.py` |
| 6 | **保留通道基础** | `channels/{base, manager, registry, websocket}` |
| 7 | **MVP 范围** | **L 档**：Baseline + 高危二次确认 + 上下文裁剪 + 轻量 CMDB + 多格式报告（MD/PDF/DOCX）|
| 8 | **UI 策略** | 现有 webui 演进 + 引入 `@assistant-ui/react` 作 Chat 壳；保留 Sidebar/Settings |
| 9 | **鉴权与审计** | 本地单用户 + 复用现有 token_issue_secret + SQLite 扫描历史（无 actor 区分）|
| 10 | **项目身份** | **secbot**（PyPI: `secbot-ai` / CLI: `secbot` / 包: `secbot/`）|

---

## Architecture Snapshot

```
┌──────────────────────────────────────────────────────────────────────┐
│  Surfaces  │  WebUI   │  CLI REPL  │  /v1/chat/completions │ Py SDK  │
└─────┬───────────┬──────────┬─────────────────┬───────────────┬───────┘
      │           │          │                 │               │
      └───── WebSocket ──────┴── (OpenAI-compat HTTP) ─────── (lib import)
                                  │
                                  ▼
            ┌────────────────────────────────────────────┐
            │  Orchestrator (LLM, ReAct loop)            │
            │  tools = [expert agents...]                │
            └────────────────────┬───────────────────────┘
                                 │ tool_call (with arg + ask_user gate for high-risk)
            ┌────────────────────┴────────────────────┐
            ▼                ▼                ▼       ...
   ┌────────────────┐ ┌──────────────┐ ┌──────────────┐
   │ asset_discovery│ │  port_scan   │ │  vuln_scan   │   Expert Agents
   │  (LLM, ReAct)  │ │ (LLM, ReAct) │ │ (LLM, ReAct) │   each w/ scoped
   │ tools=[skills] │ │ tools=[...]  │ │ tools=[...]  │   SKILL subset
   └────────┬───────┘ └──────┬───────┘ └──────┬───────┘
            │                │                │
   ┌────────┴───────┐ ┌──────┴───────┐ ┌──────┴────────┐
   │ nmap-host-disc │ │ nmap-portscan│ │ nuclei-vuln   │   Functional Skills
   │ fscan-asset-d  │ │ masscan      │ │ fscan-vuln    │   (1 skill = 1 fn)
   │ (subprocess)   │ │ (subprocess) │ │ (subprocess)  │   summary→LLM,
   └────────────────┘ └──────────────┘ └───────────────┘   raw→disk
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │  SQLite (local persistence) │
                  │  • assets (CMDB)            │
                  │  • scan_history             │
                  │  • findings                 │
                  │  • raw_logs (path refs)     │
                  └─────────────────────────────┘
```

---

## Requirements

### R1 包重命名与 IM 清理（基础工程）
- 全仓 `nanobot` → `secbot`：包目录、import、CLI 名、PyPI 元数据、README、文档、模板
- 删除 IM 通道：`channels/{telegram, feishu, slack, discord, dingtalk, msteams, qq, wecom, weixin, whatsapp, mochat, matrix, email}.py` + 对应测试
- 删除 `bridge/`（WhatsApp Baileys 桥）+ `docker-compose.yml` 中相关服务
- 保留 `channels/{base, manager, registry, websocket}.py`
- `nanobot.py` → `secbot.py`，CLI 入口同步

### R2 双层 agent 架构
- **Orchestrator**：复用 `agent/loop.py` + `agent/runner.py`；提示词模板换为安全调度词；工具列表 = expert agents
- **Expert Agents**：用 `agent/subagent.py` 定义；每个 expert agent 一份 yaml，列出：name / display_name / description / system_prompt / scoped_skills（skill 名白名单）
- **Skills**：复用 `nanobot/skills/`（→ `secbot/skills/`）目录约定；每个 skill 一个目录，含 SKILL.md + scripts/ + 输入输出 schema

### R3 安全工具 skill 化（首批）
覆盖 baseline 三步流程的 skill 集合（具体函数清单由 trellis-research 调研定）：
- 资产探测：`nmap-host-discovery`、`fscan-asset-discovery`、`masscan-discovery`（可选）
- 端口/服务：`nmap-port-scan`、`nmap-service-fingerprint`、`fscan-port-scan`
- 漏洞扫描：`nuclei-template-scan`、`fscan-vuln-scan`
- 弱口令：`hydra-bruteforce`、`fscan-weak-password`（**默认禁用，需高危二次确认**）
- 报告生成：`report-markdown`、`report-pdf`、`report-docx`
- 资产管理：`cmdb-add-target`、`cmdb-list-assets`、`cmdb-history-query`

### R4 高危动作二次确认
- skill 元数据增加 `risk_level: low | medium | high | critical`
- `critical` 类（hydra 暴破、外网扫描）调用前**强制**通过现有 `agent/tools/ask.py` 触发用户确认
- 用户拒绝即终止该 skill 调用，结果回灌主调度让 LLM 选择替代路径

### R5 上下文裁剪
- skill 执行结果分两路：
  - **回灌 LLM 的"摘要 JSON"**：结构化、字段裁剪、可截断长字符串
  - **落盘的"完整原始日志"**：写到 `~/.secbot/scans/<scan_id>/raw/<skill>.log`，UI 提供"查看原始输出"链接
- 摘要 JSON schema 在 SKILL.md 中声明

### R6 轻量 CMDB（SQLite）
- `~/.secbot/db.sqlite`，schema：
  - `assets(id, target, kind {cidr/ip/domain}, label, owner_note, created_at)`
  - `scans(id, asset_id, agent, started_at, finished_at, status)`
  - `findings(id, scan_id, severity, title, payload_json)`
  - `raw_logs(id, scan_id, skill, path)`
- WebUI 增加 Asset / ScanHistory / Report 三个顶级视图

### R7 多格式报告
- Markdown 默认（Jinja2 模板）
- PDF：评估 weasyprint vs wkhtmltopdf（trellis-research 调研）
- DOCX：python-docx
- 报告模板可扩展（templates/ 目录）

### R8 WebUI 改造
- 引入 `@assistant-ui/react` 作为 ChatPane / MessageList / Composer 的替换
- 保留现有 Sidebar / Settings / Theme / i18n 基础
- 新增视图：Assets / ScanHistory / Reports
- 安全主题：深色 + 海蓝强调色（`--primary: #1E90FF`，HSL 210 100% 56%；详见 research/cybersec-ui-patterns.md §3.3）
- MessageBubble 增强：tool-call 折叠展示 + scan-result 表格 + plan-step 时间轴

### R9 鉴权与审计 MVP
- 复用 `webui/.../token_issue_secret` 机制
- SQLite `scans` 表自动记录执行时间 / 状态（不带 actor）

---

## Acceptance Criteria

- [ ] **AC1**：全仓 grep `nanobot` 仅在历史 commit 信息 / CHANGELOG / 第三方协议中存在；运行时代码 / CLI / 包名为 `secbot`
- [ ] **AC2**：`secbot agent` CLI 可用；`secbot gateway` 起 WS gateway；`pip install -e .` + `secbot --help` 通过
- [ ] **AC3**：用户在 webui 输入"扫描 192.168.1.0/24 的高危漏洞"，Orchestrator 自动按 `asset_discovery → port_scan → vuln_scan` 顺序调度 expert agents，全程在 UI 时间轴可见，最终输出结构化 vuln 表
- [ ] **AC4**：新增一个 expert agent 仅需新增 yaml + 可选 SKILL；新增 skill 仅需新增目录 + SKILL.md，主调度代码 0 改动
- [ ] **AC5**：执行 hydra-bruteforce skill 前，UI 弹出 "高危动作确认" 对话框，列出目标和风险；用户取消则该 skill 不执行
- [ ] **AC6**：单次扫描完成后 SQLite 中 assets / scans / findings / raw_logs 表均有对应记录；WebUI Asset/ScanHistory 视图能展示
- [ ] **AC7**：从扫描历史可一键导出 Markdown / PDF / DOCX 三种报告
- [ ] **AC8**：扫描原始日志（可能 MB 级）不进入 LLM 上下文，仅摘要 JSON 入上下文；UI 提供 "查看原始日志" 跳转
- [ ] **AC9**：所有 IM 通道代码、`bridge/`、对应测试文件已删除；`pytest` 全绿；`grep -r telegram\|feishu\|slack\|discord` 在源码中无命中
- [ ] **AC10**：`.trellis/spec/secbot/` 下完整 spec 文档集存在并通过 `trellis-check`

## Definition of Done

- 单元测试 + 集成测试覆盖 Orchestrator + 3 个 expert agents + 6 个核心 skills 的 happy path
- lint / typecheck / CI 全绿
- README + AGENTS.md 重写为 secbot 平台定位
- 所有 subprocess 调用经过参数白名单 + shlex.split 校验，禁用 shell=True
- 高危动作 skill 默认 risk_level=critical
- WebUI 在 Chrome / Firefox 最新两个稳定版下手测通过
- spec 文档集（见下）完成并互相 cross-reference

---

## Out of Scope（明确排除）

- 周期性重扫 + 差异报告（cron 已存在但不做 secbot 专用 UI）
- 红蓝对抗 / 防御视角 agents（log-anomaly / ioc-hunting）
- 多用户 / RBAC / 不可篡改审计签名
- Skill marketplace / 用户上传 skill UI
- Agent-to-Agent 学习 / 历史 RAG
- SOAR / SIEM / Jira / Notion 集成
- 任何 IM 通道的"先关闭后续可恢复"模式（彻底删除）
- 漏洞库版本管理（仅依赖 nuclei-templates 自更新）

---

## Decision (ADR-lite)

### ADR-001 主调度架构 = OpenClaw tool-calling 循环
- **Context**：PRD 给出 DAG-Plan 与 OpenClaw 两种方案，且后半段倾向后者；nanobot 已有 subagent + tool registry
- **Decision**：OpenClaw 风格——专家智能体即工具，主调度走 ReAct 循环逐步调用
- **Consequences**：
  - ✅ 复用 `subagent.py` / `tools/registry.py` / `loop.py`
  - ✅ 新增 expert agent / skill 零侵入主调度
  - ⚠️ 长链路 token 成本较高，需要做上下文裁剪策略（已纳入 R5）

### ADR-002 架构层级 = 两层（Orchestrator → Expert → Skill）
- **Context**：扁平架构在 skills 数量 > 30 后 prompt 膨胀且 LLM 选错率上升
- **Decision**：Orchestrator 工具列表只暴露 expert agents；每个 expert agent 内部再持有领域 skill 子集
- **Consequences**：
  - ✅ 主调度 prompt 稳定，与 skills 数量解耦
  - ✅ Skill 在领域内 LLM 选择准确度高
  - ⚠️ 多一层 LLM 调用，需做并发与缓存（评估）

### ADR-003 工具执行 = 功能粒度 skill 化（subprocess in skill）
- **Context**：用户明确："工具的每个功能封装成 skill，由 LLM 自主发现"
- **Decision**：1 工具的 1 个独立功能 = 1 个 skill；subprocess 由 skill 内部封装；统一参数白名单
- **Consequences**：
  - ✅ 复用 nanobot 已有 skills 体系工程接口
  - ✅ LLM 见到的工具名是语义化的（fscan-weak-password 而非 fscan）
  - ⚠️ skill 数量会比想象的多（fscan 一个工具可能派生 5+ skill）

### ADR-004 UI = 现有 webui 演进 + assistant-ui 混合
- **Context**：现有 webui Sidebar/ThreadShell/Composer/Settings 完整且基于 shadcn；@assistant-ui/react 原生支持 streaming + tool-call viz
- **Decision**：保留外壳与导航，把 ChatPane 内部用 assistant-ui 重写
- **Consequences**：
  - ✅ 不重做导航/设置/主题
  - ⚠️ 需要 trellis-research 验证 assistant-ui 与现有 WS streaming 协议的对接

### ADR-005 鉴权 = 本地单用户
- **Context**：MVP L 档；用户为安全研究人员个人使用
- **Decision**：复用 token_issue_secret，扫描历史不区分 actor
- **Consequences**：
  - ✅ 不引入用户表 / 角色表 / 审批流
  - ⚠️ 一旦未来转向团队部署，需要补 actor 字段（已在 schema 预留扩展点）

### ADR-006 命名 = secbot
- **Context**：用户选 "完全重命名"
- **Decision**：包/CLI/PyPI 全部用 `secbot`
- **Consequences**：
  - ⚠️ 一次性大规模 import 改造，集中在一个 PR

---

## Implementation Plan (small PRs)

| PR | 内容 | 风险 |
|----|------|------|
| **PR1** | 全仓 `nanobot` → `secbot` 重命名（包 / import / CLI / 元数据 / 文档），CI 通过 | 高（接触面广，需自动化脚本） |
| **PR2** | 删除 IM 通道 + bridge + tests 中相关文件；docker-compose 清理 | 低（孤立删除） |
| **PR3** | `.trellis/spec/secbot/` 写 spec 文档集（11 份，见下） | 低（文档） |
| **PR4** | SQLite schema + migrations + repository 层（assets / scans / findings / raw_logs） | 中 |
| **PR5** | 引入 expert agent registry：YAML 加载 + 注册到主调度 | 中 |
| **PR6** | 6 个核心 skill 实现（asset/port/vuln 各 2 个），含 subprocess 封装 + 参数白名单 + 摘要裁剪 | 高（外部命令注入风险） |
| **PR7** | Orchestrator 提示词重写 + 高危二次确认 hook | 中 |
| **PR8** | WebUI 接 `@assistant-ui/react`，重写 ChatPane / MessageList | 中 |
| **PR9** | WebUI 新增 Assets / ScanHistory / Reports 视图，连 SQLite REST | 中 |
| **PR10** | 报告生成 skill：MD / PDF（weasyprint）/ DOCX（python-docx），模板可扩展 | 低 |

---

## Spec 文档集（输出到 `.trellis/spec/secbot/`）

| 文档 | 用途 |
|------|------|
| `index.md` | secbot spec 入口与导航 |
| `architecture.md` | 双层架构 / 数据流 / 边界 |
| `agent-registry-contract.md` | Expert agent YAML schema + 注册流程 |
| `skill-contract.md` | SKILL.md schema + 输入输出 / risk_level / summary 规范 |
| `orchestrator-prompt.md` | 主调度系统提示词模板 + 多轮策略 |
| `tool-invocation-safety.md` | subprocess 封装 / 参数白名单 / shlex / 注入防御 |
| `high-risk-confirmation.md` | risk_level 分级 + ask_user 触发契约 |
| `context-trimming.md` | 摘要裁剪规则 / 落盘路径 / 大文件策略 |
| `cmdb-schema.md` | SQLite schema + 迁移规则 + 扩展点（actor 预留）|
| `report-formats.md` | Markdown / PDF / DOCX 模板与生成路径 |
| `webui-design.md` | 视图层级 / assistant-ui 集成 / 主题色系 / MessageBubble 渲染契约 |
| `removed-im-channels.md` | 已删除组件清单 + 移除理由（防回滚误操作） |

---

## Research Tasks（用 trellis-research 子代理并行调研）

| 主题 | 输出文件 |
|------|----------|
| `@assistant-ui/react` 与 shadcn 集成路径 + WebSocket streaming 兼容性 + tool-call 可视化能力 | `research/assistant-ui-integration.md` |
| fscan / nuclei / nmap / hydra / masscan 的"独立功能"清单 + CLI 调用 schema + JSON 输出格式 | `research/security-tool-functions.md` |
| 安全行业对话/仪表盘 UI 模式（Bishop Fox / Dradis / DefectDojo / Faraday）+ 配色 + 严重度可视化 | `research/cybersec-ui-patterns.md` |

---

## Technical Notes

### 已读关键文件
- `prd.md`（仓库根，上层需求）
- `nanobot/agent/{loop,runner,subagent}.py` + `agent/tools/`
- `nanobot/channels/*.py`（确认 IM 删除范围）
- `nanobot/skills/`（复用模型）
- `webui/src/{App.tsx, components/*, hooks/*}`
- `webui/package.json`
- `bridge/{src/, package.json}`（确认是 WhatsApp 桥）

### 现有可复用资产
- `agent/loop.py`（1415 行）：主 ReAct 循环
- `agent/subagent.py`（359 行）：sub-agent 派生与上下文管理
- `agent/tools/{ask, registry, schema, sandbox}`：高危确认 / 工具注册 / schema 验证 / 沙盒
- `skills/`：configurable skill 体系
- `templates/{AGENTS, SOUL, TOOLS, USER, HEARTBEAT}.md`：系统提示词模板
- `channels/{base, manager, registry}`：通道基础设施
- `channels/websocket.py`：webui 后端
- `api/server.py`：OpenAI-compat HTTP API
- `webui/`：完整 React + shadcn 前端

### 删除候选清单
**Python**: `channels/{telegram, feishu, slack, discord, dingtalk, msteams, qq, wecom, weixin, whatsapp, mochat, matrix, email}.py`
**Tests**: `tests/channels/test_{im 各项}.py` + `tests/test_msteams.py`
**Node**: `bridge/` 整个目录
**Docs**: docker-compose.yml 中 bridge 服务条目（待查）+ docs/chat-apps.md 中 IM 章节

### Skill 数量预估
- 资产探测: 4
- 端口扫描: 3
- 漏洞扫描: 3
- 弱口令: 2
- 报告生成: 3
- CMDB 操作: 3
- 共约 18 skill（baseline 三步流程的 6 个为 P0）
