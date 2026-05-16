# 钓鱼邮件检测工作流集成

## Goal

将 `/opt/mail-gateway` 的钓鱼邮件 AI 检测能力彻底融入 secbot 工作流模块：
- rspamd Lua 插件直接触发 secbot workflow run（同步等待 LLM 结论决定是否加分）
- 下线 `ai_detector.py`（FastAPI@5001）及其 SQLite 历史存储
- 将"钓鱼邮件检测"工作流固化为首个内置模板，通过 `GET /api/workflows/_templates` 暴露给 WebUI
- 保留 postfix + rspamd + Redis + Ollama 的常驻部分不动

## Requirements

### R1 — 核心串联工作流（MVP）
实现一条 3-step 工作流：
- **step1 (`kind=script`, python)**：解析 rspamd POST 来的邮件特征 + Redis 7 天去重（按 `content_hash` = sha256(sender|subject|body)）
- **step2 (`kind=llm`, responseFormat=json)**：基于 step1 产出的 desensitized features 调 secbot 全局 provider，输出 `{is_phishing, confidence, risk_level, reason, risk_factors, suggested_action}`；`condition` 跳过条件：命中缓存 OR `rspamd_score` 越出 `[4.0, 10.0]`
- **step3 (`kind=script`, python)**：汇总 step1/step2 结果、计算 `add_score`、回写 Redis、stdout 打印**扁平 JSON**（Lua 插件从此处读取决策）

### R2 — Lua 插件改造
`config/rspamd/my_ai_check.lua` 的 `http_callback` 目标从 `http://127.0.0.1:5001/analyze` 改为 `http://<secbot>/api/workflows/<wf_id>/run`；body 结构保持（加上 `rspamd_score`），响应解析从 `stepResults.step3.output.stdout` 读 JSON，取 `add_score`。

### R3 — 模板注册
- 新建 `secbot/workflow/templates.py`，以 dataclass/常量声明钓鱼邮件模板（符合 `WorkflowTemplate` 前端契约：`{id, name, description, tags, workflow:draft}`）
- 改造 `secbot/api/workflow_routes.py::handle_templates` 从 `templates.py` 读取并返回
- Tags 遵循现有风格（参考 `asset_discovery/port_scan/vuln_scan/weak_password/report`），建议 `["email", "phishing", "llm"]`

### R4 — `ai_detector.py` 下线（保留数据库）
- 停用 systemd 单元 `mail-ai-detector` 与 FastAPI 服务（端口 5001）
- 归档 `/opt/mail-gateway/ai_detector/` 但不删（保留 30 天回滚窗口）
- `my_ai_check.lua` 改造验证后才能下线 5001 服务
- **数据库（SQLite `detection_results` 表）保留**：由 step3 的 python 脚本接管写入逻辑（沿用原 schema：content_hash / subject / sender / ai_is_phishing / ai_confidence / ai_reason / action / created_at / processed_time_ms），DB 路径保持 `/opt/mail-gateway/data/sqlite/detection_results.db`
- 同时 secbot `runs.jsonl` 记录 workflow run 维度的步骤痕迹（双写：业务库做"邮件维度"分析，runs.jsonl 做"workflow 维度"诊断）

