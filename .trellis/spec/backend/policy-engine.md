# Policy Engine — 单点工具调用安全闸门

> **Status**: DRAFT (not implemented)
> **Replaces / extends**: `.trellis/spec/backend/high-risk-confirmation.md`
> **Implements**: PRD AC3 + Pi Agent.md §1 / §5 「Policy Engine 决定什么绝不能做」
> **Code PR**: PR2 (PolicyEngine + Tool Router)
> **Open issues**:
> - rate-limit 是否每 worker 独立 vs 全局共享配额？（当前提案：worker 独立）

---

## 1. Goal

把现有分散在多处的安全控制合并为**单点 PolicyEngine**：每个工具调用前都通过
`policy.check(action, args, ctx) → Decision`，统一处理：

- **scope allow/deny**：目标在 ScopeContract 内？
- **destructive gate**：`risk_level=critical` 是否需要 human confirm？（现
  HighRiskGate 行为不变）
- **SSRF**：URL 解析后命中私网/cloud metadata？（现 `validate_url_target`）
- **workspace restrict**：文件路径越出 workspace？（现 `restrict_to_workspace`）
- **rate limit**：单 worker / 单 endpoint 每分钟调用上限
- **credential boundary**：跨 target 的 session/cookie/token 不串号
- **approval gate**：destructive 已 approved 后会话内缓存（现 HighRiskGate 行为）
- **budget gate**：转发到 BudgetEnforcer（见 `budget-enforcer.md`）

Pi Agent.md 原话：
> 让 Policy Engine 决定「什么绝不能做」。

## 2. Non-Goals

- 不做 RBAC（无多用户角色）
- 不实现 OPA/Rego 等外置策略 DSL；策略以 Python 描述符 + 配置 yaml 表达
- 不替换 SSRF 实现（继续用 `secbot/security/network.py`，PolicyEngine 调用之）
- 不引入 sidecar / 进程外 daemon

## 3. Architecture

```
        ┌──────────────────────────────────┐
        │  Tool Router (ToolRegistry.execute) │
        └──────────────┬───────────────────┘
                       │  pre-execute
                       ▼
        ┌──────────────────────────────────┐
        │       PolicyEngine.check()        │
        │  ┌─────────────────────────────┐  │
        │  │ ScopeRule                   │  │  ← ScopeContract
        │  │ SSRFRule                    │  │  ← security/network.py
        │  │ WorkspaceRule               │  │  ← workspace path policy
        │  │ DestructiveRule (HighRisk)  │  │  ← skill metadata risk_level
        │  │ RateLimitRule               │  │  ← per worker/endpoint
        │  │ CredentialBoundaryRule      │  │  ← per target session
        │  │ BudgetRule                  │  │  ← BudgetEnforcer
        │  └─────────────────────────────┘  │
        └──────────────┬───────────────────┘
                       │  Decision
                       ▼
        ┌──────────────────────────────────┐
        │  allow | need_approval | deny     │
        └──────────────────────────────────┘
```

### 3.1 `PolicyDecision` Dataclass

```python
@dataclass(frozen=True, slots=True)
class PolicyDecision:
    verdict: Literal["allow", "need_approval", "deny"]
    rule: str | None = None         # 触发的规则名（deny / need_approval 时必填）
    reason: str | None = None       # LLM-friendly 解释
    suggest: str | None = None      # 提示 LLM 该怎么修复（如 "consider preset=triage"）
    approval_payload: Mapping[str, Any] | None = None  # need_approval 时透传给 confirm UI
```

ToolRouter 处理：

| Verdict | 行为 |
|---|---|
| `allow` | 正常执行 |
| `need_approval` | 调 `ctx.confirm(approval_payload)`；approve 后再执行；deny/timeout 返回结构化 error |
| `deny` | 不执行，返回 `{"error": "policy_denied", "rule": ..., "reason": ..., "suggest": ...}` 给 LLM |

### 3.2 `Action` Taxonomy

