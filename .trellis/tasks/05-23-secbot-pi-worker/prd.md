# 重构 secbot 为 Pi 主控 + 受限 worker 架构

## Goal

把 `secbot/` 从「Orchestrator + 7 个预定义 Expert Agent 线性管道」重构为 Pi Agent.md
定义的「**Pi 主智能体（判断与编排）+ Skill（方法与工具约束）+ 知识库（专家知识检
索）+ 受限 worker（可隔离子任务）+ 结构化黑板（共享状态）+ Policy Engine（什么绝
不能做）**」架构：

- **不预定义 agent 具体功能，不固定线性路径** —— 以 DAG 探索；
- 用 **时间 15min + 工具调用 60 次** 作为预算上限；达限后总结发现/阻碍再思考；
- worker 只承接「明确可并行、可隔离、低风险」的子任务，**主决策链由 Pi 唯一拥有**；
- 黑板共享 **结构化状态**（scope/phase/evidence/findings/hypotheses/approvals），
  不共享聊天历史与未清洗原始输出。

> 用户明确指示：忽略所有现有 PRD 文件，直接基于代码事实和 Pi Agent.md 设计 spec。

## What I already know (from code, not from PRDs)

### 当前架构事实（截止 2026-05-23）

| 层 | 文件 | 现状 |
|---|---|---|
| 主控 | `secbot/agent/loop.py` (1836 行) | LLM ReAct 主循环；按 turn 绑定 `BlackboardRegistry` / `AssetFeedRegistry` / `bind_skill_context` |
| 编排提示词 | `secbot/agents/orchestrator.py` | **硬编码线性顺序** `asset_discovery → port_scan → vuln_scan → (weak_password \| pentest) → report`；强制 `report` 收尾 |
| Expert 注册 | `secbot/agents/*.yaml` (7 个) + `registry.py` | 1 个 expert = 1 块 `system_prompt` + `scoped_skills` + `output_schema` + 可选 `endpoint_bound` + `allow_exec` |
| 子 agent 池 | `secbot/agent/subagent.py` (813 行) | `SubagentManager.spawn(agent=..., target=..., endpoint_url=..., endpoint_param=...)`；endpoint 互斥锁 `_endpoint_inflight`；每 task 隔离 `FileStates` |
| Skill | `secbot/skills/<name>/{SKILL.md, handler.py}` + `skills/metadata.py` | 19 个内置 skill；front-matter 含 `risk_level/category/external_binary/network_egress/expected_runtime_sec/summary_size_hint` |
| 高危门 | `secbot/agents/high_risk.py` | `risk_level=critical` 必须 `ctx.confirm`，approve 后同会话缓存放行 |
| 黑板 | `secbot/agent/blackboard.py` + `tools/blackboard.py` | **纯文本 + `[milestone/blocker/finding/progress]` 标签**；按 `chat_id` 隔离；非结构化 |
| 资产流 | `secbot/agent/asset_feed.py` + `tools/asset_feed.py` | 实时 URL/port/vuln/cred 推送，唤醒 orchestrator |
| Teammate | `secbot/agent/teammate.py` + `tools/teammate.py` | 持久化 mailbox 协作（与 `spawn` 是两种生成方式） |
| 工作流脚本 | `secbot/workflow/` (runner/service/store/templates/scripts/expr/executors) | YAML 固定脚本编排层，独立于 LLM ReAct |
| Sandbox | `secbot/agent/tools/sandbox.py` | 仅 `bwrap`（Linux container）；`ExecTool` 在主 loop 默认禁用 |
| SSRF | `secbot/security/network.py` | `validate_url_target` 阻断 RFC1918 + cloud metadata；CIDR 白名单 |
| Skill 上下文 | `secbot/agent/tools/skill.py` 用 `ContextVars` 注入 `scan_id/scan_dir/confirm/progress` | OK |
| Audit | `agents/high_risk.py::AuditLogger` | 仅 critical confirm 流的内存 emit |
| Provider | `secbot/providers/` factory + base | 多 LLM 适配（OpenAI Responses / 兼容） |

### 已有可复用基建

