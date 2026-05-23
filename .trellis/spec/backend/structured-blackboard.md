# Structured Blackboard + Evidence Store

> **Status**: DRAFT (not implemented)
> **Replaces / extends**: `.trellis/spec/backend/blackboard-registry.md`
> **Implements**: PRD AC2 + D4
> **Code PR**: PR1 (StructuredBlackboard + EvidenceStore)
> **Open issues**:
> - Evidence 大对象（screenshot/HAR）二进制是否进 SQLite 还是 fs + ref？

---

## 1. Goal

把现有 `secbot/agent/blackboard.py::Blackboard`（**纯文本 + 4 个 tag**）扩展为
**typed kinds 结构化共享状态**，并新建独立 `EvidenceStore` 承接「raw 证据 + 脱敏
+ 多对多关联到 finding」。

直接对应 Pi Agent.md §2「共享黑板 / Task Ledger / Evidence Store」表：

```json
{
  "scope": {...},
  "phase": "...",
  "evidence": [...],
  "hypotheses": [...],
  "findings": [...],
  "approvals": {...}
}
```

## 2. Non-Goals

- 不引入新 IPC（继续 in-process + per-chat 隔离 + 现有 WebSocket 广播）
- 不实现 KB / RAG（占位接口在 `pi-orchestrator.md` §3.6 提及，留给 V2）
- 不动 AssetFeed（保留作为「**实时增量**」边车，黑板是「**精炼共享**」）
- 不强制旧 `text` 写入立即下线（保留兼容层 ≥ 1 个 milestone）

## 3. Entry Kinds — Typed Schema

旧 `BlackboardEntry(id, agent_name, text, timestamp, kind)` 扩展为：

```python
@dataclass(frozen=True, slots=True)
class BlackboardEntry:
    id: str                      # 8-char uuid, 不变
    agent_name: str
    timestamp: float
    kind: Kind                   # 新：必填，see §3.1
    payload: Mapping[str, Any]   # 新：typed by kind
    text: str | None = None      # 旧 freeform 兼容字段；新写入禁止用，读取兼容
```

### 3.1 Kind 枚举

| Kind | 用途 | Payload 必填字段 | Payload 可选字段 |
|---|---|---|---|
| `scope` | ScopeContract 快照（写一次，phase=Intake 时） | `in_scope: list[str]`, `out_of_scope: list[str]` | `auth_window`, `forbidden_actions`, `risk_profile` |
| `phase_transition` | 阶段切换 | `from: Phase`, `to: Phase`, `reason: str` | — |
| `finding` | 已确认漏洞 | `title`, `severity`, `cwe`, `owasp_category`, `asset_ref`, `evidence_ids: list[str]` | `confidence`, `remediation_ref`, `chain_of: list[finding_id]` |
| `hypothesis` | 待验证假设 | `title`, `kind` (`input-validation` / `authz` / `ssrf` / `business-logic` / `other`), `confidence: float` | `needs_skills: list[str]`, `evidence_ids` |
| `evidence_ref` | 指向 EvidenceStore 的引用 | `evidence_id`, `source_tool`, `summary: str` (≤ 200 chars) | — |
| `approval` | request/approve/deny 记录 | `action`, `requested_at`, `state` (`pending`/`approved`/`denied`), `decided_at` | `justification`, `denial_reason` |
| `milestone` | 旧兼容 + 阶段总结 | `summary: str` | `phase` |
| `blocker` | 阻塞项 | `summary: str` | `kind` (`scope`/`creds`/`tool_missing`/`other`), `requires_human: bool` |
| `progress` | 实时进度（用 AssetFeed 优先；这是退化兜底） | `summary: str` | `done`, `total` |
| `summary` | budget reflect 时写的三件套 | `kind` (`findings_summary`/`blockers_summary`/`next_steps`), `items: list[str]` | — |
| `legacy_text` | 旧 `text+tag` 写法迁移占位 | `text: str` | — |

> **强约束**：未列入此表的 kind 一律拒写（返回 `error: unknown kind`）。
> 旧 `text` 入参在 PR1 内仍支持 —— `Blackboard.write_text(agent, text)` 调用
> `_extract_kind` 推断 tag 后映射为对应 typed kind（找不到时记 `legacy_text`）。