```python
Action = Literal[
    "tool.invoke",        # 通用工具调用
    "skill.invoke",       # SkillTool（subset of tool.invoke）
    "worker.spawn",       # create_worker
    "blackboard.write",   # 含 kind 限制
    "blackboard.read",    # read_blackboard / read_blackboard_full
    "exec.shell",         # ExecTool（默认禁用）
    "http.fetch",         # CurlTool / WebFetch
    "fs.read",            # ReadFileTool / ListDirTool / GlobTool / GrepTool
    "fs.write",           # WriteFileTool / EditFileTool
    "fs.delete",          # （新工具引入时）
    "approval.request",   # request_approval
    "report.publish",     # 报告发布（report-html）
    "message",            # 直接通知用户
]
```

### 3.3 Rules

#### ScopeRule

```python
class ScopeRule(Rule):
    def applies_to(self, action: Action) -> bool:
        return action in {"skill.invoke", "worker.spawn", "http.fetch"}

    def check(self, args, ctx) -> PolicyDecision:
        target = self._extract_target(action, args)  # URL/host/IP
        if not ctx.scope.contains(target):
            return PolicyDecision("deny", rule="scope",
                reason=f"target {target} is not in scope",
                suggest="Pi: stop and notify user; do not retry.")
        if ctx.scope.is_explicitly_denied(target):
            return PolicyDecision("deny", rule="scope_denied",
                reason=f"target {target} is in out_of_scope list",
                suggest=None)
        return PolicyDecision("allow")
```

`ScopeContract`（已在 PRD D2 / `pi-orchestrator.md` §5 提及）：

```python
@dataclass(frozen=True, slots=True)
class ScopeContract:
    in_scope: tuple[ScopeAtom, ...]    # host / cidr / url-prefix / domain-wildcard
    out_of_scope: tuple[ScopeAtom, ...]
    auth_window_start: datetime
    auth_window_end: datetime
    forbidden_actions: frozenset[Action]
    risk_profile: Literal["passive", "active", "intrusive"]
```

`contains` 实现需支持：
- IP / CIDR
- 域名（含通配 `*.example.com`）
- URL 前缀（含路径）
- 时间窗校验（now ∈ [auth_window_start, auth_window_end]）

`http.fetch` / curl 命令可能包含多个网络目标；ScopeRule MUST scope-check
**every** extracted URL/host target, not only the first one. For URL-prefix atoms,
matching MUST parse URL components (scheme, host, optional port, path boundary)
rather than raw string `startswith`, so `https://app.example.test.evil.net` does
not match `https://app.example.test` and `/administer` does not match `/admin`.

#### SSRFRule

```python
class SSRFRule(Rule):
    applies_to = {"http.fetch", "skill.invoke"}  # skill 涉及 URL 入参时

    def check(self, args, ctx):
        url = args.get("url") or args.get("endpoint_url")
        if not url:
            return PolicyDecision("allow")
        ok, msg = validate_url_target(url)   # 现 security/network.py
        if not ok:
            return PolicyDecision("deny", rule="ssrf", reason=msg,
                suggest="Pi: target is internal; require user to whitelist via configure_ssrf_whitelist")
        return PolicyDecision("allow")
```

For curl-shaped `http.fetch` commands, SSRFRule also rejects command forms that
can change or bypass the validated target before execution:

- shell control syntax such as `;`, `&&`, pipes, redirects, backticks, or `$()`
- curl network-routing overrides such as `--resolve`, `--connect-to`, proxies,
  and `--unix-socket`
- curl local file read/write/upload options such as `-o`, `--output`,
  `--upload-file`, `--data-binary @file`, `--form name=@file`, `--cookie`
  file paths, TLS certificate/key file options, `--config`, `--netrc-file`,
  and non-HTTP URL schemes such as `file://`

#### WorkspaceRule

```python
class WorkspaceRule(Rule):
    applies_to = {"fs.read", "fs.write", "fs.delete"}

    def check(self, args, ctx):
        if not ctx.workspace_strict:
            return PolicyDecision("allow")
        path = Path(args["path"])
        if not path.is_relative_to(ctx.workspace):
            return PolicyDecision("deny", rule="workspace",
                reason=f"path {path} escapes workspace",
                suggest="restrict to ${WORKSPACE} subtree")
        return PolicyDecision("allow")
```