- 子 agent 隔离 + 端点互斥（Pi worker 池骨架已就位）
- Skill 抽象（risk/network/binary/runtime hint 已经全有）
- BlackboardRegistry 按会话隔离（多目标隔离基础）
- AssetFeed 实时增量推送（worker → 主控的事件通道）
- HighRiskGate audit + confirm pattern（Policy Engine 起点）
- AgentRegistry YAML 加载 + JSON Schema 校验（可演化为 Worker Profile / Skill Bundle）
- Provider/Bus/WebSocket/WebUI 已稳定

## Gap Analysis — 当前 vs Pi Agent.md 目标

| Pi Agent.md 目标 | 当前 secbot | 差距 |
|---|---|---|
| **DAG 探索 + budget**（15min / 60 调用） | 硬编码线性 5 阶段，无 budget tracker | ❌ 缺 budget；需重写 orchestrator prompt + 加运行时门 |
| **不定义具体功能 worker**（受限 Pi 实例 + skill 限制） | 7 个 expert 各自有手写 `system_prompt`，name=功能 | ⚠️ 需把 expert 抽象为「worker profile = scoped_skills + risk + scope contract」 |
| **结构化黑板**（targets/scope/phase/evidence/findings/hypotheses/approvals） | 纯文本 + tag | ❌ 需要把 `BlackboardEntry` 扩展为 typed kinds + 独立 `EvidenceStore` |
| **Policy Engine**（scope allow/deny + rate limit + credential boundary + destructive gate + human approval gate） | 仅 HighRiskGate 一个点 | ❌ 需统一 PolicyEngine：每次工具调用前 `check(scope, action, risk)` |
| **Knowledge Base / RAG**（OWASP/CWE/CVE/历史报告/严重性标准/payload risk） | 无 | ❌ 全新；MVP 可用 phase-aware 文件检索 |
| **Finding Ontology**（CWE / OWASP category / asset type / impact type / confidence） | findings 是各 skill 自由格式 | ❌ 需新增 ontology schema + skill 输出归一 |
| **Evidence Store**（独立存储 + evidence_id + 脱敏） | raw_log_path 散落 + 在 blackboard text 里 | ⚠️ 需独立 store，绑定 finding_id ↔ evidence_id |
| **Event Stream**（每次计划/工具调用/结果/审批 event_id） | WebSocket broadcast 是临时事件，无持久 event_id 链 | ❌ 持久化 + 可重放 |
| **/tree resume** 分支管理（main / exploration / branch summary） | 仅 spawn_teammate（mailbox 持久），不是会话分支 | ⚠️ 需新增 BranchManager + branch summary |
| **Sandbox 网络 egress policy** | bwrap 仅 Linux + 默认禁 exec；SSRF 拒内网；无 per-target egress allowlist | ⚠️ 需 per-scope egress 白名单 |
| **DAG task graph** | workflow YAML 是预定义脚本，不是 LLM 探索图 | ⚠️ 需要 TaskGraph 抽象（节点=hypothesis/observation/action） |

## Requirements (target architecture)

### 控制平面

1. **Job Manager** —— 接收目标 + 授权证明 + 测试窗口 + 账号 + 禁止动作，生成
   `ScopeContract`。
2. **Pi Orchestrator** —— LLM ReAct，**不再硬编码线性阶段**；prompt 由
   - 当前 phase（initial / passive-recon / mapping / hypothesis / safe-validation /
     triage / report）
   - 已知 ScopeContract
   - 当前 budget 剩余
   - 黑板结构化快照（不传聊天历史）
   - Skill / Worker 注册表 — 拼装。
3. **Policy Engine** —— 单点 `check(action, args, ctx) → allow|deny|need_approval`，
   合并：scope 内/外、destructive gate、rate limit、credential boundary、approval。
4. **State Manager** —— 拥有 task graph（DAG，节点 = observation / hypothesis /
   action / approval / finding）+ phase 转移 + budget tick。
5. **Budget Enforcer** —— wall-clock + tool-call-count 双轨；达限触发 `summarize &
   reflect` 路径而非硬停。

### 执行平面

6. **Tool Router** —— 所有 LLM 工具调用统一过 Router：参数 schema 校验 + 自动注入
   scope + 自动加 timeout/rate-limit + 进入 Policy Engine。