### 3.2 Phase 枚举

```
Intake | Passive Discovery | Active Mapping | Hypothesis Generation |
Safe Validation | Triage | Reporting | Checkpoint
```

（与 `pi-orchestrator.md` §3.4 严格同步）

## 4. API Surface

### 4.1 `Blackboard` 新方法

```python
class Blackboard:
    # ---- 新接口 ----
    async def write(
        self,
        agent_name: str,
        kind: Kind,
        payload: Mapping[str, Any],
    ) -> BlackboardEntry: ...

    async def read_by_kind(
        self,
        kinds: Iterable[Kind],
        *,
        since: float | None = None,
        scope_filter: ScopeFilter | None = None,
    ) -> list[BlackboardEntry]: ...

    async def snapshot(self) -> BlackboardSnapshot: ...
    """Return aggregated view: latest scope, latest phase_transition,
    all findings, open hypotheses, pending approvals, last 3 blockers."""

    # ---- 旧兼容（保留 ≥ 1 milestone）----
    async def write_text(self, agent_name: str, text: str) -> BlackboardEntry:
        """Parses [kind] tag, maps to typed write. Logs deprecation warn."""

    async def read_all(self) -> list[BlackboardEntry]:
        """Returns all entries; payload preserved. text field populated
        when entry.kind == legacy_text."""
```

### 4.2 `BlackboardSnapshot`

Pi prompt 实际注入的视图（节省 token）：

```python
@dataclass(frozen=True, slots=True)
class BlackboardSnapshot:
    scope: ScopeContract | None
    current_phase: Phase
    findings: list[FindingSummary]    # ≤ 50 条；按 severity 排序
    open_hypotheses: list[HypothesisSummary]  # ≤ 20 条
    pending_approvals: list[ApprovalSummary]
    recent_blockers: list[BlockerSummary]     # ≤ 5 条
    recent_milestones: list[MilestoneSummary] # ≤ 5 条
```

序列化为 markdown 段落注入 Pi prompt（不传 entry.id / timestamp 节省 token）。

### 4.3 LLM Tool Surface

| 工具 | 接口 | 出现在 |
|---|---|---|
| `read_blackboard` | 旧名保留；返回 markdown-formatted snapshot | Pi + worker |
| `write_blackboard` | 新签名 `(kind, payload)`；旧 `(text)` 兼容 | Pi + worker (subject to scope_filter) |
| `read_blackboard_full` | 返回所有 entries（按 kind 过滤）| Pi only |

Worker 写黑板时 PolicyEngine 限制：

- worker 不能直接写 `finding`（只能写 `hypothesis` / `candidate_finding`，由 Pi
  promote）
- worker 不能写 `phase_transition`
- worker 不能写 `approval`

详见 `policy-engine.md` §4.2。

## 5. EvidenceStore — 新增模块

### 5.1 Schema

```sql
CREATE TABLE evidence_records (
  id              TEXT PRIMARY KEY,        -- 12-char uuid
  chat_id         TEXT NOT NULL,
  source_tool     TEXT NOT NULL,           -- skill name / 'pi' / 'worker:<id>'
  evidence_type   TEXT NOT NULL,           -- 'http' | 'screenshot' | 'log' | 'cmd_output' | 'dom' | 'har' | 'other'
  summary         TEXT NOT NULL,           -- ≤ 200 chars
  raw_ref         TEXT,                    -- fs path under {workspace}/.secbot/evidence/{chat_id}/{id}
  sanitised       INTEGER NOT NULL DEFAULT 0,  -- 0/1
  sensitive_keys  TEXT,                    -- JSON list, e.g. ["token","session"]
  created_at      REAL NOT NULL,
  size_bytes      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_evidence_chat ON evidence_records (chat_id, created_at);

CREATE TABLE evidence_finding_link (
  evidence_id  TEXT NOT NULL,
  finding_id   TEXT NOT NULL,             -- BlackboardEntry.id where kind=finding
  link_role    TEXT NOT NULL DEFAULT 'primary',  -- 'primary' | 'supporting' | 'rebuttal'
  PRIMARY KEY (evidence_id, finding_id)
);
```

