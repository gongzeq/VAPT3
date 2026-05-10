# Prompts Config

> Authoritative contract for the quick-command (快捷指令) configuration source and the `GET /api/prompts` endpoint.
> Implementation: `secbot/api/prompts.py` + `secbot/config/prompts.yaml`.

---

## 1. Why YAML, not DB

Quick commands are a **read-only, low-churn, developer-edited** asset — similar to expert agent YAML (see [agent-registry-contract.md](./agent-registry-contract.md)). A DB table would add migrations without delivering user-facing value. YAML keeps authoring friction at zero and lets the choice be revisited only when inline editing from the UI is actually requested.

---

## 2. File location

Resolution order (first hit wins):

1. `$SECBOT_PROMPTS_FILE` (absolute path, escape hatch for tests)
2. `~/.secbot/prompts.yaml` (user override)
3. `secbot/config/prompts.yaml` (bundled default, committed to repo)

If none exist, `GET /api/prompts` returns `{"prompts": []}` and logs a `warning` once per process.

---

## 3. YAML schema

```yaml
# secbot/config/prompts.yaml
prompts:
  - key: scanAsset
    title: 全网资产发现
    subtitle: 扫描内网所有存活主机并入库 CMDB
    prefill: "对资产 192.168.1.0/24 发起一次轻量端口扫描，重点看 Web 服务"
    icon: Radar
  - key: weakPwd
    title: 弱口令检测
    subtitle: SSH/RDP/SMB 常见服务字典爆破
    prefill: "对最近一周新增的资产做一轮弱口令探测，结果按高危聚合"
    icon: Key
  - key: summarize
    title: 月度合规报告
    subtitle: 汇总当月扫描数据导出 PDF
    prefill: "把今天的扫描发现按业务系统聚合，生成一份执行摘要"
    icon: FileText
  - key: drill
    title: CVE 影响排查
    subtitle: 输入 CVE 编号，自动定位受影响资产
    prefill: "针对最近一条高危漏洞，给我一个验证 PoC 与修复建议"
    icon: Bug
```

### 3.1 Required fields

| Field | Type | Constraint |
|-------|------|-----------|
| `key` | string | **Unique** across the file. Used by the frontend as React key and analytics id. Allowed chars: `[a-zA-Z][a-zA-Z0-9_]*`. |
| `title` | string | ≤ 12 CJK chars / 24 latin chars — fits the chip. |
| `subtitle` | string | ≤ 30 CJK chars — secondary line. |
| `prefill` | string | The exact text that will populate the composer when the chip is clicked. No templating in v1. |
| `icon` | string | Lucide icon name (PascalCase). Unknown names fall back to `Sparkles` in the frontend — backend does not validate, but the set MUST be checked in `tests/api/test_prompts.py` against a whitelist of currently shipped icons. |

### 3.2 Forbidden

- No multi-language variants. Text is Chinese-only (mirrors the rest of dashboard strings served by the backend).
- No nested groups / categories. Flat list only.
- No per-role or per-agent gating. All authenticated users see the same list.

---

## 4. Hot reload

- The handler stats the source file on every request (single `stat()` call, ~µs).
- When `mtime` changes, the YAML is re-parsed and the in-memory cache swapped atomically.
- Parse errors serve the previous cached value and log a `warning` with the parse error. The frontend never sees an empty list because of a transient edit.
- First load and errors emit a structured log line: `prompts.loaded count=<n> source=<path>` / `prompts.reload_failed error=<msg>`.

---

## 5. HTTP contract

### 5.1 `GET /api/prompts`

```json
{
  "prompts": [
    {
      "key": "scanAsset",
      "title": "全网资产发现",
      "subtitle": "扫描内网所有存活主机并入库 CMDB",
      "prefill": "对资产 192.168.1.0/24 发起一次轻量端口扫描，重点看 Web 服务",
      "icon": "Radar"
    }
  ]
}
```

- No `ETag` / `Cache-Control` in v1 (payload is < 2 KB).
- Auth: same bearer token as the rest of `/api/**`.

### 5.2 Error modes

| Condition | Status | Body |
|-----------|--------|------|
| YAML missing from all 3 locations | 200 | `{"prompts": []}` |
| YAML parse error | 200 | last known good cached value (never 500) |
| Duplicate `key` | 200 | first occurrence wins; `warning` logged with the duplicate key |

---

## 6. Testing

`tests/api/test_prompts.py` MUST cover:

- Default bundled YAML returns 4 prompts in documented order.
- `$SECBOT_PROMPTS_FILE` override picked up.
- File missing → `200 {"prompts": []}` + warning logged.
- Malformed YAML → 200 with previous cached value.
- Touching the file (mtime bump) → next request reflects new content without process restart.
- Duplicate key → deduped, first-wins.
- All `icon` values in the shipped YAML appear in the frontend's `ICON_MAP` whitelist (import from `webui/src/data/mock/icons.ts` or equivalent).

---

## Origin

- `.trellis/tasks/05-10-p1-report-session-prompts/prd.md`
- `webui/src/gap/home-assistant-data.md` — "快捷指令 chips" gap + confirmed config-file approach
- `webui/src/components/PromptSuggestions.tsx` — the 4 prompts migrated verbatim