7. **Worker Pool** —— 受限 Pi 子进程；spawn 入参 = `WorkerProfile(allowed_skills,
   scope_view, blackboard_view, budget)`；**无最终漏洞确认权 / 无报告签发权**。
8. **Sandbox Runner** —— 每 target/task 独立容器；网络 egress 按 ScopeContract
   allowlist；secret 注入最小化。
9. **Browser Runner** —— authenticated context；session 隔离；HAR/screenshot/DOM
   摘要 → Evidence Store。

### 知识平面

10. **Skill Registry** —— 现有 SKILL.md 元数据基础上 + 添加 `methodology`、
    `output_schema`（统一到 Finding Ontology）、`safety_policy`、`evidence_schema`。
11. **Knowledge Base** —— phase-aware retrieval，至少：OWASP WSTG / ASVS、CWE、
    CVE 摘要、内部历史报告、严重性评级标准、修复建议模板。MVP 可用纯文件 + 关键
    词 + embedding 二选一。
12. **Finding Ontology** —— `{cwe, owasp_category, asset_type, impact_type,
    confidence, severity}` 统一 schema；skill 输出强制映射。

### 审计与报告平面

13. **Event Stream** —— append-only `event_log`，每条 `event_id` + 类型（plan /
    tool_call / tool_result / approval / finding / phase_transition）；可重放。
14. **Evidence Store** —— `EvidenceRecord(id, type, source_tool, summary, raw_ref,
    sanitised, created_at)`；finding ↔ evidence 多对多。
15. **Report Builder** —— 输入 = 已确认 finding + evidence；输出 = executive
    summary / technical / evidence / risk / remediation / retest notes。

### MVP 边界（PR 顺序）

按 Pi Agent.md §8「先不要做复杂 subagent」：

- **MVP PR1**：StructuredBlackboard（typed kinds：scope/phase/evidence/finding/
  hypothesis/approval）+ EvidenceStore；保留旧文本 entry 兼容。
- **MVP PR2**：PolicyEngine 单点 + 改造 Tool Router 让所有 SkillTool 经过它（先合
  并 HighRiskGate + SSRF + workspace restrict）。
- **MVP PR3**：BudgetEnforcer（wall-clock + tool-count）+ 替换 orchestrator
  prompt 的硬编码顺序为 DAG-aware「按 phase 思考下一步」。
- **MVP PR4**：FindingOntology schema + skill 输出归一适配层；ReportBuilder 用结
  构化输入。
- **MVP PR5**：EventStream 持久化（SQLite append-only）。

### V2 边界

- V2 PR6：WorkerProfile（替代 expert YAML 1:1 模式），允许任意组合 scoped_skills。
- V2 PR7：KnowledgeBase phase-aware retrieval（先文件 + grep，再上 embedding）。
- V2 PR8：BranchManager（main / exploration branch + branch summary，呼应
  Pi `/tree` 思路）。
- V2 PR9：per-scope network egress allowlist；BrowserRunner with HAR。

### 显式不做（Out of Scope）

- **不删除** workflow YAML scripts —— 它是「高层固定脚本编排」，与 Pi 探索模式正
  交（如固定合规扫流水线）；保留作为旁路通道，仅停用 Orchestrator 对它的强依赖。
- 不引入新的 LLM provider；继续用现有 `providers/factory.py`。
- 不重写 WebUI；事件流通过既有 WebSocket。
- 不动 CMDB schema 主体；新增 `events`/`evidence`/`findings_v2` 表即可。

## Acceptance Criteria (evolving)

- [ ] AC1：orchestrator system prompt 不再含 `asset_discovery → port_scan → ...`
  字面顺序；改为 phase-aware 决策模板（`render_orchestrator_prompt` 重写）。
- [ ] AC2：`Blackboard` 支持读写 typed kinds `{scope, phase, finding, hypothesis,
  evidence_ref, approval}`，旧 `text+tag` 写法保持兼容。
- [ ] AC3：每次工具调用前 Tool Router 经过 PolicyEngine.check，被拒绝时返回结构化
  `{denied, reason, suggest}` 而非抛异常。