### R6 — /history /stats 移植到大屏分析（两层结构：概要卡 → 详情页）
- **数据库选型**：**继续使用 SQLite**（`/opt/mail-gateway/data/sqlite/detection_results.db`，沿用原 schema 不迁移），由 step3 接管写入
- **前端两层结构**（见 [`prototype.html`](file:///home/administrator/VAPT3/.trellis/tasks/05-13-phishing-email-workflow/prototype.html)）：
  - **L1 主屏概要卡**：在 `webui/src/pages/DashboardPage.tsx` 现有大屏上新增**单个**"钓鱼邮件检测"概要卡（一行宽度），含主指标（今日识别钓鱼数）+ 7 天 sparkline + 3 个小指标（今日总数/缓存命中率/平均耗时）+ 链路状态徽章；**整卡可点击进入详情页**
  - **L2 详情页**：新路由（建议 `/dashboard/phishing` 或 React 内部 view 切换），包含 KPI×4 + 检测趋势复合图 + 风险等级饼图 + 高危发件人 Top 8 + 检测明细表（搜索/筛选/分页）+ 链路健康卡（postfix/rspamd/workflow/LLM provider/redis/SQLite 6 项）
- **新增 secbot REST 端点**：
  - `GET /api/dashboard/phishing/summary` — **L1 概要卡专用**：返回 today_phishing / today_total / cache_hit_rate / avg_duration_ms / spark_7d（数组）+ link_status
  - `GET /api/dashboard/phishing/stats` — L2 KPI（替代原 `:5001/stats`）
  - `GET /api/dashboard/phishing/history?limit=&search=&filter=` — L2 明细表（替代原 `:5001/history`）
  - `GET /api/dashboard/phishing/trend?days=7|30|90` — L2 检测趋势（钓鱼/可疑/正常 + 钓鱼率）
  - `GET /api/dashboard/phishing/top-senders?limit=8` — L2 高危发件人 Top
  - `GET /api/dashboard/phishing/health` — L2 链路健康聚合（postfix/rspamd/workflow/provider/redis/sqlite）
- 所有端点查询 `detection_results` 表，无需新建表

### R5 — 容错策略
- LLM 不可用 / workflow error → Lua 解析不到 `add_score` 字段时**默认 add_score=0**（邮件放行，仅 secbot 告警）
- step3 必须保证"无论前面 step 发生什么都输出有效 JSON"（通过 `on_error=continue` 配合 step3 的防御性读取）

## Acceptance Criteria

- [ ] `POST /api/workflows/<wf_id>/run` body=`{sender, subject, body, urls, recipient, rspamd_score}` 能同步返回含 `add_score` 的 JSON
- [ ] 同一邮件二次投递命中 Redis 缓存，step2 被 skip，总耗时 < 200ms
- [ ] LLM 正常时，钓鱼邮件样本 `/opt/mail-gateway/email/*` 返回 `is_phishing=true` 数符合原 `ai_detector.py` 基线
- [ ] `GET /api/workflows/_templates` 返回含"钓鱼邮件检测"条目；WebUI `TemplateGallery` 能渲染并"Use"
- [ ] Lua 插件替换后，端到端走一封钓鱼邮件，SMTP 层 score 正确加分
- [ ] LLM provider 故意关闭时，邮件不被误拦，secbot 告警可见

## Technical Approach

### 数据流
```
postfix → rspamd (score ∈ [4,10])
         → my_ai_check.lua
             → POST /api/workflows/{wf_id}/run (同步)
                 → step1 script: Redis dedup + desensitize
                 → step2 llm:   Ollama via secbot provider (JSON mode)
                 → step3 script: aggregate + add_score + Redis write
             ← response.stepResults.step3.output.stdout (扁平 JSON)
         ← task:insert_result("AI_PHISHING_DETECT", add_score, ...)
→ postfix 按最终 score 决定投递/隔离/拒收
```

### WorkflowInputs 声明
```
sender (string, required)
subject (string, required)
body (string, required)
urls (string, default="[]")   # JSON string
recipient (string)
rspamd_score (string, required)  # 以字符串传入保留精度
```

### step3 stdout 契约
```json
{"add_score": 5.0, "is_phishing": true, "confidence": 0.92, "reason": "...", "suggested_action": "拒绝", "from_cache": false}
```

### Redis key 规则
- `ai:result:<content_hash>` TTL 7 天（与原 `CACHE_EXPIRE_SECONDS` 一致）
- Value: 完整 step3 输出 JSON

## Decision (ADR-lite)

**Context**：钓鱼邮件检测天然是"常驻事件驱动流"，而 secbot workflow 是"一次触发串联"的短生命周期模型，范式存在冲突。

**Decision**：采用"**每封邮件 = 一次 workflow run**"的 Per-Mail 触发模式，将常驻监听职责留在 postfix+rspamd 系统服务，workflow 承担"单次邮件分析"的串联逻辑。rspamd 同步调用 workflow 并等待结果做拦截决策。

**Consequences**：
- ✅ 完全契合 workflow 串联模型，WebUI 可按 run 查看每封邮件的步骤级痕迹
- ✅ 统一 LLM 接入（换 provider 不用改 `ai_detector.py`）
- ⚠️ 邮件量大时 `runs.jsonl` 可能膨胀 —— 未来需要 run 归档/清理策略（out of scope）
- ⚠️ Lua 插件→workflow 同步调用链加长了 rspamd 超时敏感度

## Out of Scope

- SQLite `detection_results.db` 的历史数据迁移到 runs.jsonl（保留只读）
- `/history` `/stats` `/config` 接口的等价替代（WebUI 已能看 run 列表，短期够用）
- 多接收域 / 多租户支持（Lua 的 `internal_domains` 仍保持硬编码）
- 邮件附件扫描、SPF/DKIM/DMARC 独立信号进 condition
- `_templates` 首批除了钓鱼邮件外再多几个模板
- Run 归档/清理策略、runs.jsonl 膨胀治理

## Technical Notes

- **ScriptExecutor 60s 超时上限** — step1/step3 都要严格控制在内，重 I/O（Ollama 调用）由 step2 `kind=llm` 承担
- **Script 步骤输出结构**：`{exit_code, stdout, stderr}`（见 `secbot/workflow/executors/script.py`），Lua 要读 `stepResults.step3.output.stdout` 再 `json.decode`
- **模板契约**：`WorkflowTemplate` 见 [`workflow-client.ts#L163-170`](file:///home/administrator/VAPT3/webui/src/lib/workflow-client.ts#L163-L170)
- **现有 runner**：[`runner.py`](file:///home/administrator/VAPT3/secbot/workflow/runner.py)；同步执行、每步落盘
- **Lua 插件**：[`my_ai_check.lua`](file:///opt/mail-gateway/config/rspamd/my_ai_check.lua) `http_callback` 部分
- **原 prompt**：`ai_detector.py::build_prompt` — 可直接照搬到 step2 的 `userPrompt` 模板字符串里