> 大对象（HAR / screenshot）以**文件**存于
> `{workspace}/.secbot/evidence/<safe_chat_segment>/<evidence_id>.{ext}`。
> `safe_chat_segment` 必须是单个路径段；若原始 `chat_id` 含 `/`, `..`, 空白或其他
> 不安全字符，使用稳定 hash 段（如 `chat-<sha256-prefix>`），禁止把原始 `chat_id`
> 直接拼进文件路径。`evidence_records.raw_ref` 存相对路径，读取或删除时必须验证
> resolve 后仍在 evidence root 下。`size_bytes` 用于 budget 提示（防止单次 task
> 产出 GB 级证据）。

### 5.2 API

```python
class EvidenceStore:
    def __init__(self, db: sqlite3.Connection, fs_root: Path): ...

    async def put(
        self,
        chat_id: str,
        *,
        source_tool: str,
        evidence_type: str,
        summary: str,
        raw_bytes: bytes | None = None,
        sensitive_keys: Iterable[str] = (),
    ) -> str:
        """Return evidence_id. Writes raw to fs if raw_bytes given;
        applies sanitiser when sensitive_keys is non-empty."""

    async def get(self, evidence_id: str) -> EvidenceRecord | None: ...

    async def link(
        self,
        evidence_id: str,
        finding_id: str,
        *,
        role: Literal["primary", "supporting", "rebuttal"] = "primary",
    ) -> None: ...

    async def find_for(self, finding_id: str) -> list[EvidenceRecord]: ...

    async def gc(self, chat_id: str, *, before: float) -> int:
        """Remove evidence older than `before` timestamp for chat_id."""
```

### 5.3 Sanitiser

默认 `sanitise(content, keys)`：

- 替换 JSON 中匹配 `keys` 的字段值为 `"***REDACTED***"`
- HTTP 头 `Authorization`, `Cookie`, `Set-Cookie` 自动脱敏（无需显式指定）
- URL query 中匹配 `keys` 的参数同样替换
- 保留长度 / 类型提示（如原值 32 chars → `***REDACTED:32c***`）

`sanitised=1` 仅当 raw_bytes 走过 sanitiser 时才置位；否则 `0` 表示原样。

## 6. Lifecycle

### 6.1 Blackboard 实例

- `BlackboardRegistry.get_or_create(chat_id)` 返回 per-chat 实例（行为不变）
- 实例 in-memory；进程退出丢失（结构化 entries **同步写 event_log** 实现持久化，
  见 `event-stream.md` §3）
- `drop(chat_id)` 触发清空 + GC EvidenceStore 关联记录

### 6.2 EvidenceStore 实例

- 进程单例，连接 CMDB SQLite（与现 `cmdb/` 共库）
- fs root = `{workspace}/.secbot/evidence/`
- GC 策略：默认不自动清理；`drop(chat_id)` 触发硬删除（fs + db）

### 6.3 Write 路径

```
worker.SkillTool.execute()
  └─ SkillResult{summary, raw_log_path, findings}
       ├─ raw_log_path  → EvidenceStore.put(chat_id, raw_bytes=...)
       │                    → evidence_id
       ├─ summary       → Blackboard.write(kind="evidence_ref",
       │                                   payload={evidence_id, source_tool, summary})
       └─ findings[i]   → Blackboard.write(kind="hypothesis" or
                                           "candidate_finding",
                                           payload={..., evidence_ids:[evidence_id]})
```

Pi promotion 路径：

```
Pi.tool_call("promote_finding", hypothesis_id=...)
  └─ Blackboard.write(kind="finding", payload={..., chain_of: hypothesis_id})
```

## 7. Error / Edge Cases

| Case | Behavior |
|---|---|
| 未知 kind | `Blackboard.write` 抛 `BlackboardValueError`；ToolRouter 返回 LLM 友好错误 |
| Payload 缺必填字段 | 同上，错误信息含字段名 |
| Worker 试图写 `finding` | PolicyEngine 拒绝，引导写 `hypothesis` |
| EvidenceStore fs 写失败 | 自动降级：仅写 db 记录 + summary，`raw_ref=NULL` |
| `chat_id` 含路径穿越字符 | `raw_ref` 使用 hash 后的安全目录段；不得在 evidence root 外落文件 |
| `raw_ref` resolve 后越出 evidence root | 拒绝读取 / 删除，抛 validation error |
| sanitiser 处理失败 | sanitised=0 + 写 `event_log(kind="sanitiser_fallback")` |
| Snapshot 太大（findings > 50） | 按 severity desc 截断；尾部加 `... (N more, see read_blackboard_full)` |
| 旧 `text` 写入无法识别 tag | 落 `legacy_text`，日志 warn |