- [ ] AC4：每个 task 启动时初始化 BudgetTracker(wall_clock=15min, tool_calls=60)，
  达限触发「summarize & reflect」hook 而非 hard-stop。
- [ ] AC5：Skill handler 输出归一为 `Finding` ontology（cwe/owasp/asset_type/...），
  raw 输出留 `EvidenceRecord`。
- [ ] AC6：`event_log` 表存在 + 每个 plan/tool_call/approval/finding 落盘可重放。
- [ ] AC7：worker（subagent）启动时获得 `WorkerProfile`，无报告/最终确认工具。

## Definition of Done

- spec 文档落在 `.trellis/spec/backend/` 下，至少 6 个新 spec：
  `pi-orchestrator.md` / `policy-engine.md` / `structured-blackboard.md` /
  `budget-enforcer.md` / `finding-ontology.md` / `event-stream.md`。
- `architecture.md` 增补 V2 章节（Pi 架构图替代两层管道）。
- 对每条 AC 标注覆盖的 spec 锚点。
- 现有 200+ 测试不破坏（每个 PR 单跑 pytest）；新增 spec-level acceptance test
  框架草案。

## Decision (ADR-lite) — 已锁定

### D1 Expert YAML 处置 = **保留为 worker preset alias**

- **Context**：现 7 个 expert YAML 与 LLM prompt / 测试 / Skill 路由耦合很深；
  彻底删除迁移成本高。
- **Decision**：新增 `agents/presets/{recon,crawl,triage,report}.yaml` 4 个泛化
  preset；旧 7 个 YAML 移到 `agents/legacy/`，每个声明 `alias_of: <preset>` +
  「附加 scope/skill 修饰」（如 `port_scan` 继承 `recon` 但限制 `scoped_skills`
  到端口扫类）。LLM 既能调旧名也能动态拼装新 worker。
- **Consequences**：worker pool 真正泛化，向后兼容；`AgentRegistry` 需扩展支持
  `alias_of` + skill 子集裁剪。`orchestrator-prompt.md` 旧 spec 中 7 个 expert
  专属规则全部弃用，新 prompt 不再硬编码顺序。

### D2 Budget 达限 = **Reflect-then-checkpoint**

- **Context**：Pi Agent.md §1「达限后总结发现和阻碍 ... 进入思考（在当前状态我还
  能尝试什么）」。
- **Decision**：BudgetEnforcer 在 wall-clock 15min 或 tool_calls 60 任一触发时，
  立即注入一条 system 消息让 Pi 做 `summarize_findings + list_blockers +
  propose_next_steps`，写入黑板与 event_log，然后发 `checkpoint` 事件给前端，
  worker 全部暂停。用户决定 `resume / abort / extend_budget`。
- **Consequences**：长流程不会暴毙；UI 需新增 checkpoint 卡片 + resume 按钮；
  `event_log` 必须能记录 `phase=checkpoint`。

### D3 KnowledgeBase = **MVP 占位 + V2 实现**

- **Context**：embedding / RAG 体量大且需要评测集；MVP 优先把结构化黑板/Policy/
  Budget 落地。
- **Decision**：MVP 仅落 `KnowledgeRetriever` Protocol + `NullRetriever`；
  Pi prompt 留 hook 但默认不调用。V2 PR7 再实装 `FileRetriever`（grep 静态
  OWASP/CWE）→ `EmbeddingRetriever`。
- **Consequences**：MVP 不引入新二进制依赖；spec 留 `knowledge-retriever.md`
  接口规范，但实现可推迟。

### D4 TaskGraph 持久化 = **SQLite + EventStream 重放**

- **Context**：resume / 审计 / 跨进程重启都要求持久化；现有 CMDB 已用 SQLite。
- **Decision**：新增 `task_graph_nodes(id, chat_id, kind, status, payload_json,
  created_at, parent_node_id NULL)` + `task_graph_edges(parent_id, child_id,
  edge_kind)` + `event_log(id, chat_id, type, payload_json, ts)`。所有 plan /
  tool_call / tool_result / approval / finding / phase_transition 走 event_log
  append-only；重启 / resume 时从 event_log 按 chat_id 重建 TaskGraph。