#### DestructiveRule（**合并** HighRiskGate）

```python
class DestructiveRule(Rule):
    applies_to = {"skill.invoke", "exec.shell"}

    def check(self, args, ctx):
        meta = ctx.skill_metadata  # injected by ToolRouter from SkillTool
        if meta is None or not meta.is_critical():
            return PolicyDecision("allow")
        if meta.name in ctx.approved_skills:  # session cache
            return PolicyDecision("allow")
        payload = build_confirmation_payload(meta, args, ctx.scan_id)  # 复用现有
        return PolicyDecision("need_approval", rule="destructive",
            reason=f"{meta.name} is risk_level=critical",
            approval_payload=payload)
```

`build_confirmation_payload` 与现 `agents/high_risk.py::build_confirmation_payload`
**byte-identical**（迁移不破坏 WebUI 弹窗）。

#### RateLimitRule

```python
class RateLimitRule(Rule):
    applies_to = {"skill.invoke", "http.fetch"}

    def check(self, args, ctx):
        bucket = self._bucket_for(ctx)  # per worker + per endpoint
        if bucket.exceeded():
            return PolicyDecision("deny", rule="rate_limit",
                reason=f"{bucket.name}: {bucket.calls}/min exceeds {bucket.limit}",
                suggest="Pi: sleep or hand off to checkpoint")
        bucket.consume()
        return PolicyDecision("allow")
```

默认配额（可在 config 覆盖）：

```yaml
policy:
  rate_limit:
    worker_default: 30/min          # 30 tool calls per minute per worker
    endpoint_default: 10/min        # per (endpoint_url, endpoint_param)
    skill_overrides:
      hydra-bruteforce: 1/min       # 极保守
      fscan-vuln-scan: 5/min
      report-html: unlimited
```

Bucket 实现：sliding window 60s + 内存计数；重启重置（持久化不必要）。

#### CredentialBoundaryRule

```python
class CredentialBoundaryRule(Rule):
    applies_to = {"http.fetch", "skill.invoke"}

    def check(self, args, ctx):
        target_host = self._extract_host(args)
        creds = args.get("cookies") or args.get("auth_header")
        if not creds:
            return PolicyDecision("allow")
        # ctx.credential_zones: dict[host, frozenset[credential_id]]
        cred_id = self._fingerprint(creds)
        owners = ctx.credential_zones.get(target_host, frozenset())
        if cred_id not in owners and ctx.credential_zones:
            return PolicyDecision("deny", rule="credential_boundary",
                reason=f"credential {cred_id[:8]} not authorised for {target_host}",
                suggest="Pi: do not reuse session across targets")
        return PolicyDecision("allow")
```

`credential_zones` 在 ScopeContract 派生时构造：每个 in_scope target 关联一组允
许使用的 credential id（如 `target=app.example.com` ↔ `creds=session_xyz`）。

#### BudgetRule

代理调用 `BudgetEnforcer.check(ctx)`（见 `budget-enforcer.md` §4.3）。PR3
启用 reflect-then-checkpoint 后，`EXCEEDED` 状态只允许 Pi 完成 checkpoint 三件套：
`blackboard.write(kind="summary")`、`blackboard.write(kind="phase_transition")`、
`blackboard.read` 与 `message`。

```python
class BudgetRule(Rule):
    applies_to = "*"

    def check(self, args, ctx):
        status = ctx.budget.status()  # HEALTHY | LOW | EXCEEDED
        if status == "EXCEEDED":
            if (ctx.action, args.get("kind")) in {
                ("blackboard.write", "summary"),
                ("blackboard.write", "phase_transition"),
            }:
                return PolicyDecision("allow")
            if ctx.action in {"blackboard.read", "message"}:
                return PolicyDecision("allow")
            return PolicyDecision("deny", rule="budget",
                reason="budget exhausted; write summary/phase_transition first",
                suggest="see [BUDGET_EXCEEDED] instructions")
        return PolicyDecision("allow")
```

### 3.4 Rule 顺序

