# Write Agent.md — Universal Agent Dev Doctrine from Hermes

## Goal

写一份独立的 `Agent.md`，**项目无关、与本仓库代码解耦**，纯粹提炼 https://pty819.github.io/hermes-docs 19 章 + 工程教训中的可复用准则。
目标受众：任何在做 AI Agent 开发的人（不限 secbot），让他们能把 Agent.md 复制粘贴进任何新项目当作开发铁律来用。

## What I already know

### 范围决策（已与用户确认）

- **写作风格**：开发准则手册（do/don't 清单 + Hermes 教训出处 + 反模式），~800-1500 行。
- **文件归属**：新增 `Agent.md` 到项目根目录；**不动** `AGENTS.md`（Trellis 引导）和 `Pi Agent.md`（历史草稿）。
- **不绑定 secbot**：不引用 `.trellis/spec/backend/` 任何细则；不写 Orchestrator/HighRiskGate/Blackboard 等 secbot 概念；不参考 secbot 代码骨架。
- **覆盖范围**：Hermes 19 章对应的主题（主循环、工具、提示、上下文、会话、配置、模型路由、CLI/UI、IPC、MCP、插件、技能、安全、协作）+ Part2 工程教训 + Build Your Own。

### Hermes 已抓取并提炼的素材（按主题）

| 主题 | 关键铁律候选 |
|------|--------------|
| 主循环 | 14 种错误分类；iteration budget + grace call；同步主循环 + 按需 async；回调必须 try/except |
| 工具系统 | self-registration + AST 扫描；三档并行（NEVER/PARALLEL_SAFE/PATH_SCOPED）；类型矫正；三层 result budget；工具名修复 + 3 次重试上限 |
| 提示工程 | 9-slot pipeline；prompt cache 必须字节一致；4 个 cache 断点（system + 3 滚动）；注入扫描 10 正则 + 10 invisible Unicode |
| 上下文压缩 | 预压缩（70-80% 阈值）；降级链 LLM summary → static truncate；token budget 公式 |
| 会话状态 | SQLite + WAL + FTS5；50 次写 PASSIVE checkpoint；schema 迁移链；session 分支 |
| 配置 | 4 层叠加；.env 0600；Profile 系统；显式凭据配置 gating |
| 模型路由 | Adapter + SimpleNamespace；连接池复用；402 歧义消解；凭据池轮转 |
| IPC | JSON-RPC over stdin/stdout；SlashWorker 隔离子进程；optimistic concurrency control |
| MCP | OAuth 2.1 PKCE state/verifier 分离；熔断器；描述注入扫描（warn-level）；命名空间冲突保护 |
| 插件/技能 | progressive disclosure；双层缓存（LRU + JSON）；plugin pre/post hook |
| 安全 | 38+ 危险命令模式；NFKC + ANSI 去除；approval 3 模式；env 变量剥离；credential redact；Tirith 预扫；浏览器私网阻断 |
| 工程教训 | 8 大模式（Strategy/Self-Reg/Observer/Adapter/Circuit Breaker/Optimistic/WAL/Adapter）；3 大技术债（god class 12k 行 / provider hack 散落 / 手动 cache 失效） |
| Build Your Own | MVA 200 行结构；Mono vs Micro 决策；5 阶段 roadmap |

### 决策原则（已确认）

> "**简单的、可靠的、可调试的方案，永远优于优雅的、复杂的、难以理解的方案。**" — Hermes 全书核心信念，作为 Agent.md 卷首语。

## Requirements

- [ ] 项目无关：不出现 secbot/VAPT3/nanobot 任何标识符或文件路径。
- [ ] 每条铁律必须含三段式：**铁律陈述** + **Hermes 出处/教训** + **反模式示例**。
- [ ] 章节按"由内向外"排序：核心循环 → 工具 → 提示 → 上下文 → 会话 → 配置 → 模型路由 → IPC → MCP → 插件/技能 → 安全 → 工程模式总结 → 构建路线图。
- [ ] 卷首语用 Hermes 的核心信念。
- [ ] 末尾附 Hermes 19 章索引链接，方便深挖。
- [ ] 文档可以直接复制到任何 Agent 项目根目录使用。

## Acceptance Criteria

- [ ] 文档 800-1500 行之间。
- [ ] 每章节有清晰的"铁律 / 反模式 / Hermes 教训"三段结构。
- [ ] 至少覆盖 12 个 Hermes 主题（见上表）。
- [ ] 包含至少 8 条来自 lessons.html 的可复用原则。
- [ ] 包含至少 5 个具体反模式（god class、asyncio.run、共享完整会话、手动 cache 失效、未分类错误吞噬等）。

## Out of Scope

- 不写 secbot 具体落地。
- 不引用 `.trellis/spec/backend/*.md`。
- 不参考 `secbot/agent/loop.py` 或任何项目内代码。
- 不修改任何现存文件。
- 不实现代码。

## Decision (ADR-lite)

**Context**：用户希望产出一份可在任意 Agent 项目复用的开发准则。
**Decision**：完全脱离 secbot 上下文，纯粹以 Hermes 教训为基础写通用 Agent.md。
**Consequences**：失去了 secbot 落地的具象感，但获得了跨项目复用能力；Agent.md 与 secbot 的具体 spec 互为正交。

## Technical Notes

- 已抓取 Hermes 4 个核心页面：lessons.html / build-your-own.html / agent-loop.html / security.html。
- 默认语言：中文（与 Hermes 文档语言一致；用户 PRD/对话语言一致）。
- 默认存放位置：`/Users/shan/Downloads/nanobot/Agent.md`（项目根目录）。