- **Consequences**：CMDB 多 3 张表；`event-stream.md` spec 需明确 schema；旧
  blackboard text entries 写一个 `event.kind=blackboard_legacy` 兼容层即可。

## Open Questions

> 全部已 closed（见 ADR-lite D1-D6）。

## Decision (ADR-lite) — D5 / D6 续

### D5 交付边界 = **spec 已交付，当前编码延续从 PR1 开始**

- **Context**：2026-05-23 的 spec 设计任务已经交付；用户在后续目标中要求
  「根据 05-23-secbot-pi-worker 进行编码，先调用 brainstorm」。
- **Decision**：本任务继续作为 Pi 架构迁移的承载任务，编码从 **PR1
  StructuredBlackboard + EvidenceStore** 开始。PR1 只落实
  `structured-blackboard.md` 规定的 typed blackboard 兼容层与 EvidenceStore，
  不提前实现 PolicyEngine / BudgetEnforcer / Pi prompt / FindingOntology /
  EventStream。
- **Consequences**：实现阶段必须先注入 PR1 所需 spec 到 `implement.jsonl` /
  `check.jsonl`，再 `task.py start`。后续 PR2-PR5 仍按路线拆分，避免一次改动跨越
  多个架构层。

### D6 `secbot/workflow/` 处置 = **保留作旁路**

- **Context**：1600+ 行独立编排，独立 API/store/runner；与 Pi 探索模式正交。
- **Decision**：保留 `secbot/workflow/`；Pi orchestrator prompt 不再提及它；不动
  现有调用入口；后续若要收编，作为单独任务规划。
- **Consequences**：本次重构只动 `secbot/agent/` + 新加 `secbot/policy/` /
  `secbot/state/` / `secbot/knowledge/`（接口位）。

## Final Implementation Plan

### spec 文件结构（本任务交付物）

```
.trellis/spec/backend/
  pi-orchestrator.md         # 替换旧 orchestrator-prompt.md (旧 spec 标注 DEPRECATED)
  structured-blackboard.md   # 替换旧 blackboard-registry.md (扩展兼容)
  policy-engine.md           # 新 — 合并/扩展 high-risk-confirmation.md
  budget-enforcer.md         # 新
  finding-ontology.md        # 新 — 与 skill-contract.md 联动
  event-stream.md            # 新 — task_graph + event_log schema
```

### PR 路线（spec 之后的代码任务，按依赖顺序）

| PR | 标题 | 引用 spec | 关键改动 |
|---|---|---|---|
| PR1 | StructuredBlackboard + EvidenceStore | structured-blackboard.md | 扩展 `Blackboard` 为 typed kinds；新建 `EvidenceStore`；旧 text entry 兼容层 |
| PR2 | PolicyEngine + Tool Router | policy-engine.md | 新建 `secbot/policy/engine.py`；改 `ToolRegistry` 走单点 `check`；并入 HighRiskGate 与 SSRF |
| PR3 | BudgetEnforcer + Pi prompt | budget-enforcer.md + pi-orchestrator.md | 新建 `BudgetTracker`；重写 `render_orchestrator_prompt` 为 phase-aware；checkpoint 事件 |
| PR4 | FindingOntology + ReportBuilder v2 | finding-ontology.md | Skill 输出归一适配；改 `report-html` skill 用结构化输入 |
| PR5 | EventStream 持久化 | event-stream.md | 新建 SQLite 3 表 + replay；event_log append-only |

### 显式不做

- 不改 webui frontend；事件经 WebSocket 既有协议
- 不引新 LLM provider
- 不动 CMDB 既有表
- 不重写 Workflow 子系统
- 不集成 KB embedding（V2）
- 不新增 BrowserRunner with HAR（V2）

## Acceptance Criteria (final)

- [ ] AC1：6 个新 spec 文件存在于 `.trellis/spec/backend/`，每个含「Status /
  Replaces / Implements / Open issues」头表
- [ ] AC2：`orchestrator-prompt.md` 添加 `> ⚠ DEPRECATED: superseded by
  pi-orchestrator.md` 顶注（不删除，保留历史）
- [ ] AC3：`blackboard-registry.md` 添加扩展指针指向 `structured-blackboard.md`
- [ ] AC4：每个 spec 至少含：**Goal / Non-Goals / Schema or Interface /
  Lifecycle / Error/Edge cases / Migration & Compat / Test plan**