PolicyEngine 串行执行，**第一个非 allow 即返回**。顺序：

```
ScopeRule → SSRFRule → WorkspaceRule → CredentialBoundaryRule →
CallerKindRule → BudgetRule → RateLimitRule → DestructiveRule
```

理由：先确认目标合法（scope / SSRF / workspace / credential），再确认 caller
是否有权做这类动作；然后执行 BudgetRule，使 `EXCEEDED` 时不会消耗 rate-limit
bucket，也不会先弹 destructive approval。预算健康时再进入资源类（rate）和人工审批
（destructive）。

这样目标/凭据边界优先给出最具体的越权原因；worker 永远不能执行的动作（如
`worker.spawn`、`report.publish`、`blackboard.write(kind="finding")`）也不会消耗
rate-limit bucket。

## 4. Tool Router 集成

### 4.1 现 `ToolRegistry.execute_tool` 改造

```python
async def execute_tool(
    self,
    name: str,
    arguments: Mapping[str, Any],
    ctx: ToolExecutionContext,
) -> str:
    tool = self._tools[name]
    action = self._action_for(tool)  # 推断 Action taxonomy
    decision = await self._policy.check(action, arguments, ctx)

    if decision.verdict == "deny":
        return json.dumps({
            "error": "policy_denied",
            "rule": decision.rule,
            "reason": decision.reason,
            "suggest": decision.suggest,
        })

    if decision.verdict == "need_approval":
        approved = await ctx.confirm(decision.approval_payload)
        if not approved:
            return json.dumps({
                "error": "user_denied",
                "rule": decision.rule,
                "reason": decision.reason or "user denied confirmation",
            })

    return await tool.execute(**arguments)
```

### 4.2 Worker-level 限制（new）

`PolicyEngine` 在构造时按 caller_kind 分裂行为：

| Caller | 额外限制 |
|---|---|
| `pi` | 全权（subject to scope/destructive/budget） |
| `worker` | 禁止 `blackboard.write(kind="finding"\|"phase_transition"\|"approval")`；禁止 `worker.spawn`；禁止 `report.publish` |
| `system` | 内部调用（如 BudgetEnforcer 注入消息）；绕过 destructive，但仍受 scope |

实现：

```python
class CallerKindRule(Rule):
    applies_to = "*"
    _BANNED = {
        "worker": {
            ("blackboard.write", "finding"),
            ("blackboard.write", "phase_transition"),
            ("blackboard.write", "approval"),
            ("worker.spawn", None),
            ("report.publish", None),
        }
    }

    def check(self, args, ctx):
        banned = self._BANNED.get(ctx.caller_kind, set())
        sub = args.get("kind")  # for blackboard.write
        if (ctx.action, sub) in banned or (ctx.action, None) in banned:
            return PolicyDecision("deny", rule="caller_kind",
                reason=f"{ctx.caller_kind} cannot {ctx.action}({sub})",
                suggest="Pi: handle this yourself")
        return PolicyDecision("allow")
```

### 4.3 Audit

所有 deny + need_approval 进入 `event_log`（见 `event-stream.md` §2.2）：

```json
{
  "type": "policy_decision",
  "payload": {
    "action": "skill.invoke",
    "rule": "scope",
    "verdict": "deny",
    "tool": "qscan-port-scan",
    "args_hash": "sha256:...",  // 不存原始 args，仅 hash
    "caller_kind": "worker",
    "worker_id": "...",
    "reason": "..."
  }
}
```

## 5. Config

```python
# secbot/config/schema.py
class PolicyConfig(BaseModel):
    enabled: bool = True
    ssrf_whitelist: list[str] = []   # CIDRs allowed to bypass SSRFRule
    rate_limit: RateLimitConfig = RateLimitConfig()
    workspace_strict: bool = True
    destructive_timeout_sec: int = 120   # 旧 HighRiskGate.timeout_sec
```

## 6. Error / Edge Cases