## 8. Migration & Compatibility

### 8.1 Schema 演化

- PR1 引入 `evidence_records` + `evidence_finding_link`；不动现有 `blackboard.py` 内部数据（in-memory）
- 旧 `BlackboardEntry.text` 字段保留为 `Optional[str]`
- 新 `payload` 字段补 default `{}` 避免破坏 `to_dict_list` 消费者

### 8.2 API 兼容

```python
# 旧调用仍然能跑：
await board.write("recon", "[finding] open redirect on /go endpoint")
# 转译为：
# BlackboardEntry(kind="finding", payload={"title":"open redirect on /go endpoint",
#                                          "severity":"unknown", ...},
#                 text="[finding] open redirect on /go endpoint")
```

但严重缺字段时落 `legacy_text`，前端 UI 渲染加 "需要补全" 徽章。

### 8.3 WebSocket 协议

`agent_event.type='blackboard_entry'` 的 payload 在 PR1 扩展为：

```json
{
  "id": "...",
  "agent_name": "...",
  "kind": "finding",
  "payload": {...},
  "timestamp": "...",
  "text": null      // legacy only
}
```

前端按 `kind` 切换渲染卡片；旧 `text` 字段缺省 null。

## 9. Test Plan

### Schema tests

- `test_write_typed_kind`：每个 kind 一组「合法」/「缺必填」/「未知字段」
- `test_legacy_text_translation`：旧 4 个 tag 各一例，断言映射到正确 kind

### Snapshot tests

- `test_snapshot_truncation`：60 个 finding，断言只返回 50 + 末尾提示
- `test_snapshot_severity_sort`：mixed severities，断言降序

### EvidenceStore tests

- `test_put_with_sensitive_keys`：raw_bytes 含 `Authorization` 头，断言文件
  写出后头被脱敏
- `test_link_multi_finding`：1 evidence ↔ 3 finding 多对多
- `test_gc_removes_fs_and_db`：drop chat_id 后 fs 路径不存在 + db 行清空
- `test_size_bytes_recorded`：写 1MB raw_bytes 后 size_bytes=1048576
- `test_raw_storage_sanitises_chat_id_path_segment`：恶意 `chat_id` 不能让 raw 文件写出
  evidence root
- `test_raw_path_rejects_escaped_ref`：手工传入 `../...` raw_ref 必须拒绝

### Policy integration

- `test_worker_cannot_write_finding`：worker 调 `write_blackboard(kind="finding")`
  被 PolicyEngine 拒
- `test_pi_can_promote_hypothesis`：Pi 调 `promote_finding` 写出 `finding` entry

## 10. Implementation Anchors (PR1)

- `secbot/agent/blackboard.py::BlackboardEntry`（扩展 dataclass）
- `secbot/agent/blackboard.py::Blackboard.write` (重写) + `write_text` (兼容)
- `secbot/agent/blackboard.py::BlackboardSnapshot` (新)
- `secbot/agent/tools/blackboard.py::BlackboardReadTool` (markdown 渲染 snapshot)
- `secbot/agent/tools/blackboard.py::BlackboardWriteTool` (重写参数)
- `secbot/evidence/store.py::EvidenceStore` (新模块)
- `secbot/evidence/sanitiser.py::sanitise` (新)
- `secbot/cmdb/migrations/0007_evidence.sql` (新 migration)

## 11. References

- Pi Agent.md §2 「共享黑板 / Task Ledger / Evidence Store」整段
- 旧 spec: `blackboard-registry.md` （仍生效；本 spec 描述结构化增量）
- 关联 spec: `pi-orchestrator.md` / `policy-engine.md` /
  `finding-ontology.md` / `event-stream.md`