- [ ] AC5：PRD ADR-lite 段落含 D1-D6 全部决策
- [ ] AC6：每个 spec 文末显式列出对应代码 PR 编号（PR1-5）+ 实施任务追踪锚点
- [ ] AC7：`architecture.md` 顶部加一段「Two-layer → Pi-architecture migration」
  指引（不删旧版，保留参考）

## Definition of Done

- 6 个新 spec 已写完 + PRD 锁定 + `architecture.md` 增补段落 + 旧 spec 顶注完成
- PR1 编码完成：typed Blackboard 兼容层 + EvidenceStore + sanitizer + 对应测试
- PR1 不实现 policy / budget / orchestrator prompt / finding ontology / event stream
- 现有相关测试通过；新增 PR1 覆盖按 `structured-blackboard.md` 的 test plan 对齐

## Delivery Status — 2026-05-23

✅ 已交付：

- `.trellis/spec/backend/pi-orchestrator.md` — 316 行
- `.trellis/spec/backend/structured-blackboard.md` — 358 行
- `.trellis/spec/backend/policy-engine.md` — 473 行
- `.trellis/spec/backend/budget-enforcer.md` — 336 行
- `.trellis/spec/backend/finding-ontology.md` — 347 行
- `.trellis/spec/backend/event-stream.md` — 411 行
- `architecture.md` §0 增补段落（Migration Note）
- `orchestrator-prompt.md` / `blackboard-registry.md` / `high-risk-confirmation.md`
  各加 SUPERSEDED / EXTENDED / DEPRECATED 顶注

## Next Step — 建议下一任务 (PR1 入口)

```
slug:  secbot-pr1-structured-blackboard
goal:  按 structured-blackboard.md 实施 StructuredBlackboard + EvidenceStore
files:
  - secbot/agent/blackboard.py
  - secbot/agent/tools/blackboard.py
  - secbot/evidence/__init__.py (new)
  - secbot/evidence/store.py (new)
  - secbot/evidence/sanitiser.py (new)
  - secbot/cmdb/migrations/0007_evidence.sql (new)
guard:
  - 不动 policy / budget / orchestrator prompt（留给 PR2/PR3）
  - 保留 Blackboard.write_text 兼容路径 ≥ 1 milestone
  - WebSocket payload 加 kind/payload 字段（前端兜底 null）
```

## Coding Continuation — 2026-05-24

当前目标：按上面的 PR1 入口直接实现 StructuredBlackboard + EvidenceStore。

实现边界：

- 改 `secbot/agent/blackboard.py` 与 `secbot/agent/tools/blackboard.py`，增加 typed
  `kind + payload` API，同时保留旧 `write(agent, text)` / `read()` / REST/WS 兼容。
- 新增 `secbot/evidence/`，实现 `EvidenceStore` 与 `sanitiser`，以 SQLite +
  workspace 文件引用为 MVP 存储。
- 增加/更新测试覆盖 typed kind、legacy text 映射、snapshot、EvidenceStore
  写入/读取/脱敏/关联。
- 暂不改 orchestrator prompt、PolicyEngine、BudgetEnforcer、FindingOntology
  schema 双写或 EventStream 落盘。

## Research References

（待 trellis-research 子 agent 填充：Pi 多 agent 框架对比 / OWASP ASVS 结构化加载
方式 / Finding ontology 业界范例 / OpenSearch 等 evidence store）

## Technical Notes

- Pi Agent.md §1 表格：方案二（Pi 主控 + skill + tree/resume）+ 少量受限 worker
  是**最高推荐**，与本 PRD 一致。
- 现 `orchestrator-prompt.md` spec 与目标冲突 —— 重构后该 spec 需作废或重写为
  `pi-orchestrator.md`。
- `agent-registry-contract.md` §5「一个 skill 只能属于一个 expert agent」在
  WorkerProfile 模型下需要重新讨论（worker 池可能多 worker 共享同一 skill）。
- `secbot/workflow/` 与 `secbot/agent/` 是两套并行编排；本次重构只动 `agent/` +
  新加 `policy/` `state/` `knowledge/`。
