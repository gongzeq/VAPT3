**Pi 做主智能体/总控，skill 管工具和方法论；只在明确可并行、可隔离、低风险的任务上启动多个 Pi 实例作为 worker/subagent**。不定义智能体具体功能，不定义具体线性路径方案，以DAG图进行探索；靠时间15分钟和工具调用轮次60次进行限制；达到限制后总结发现和阻碍，判断没有到达终点，进入思考（在当前状态我还能尝试什么）



## 1. 方案选择：不要做“全 subagent 化”，做“主控 + 受限 worker”

### 推荐架构

| 方案 | 适合程度 | 判断 |
|---|---:|---|
| 方案一：LLM 调多个 Pi 实例，让 Pi 成为子 agent | 中等 | 适合并行侦察、日志分析、报告草拟、结果复核；不适合作为核心决策链 |
| 方案二：Pi 做主智能体，skill 控 tool，用 tree/resume 管上下文 | 高 | 更适合做主流程、审计、范围控制、风险控制、可恢复任务 |
| 混合方案：Pi 主控 + 少量受限 Pi worker | 最高 | 工程上最稳，安全边界最清楚，也最容易扩展 |

**不建议把多个 Pi 实例设计成“平权智能体互相协商”。** 自动化渗透里最危险的不是工具不会跑，而是上下文污染、目标范围误判、重复执行、高风险动作失控、证据不可追溯。主智能体必须唯一拥有：授权范围、任务状态、风险策略、最终判断、报告签发权。