| Case | Behavior |
|---|---|
| `ctx.scope is None`（尚未 Intake 完成） | ScopeRule `allow`（degraded mode；写 warn log） |
| `ctx.budget is None`（BudgetEnforcer 未初始化） | BudgetRule `allow` |
| ApprovalPayload 无 `confirm` callback | `need_approval` 自动转 `deny`（fail-safe） |
| Rule 抛异常 | 视为 `deny`，rule=`<rule_class>_error`；写 event_log |
| 单 turn 内同一 tool 调用 100 次（疯狂 LLM） | RateLimitRule 阻止；BudgetEnforcer 兜底 |
| Approve 后 5 秒内同样调用复发 | DestructiveRule 缓存命中，直接 allow |
| Approve 缓存跨 worker 共享？ | 否；缓存 keyed by `(scan_id, worker_id?, skill_name)`。Pi 是单实例所以共享；worker 之间独立 |

## 7. Migration & Compatibility

### 7.1 与现 HighRiskGate 兼容

PR2 保留 `secbot/agents/high_risk.py`，但内部全部 delegate 到 PolicyEngine：

```python
class HighRiskGate:
    def __init__(self, policy: PolicyEngine, ...): ...

    async def guard(self, meta, args, ctx, run):
        ctx_p = build_policy_ctx(ctx, skill_metadata=meta)
        decision = await self._policy.check("skill.invoke", args, ctx_p)
        if decision.verdict == "deny": return SkillResult(...)
        if decision.verdict == "need_approval":
            ok = await ctx.confirm(decision.approval_payload)
            if not ok: return SkillResult(...)
        return await run(args, ctx)
```

`AuditLogger` 在 PR2 中继续存在；新 audit 双写到 `event_log`。V2 删除旧
HighRiskGate 模块。

### 7.2 与现 SSRF 兼容

`secbot/security/network.py` 不动；PolicyEngine `SSRFRule` 调用之。
`configure_ssrf_whitelist` 由 PolicyConfig.ssrf_whitelist 触发。

### 7.3 与现 `restrict_to_workspace` 兼容

`AgentLoop` / `SubagentManager` 构造时把 `restrict_to_workspace` 透传到
`PolicyConfig.workspace_strict`，行为不变。

## 8. Test Plan

### Unit (each rule)

- `test_scope_rule_in_scope_allows`
- `test_scope_rule_out_of_scope_denies`
- `test_scope_rule_expired_window_denies`
- `test_ssrf_rule_private_ip_denies`
- `test_workspace_rule_escape_denies`
- `test_destructive_rule_critical_needs_approval`
- `test_destructive_rule_cached_after_approve`
- `test_rate_limit_rule_exceeds_denies`
- `test_credential_boundary_cross_target_denies`
- `test_budget_rule_exceeded_denies`
- `test_caller_kind_worker_cannot_write_finding`

### Integration

- `test_tool_router_deny_returns_structured_error`
- `test_tool_router_need_approval_blocks_on_confirm`
- `test_tool_router_audit_emits_event_log`
- `test_multiple_rules_first_deny_wins`

### Compat

- `test_legacy_high_risk_gate_delegates_to_policy`
- `test_existing_ssrf_tests_pass_with_new_router`（regression）

## 9. Implementation Anchors (PR2)

- `secbot/policy/__init__.py`
- `secbot/policy/engine.py::PolicyEngine`
- `secbot/policy/rules/{scope,ssrf,workspace,destructive,rate_limit,credential,budget,caller_kind}.py`
- `secbot/policy/decision.py::PolicyDecision`
- `secbot/policy/scope.py::ScopeContract` (含 `from_intake` 构造器)
- `secbot/agent/tools/registry.py::ToolRegistry.execute_tool` (改造)
- `secbot/agents/high_risk.py` (改造为 delegating shim)
- `secbot/config/schema.py::PolicyConfig` (新)

## 10. References

- Pi Agent.md §1（Policy Engine 段落）+ §5（Policy Engine 详细职责） + §9
- 旧 spec: `high-risk-confirmation.md`（仍生效；PR2 标注 SUPERSEDED-BY）
- 关联 spec: `pi-orchestrator.md` §3.2 / `budget-enforcer.md` /
  `event-stream.md` §2.2