社区的 pi-subagent 技能思路也是把子任务委托给隔离的 Pi 子进程；其描述里强调每个子 agent 拿到的是新的上下文窗口，并没有共享状态，这适合并行和故障隔离。([SkillsMP](https://skillsmp.com/skills/espennilsen-pi-extensions-pi-subagent-skills-pi-subagent-skill-md)) Pi 的 `/tree` 模式更像单会话分支管理：当前分支只看到当前路径上下文，不是天然多智能体共享记忆。([StackToHeap](https://stacktoheap.com/blog/2026/02/26/pi-tree-context-window-management/))

## 2. 子智能体是否并行？可以，但不要共享完整会话

应该设计并行，但**共享的不是聊天记录，而是结构化状态**。

建议用一个 **共享黑板 / Task Ledger / Evidence Store**：

```text
                ┌─────────────────────────────┐
                │        Web UI / API          │
                │  scope, auth, risk profile   │
                └──────────────┬──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Pi 主智能体 / Orchestrator │
                    │ planner, policy, report owner │
                    └───────┬───────┬───────┘
                            │       │
          ┌─────────────────▼─┐   ┌─▼─────────────────┐
          │ Policy / Scope Guard│   │ Skill Registry     │
          │ allowlist, rate, gate│   │ methods, tools     │
          └─────────┬──────────┘   └─────────┬─────────┘
                    │                        │
          ┌─────────▼────────────────────────▼─────────┐
          │        Shared State / Blackboard             │
          │ targets, tasks, findings, evidence, logs     │
          │ hypotheses, approvals, summaries, artifacts  │
          └───────┬───────────┬───────────┬────────────┘
                  │           │           │
        ┌─────────▼───┐ ┌─────▼─────┐ ┌──▼────────────┐
        │ Recon Worker │ │ Crawl Worker│ │ Triage Worker │
        │ Pi or script │ │ Pi/tool     │ │ Pi/LLM        │
        └──────────────┘ └───────────┘ └───────────────┘
                  │           │           │
          ┌───────▼───────────▼───────────▼───────┐
          │ Tool Sandbox / Containers / Proxies    │
          │ audit log, rate limit, network policy  │
          └────────────────────────────────────────┘
```

### 共享内容应该是这些

共享：

```json
{
  "target_id": "app-prod-001",
  "scope": ["https://example.com"],
  "out_of_scope": ["payments.example.com"],
  "phase": "authenticated-web-review",
  "evidence": [
    {
      "type": "http_observation",
      "url": "...",
      "method": "GET",
      "status": 200,
      "summary": "Observed reflected parameter in search page"
    }
  ],
  "hypotheses": [
    {
      "kind": "input-validation-risk",
      "confidence": 0.42,
      "needs_validation": true
    }
  ],
  "findings": [],
  "approvals": {
    "active_testing": "approved",
    "destructive_testing": "denied"
  }
}
```

不要共享：

```text
完整聊天历史
模型私有推理过程
未清洗的网页内容
未经验证的工具原始大输出
跨目标的 session/cookie/token
```

原因是：完整会话共享会导致 prompt injection、上下文漂移、token 膨胀、责任不清。黑板模式让每个 worker 只读自己需要的上下文，只写结构化结果，由主智能体统一复核。

## 3. 哪些任务适合子智能体并行

适合并行：

| Worker | 任务 | 工具权限 |
|---|---|---|
| Recon Worker | 资产整理、DNS/证书/公开信息归纳 | 只读、低频率 |
| Crawl Worker | 站点地图、页面聚类、表单识别 | 浏览器/HTTP，限速 |
| Auth Flow Worker | 登录流程、角色路径梳理 | 仅授权测试账号 |
| Static Review Worker | 如果有源码，做代码结构和敏感点索引 | 只读 repo |
| Finding Triage Worker | 归并证据、去重、严重性初判 | 无网络执行权 |
| Report Worker | 把已确认发现写成报告 | 无测试工具权限 |
| Knowledge Worker | 检索 OWASP/CWE/CVE/内部知识 | 只读知识库 |

不适合并行，必须由主控串行审批测试 | 需要明确授权和回滚策略 |
| 高负载扫描 | 容易造成可用性影响 |
| 认证、权限、会话相关验证 | 容易串号或污染状态 |
| 漏洞最终确认 | 需要证据链一致 |
| 生成最终报告 | 需要统一口径 |

## 4. 专家知识怎么注入：skill + 知识库，二者都要

不要二选一。正确做法是：

**skill 放“怎么做”**，**知识库放“知道什么”**。

### Skill 适合放

Pi 官方文档说明 skill 可以包含工作流、安装说明、辅助脚本和参考文档，并且 full `SKILL.md` 是按需加载的 progressive disclosure。([Pi.dev](https://pi.dev/docs/latest/skills)) 所以 skill 应该封装：

```text
skills/
  web-security-review/
    SKILL.md
    references/
      methodology.md
      finding-schema.md
      safety-policy.md
    scripts/
      normalize_http_log.py
      parse_scanner_output.py

  api-security-review/
    SKILL.md
    references/
      endpoint-inventory.md
      authz-checklist.md

  evidence-triage/
    SKILL.md
    scripts/
      dedupe_findings.py
      severity_mapper.py

  report-generation/
    SKILL.md
    templates/
      finding.md
      executive-summary.md
```

每个 skill 里不要只写“你是渗透专家”。要写成可执行规范：

```text
# web-security-review skill

输入：
- target_id
- authorized_scope
- phase
- available_credentials
- risk_level
- previous_evidence

强制规则：
- 每次 tool 调用前检查 scope
- 不执行破坏性动作
- 不绕过 rate limit
- 高风险验证必须请求 approval token
- 所有发现必须附 evidence_id

输出：
- observations[]
- hypotheses[]
- candidate_findings[]
- recommended_next_tasks[]
```

### 知识库适合放

知识库/RAG 放这些：

```text
- OWASP WSTG / ASVS 映射
- CWE / CAPEC 分类
- CVE / NVD 数据
- 厂商安全公告
- 内部历史报告
- 已验证的 payload 风险说明
- 公司自己的漏洞评级标准
- 修复建议模板
- 误报案例库
```

LLM 不应该“自己随便查”。应该通过 **phase-aware retrieval**：

```text
当前阶段 = authz review
当前观察 = 某接口返回对象 ID
检索：
- 访问控制测试方法论
- IDOR/权限绕过历史案例
- 公司严重性评级标准
- 相关修复建议模板
```

最终注入给模型的不是整个知识库，而是：

```json
{
  "retrieved_guidance": [
    {
      "source": "internal-severity-standard",
      "summary": "Cross-tenant data exposure is generally High or Critical depending on data class."
    },
    {
      "source": "owasp-asvs-access-control",
      "summary": "Authorization must be enforced server-side on every object access."
    }
  ]
}
```

## 5. 推荐的完整系统架构

### A. 控制平面

```text
1. Job Manager
   - 创建任务
   - 绑定授权范围
   - 设置风险等级
   - 管理暂停、恢复、重试

2. Pi Orchestrator
   - 选择阶段
   - 调用 skill
   - 分派 worker
   - 汇总证据
   - 生成下一步计划

3. Policy Engine
   - scope allowlist / denylist
   - rate limit
   - credential boundary
   - destructive action gate
   - human approval gate

4. State Manager
   - task graph
   - scan state
   - event log
   - evidence store
   - finding store
```

### B. 执行平面

```text
1. Tool Router
   - 只允许调用注册工具
   - 工具参数 schema 校验
   - 自动加 scope 参数
   - 自动加 timeout / rate limit

2. Sandbox Runner
   - 每个目标/任务独立容器
   - 网络 egress 限制
   - 文件系统隔离
   - secret 注入最小化

3. Browser Runner
   - 认证态浏览器上下文
   - session 隔离
   - HAR / screenshot / DOM 摘要

4. Worker Pool
   - Pi worker，可选
   - 非 LLM worker，也可用普通脚本
   - 所有输出写入黑板
```

### C. 知识平面

```text
1. Skill Registry
   - 方法论
   - 工具适配器
   - 输出 schema
   - 安全规则

2. RAG Knowledge Base
   - 安全知识
   - 历史漏洞
   - 修复建议
   - 严重性标准

3. Finding Ontology
   - CWE
   - OWASP category
   - asset type
   - impact type
   - confidence score
```

### D. 审计与报告平面

```text
1. Event Stream
   - 每次计划、工具调用、结果、审批都有 event_id

2. Evidence Store
   - HTTP 片段
   - 截图
   - 日志摘要
   - 复现条件
   - 不保存敏感明文，必要时脱敏

3. Report Builder
   - executive summary
   - technical details
   - evidence
   - risk rating
   - remediation
   - retest notes
```

## 6. 工作流建议

```text
Phase 0: Intake
- 输入目标、授权证明、测试窗口、账号、禁止事项
- Policy Engine 生成 scope contract

Phase 1: Planning
- Pi 主控选择测试路线
- 加载对应 skill
- 创建 task graph

Phase 2: Passive Discovery
- 可并行
- worker 只读收集信息
- 写入 assets / endpoints / tech stack

Phase 3: Active Mapping
- 受限并行
- 浏览器 crawler、endpoint inventory、认证流整理
- 限速、限范围

Phase 4: Hypothesis Generation
- LLM 根据证据生成候选风险
- 不直接确认漏洞

Phase 5: Safe Validation
- 只允许低影响验证
- 高风险动作进入 approval queue

Phase 6: Triage
- 去重
- 严重性评级
- 证据完整性检查

Phase 7: Reporting
- 生成报告
- 人工复核
- 输出修复建议和 retest checklist
```

## 7. 关于 `tree` / `resume` 的使用方式

Pi 的 `/tree` 思路适合做上下文分支管理；社区文章里提到 session 可以被理解为树，当前上下文只包含当前路径，离开分支时可以生成 branch summary。([StackToHeap](https://stacktoheap.com/blog/2026/02/26/pi-tree-context-window-management/)) 这适合你的方案二，但要注意：`/tree` 只是会话分支，不会回滚文件系统或外部工具状态。([StackToHeap](https://stacktoheap.com/blog/2026/02/26/pi-tree-context-window-management/))

建议这样用：

```text
main branch:
- scope
- policy
- current phase
- approved plan
- confirmed findings

exploration branch:
- 某个假设的分析
- 某个工具输出解释
- 某个误报排查

resume summary:
- 当前目标
- 已确认资产
- 已完成阶段
- 未完成任务
- 待审批动作
- 已确认 findings
```

不要把每次工具输出都塞进主会话。工具输出应该进 Evidence Store，主会话只保留摘要和 evidence_id。

## 8. 最终推荐实现路线

### MVP 版本

先不要做复杂 subagent。先做：

```text
Pi 主控
+ Skill Registry
+ Tool Router
+ Scope Guard
+ SQLite/Postgres 状态库
+ Evidence Store
+ Report Generator
```

MVP 的关键能力：

```text
- 目标范围强校验
- 阶段化 workflow
- 工具调用白名单
- 所有工具输出结构化
- finding 去重和证据绑定
- resume 能恢复任务
```

### V2 再加 worker

加 3 类 worker 就够：

```text
1. Recon Worker
2. Crawl / Inventory Worker
3. Triage / Report Worker
```

每个 worker 必须满足：

```text
- 无全局决策权
- 无最终漏洞确认权
- 无越权工具权限
- 只读黑板的一部分
- 只写结构化 artifact
- 所有动作可审计
```
## 9. 一句话设计原则

**让 Pi 主智能体负责“判断和编排”，让 skill 负责“方法和工具约束”，让知识库负责“专家知识检索”，让 worker 只负责“可隔离的子任务”，让黑板负责“共享状态”，让 Policy Engine 决定“什么绝不能做”。**

所以你的最终方案应该是：

```text
Pi Orchestrator
  -> loads security skills
  -> queries knowledge base
  -> creates task graph
  -> dispatches limited workers
  -> enforces scope/risk policy
  -> stores evidence
  -> produces verified report
```
