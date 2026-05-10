# P1 · Report Persistence + Session Search/Archive + Prompts Config

> Parent: [05-10-backend-api-gap-fill](../05-10-backend-api-gap-fill/prd.md)
> Priority: P1 · Est: 2–3d · Depends on: P0 完成（仅限 cmdb-schema.md 已更新）

## Goal

引入 `report_meta` 表持久化历史报告元数据；扩展会话列表支持搜索 + 归档；交付 `/api/prompts` 快捷指令配置化接口。完成后前端 `recentReports` mock 被替换，`PromptSuggestions.tsx` 的 `PROMPTS[]` 数组彻底移除。

## Requirements

### 新增表 `report_meta`

见 `.trellis/spec/backend/report-meta.md`。概要：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | ULID，形如 `RPT-2026-0510-014` |
| `scan_id` | TEXT FK → `scan.id` | 所属扫描 |
| `title` | TEXT NOT NULL | 报告标题 |
| `type` | TEXT | `compliance_monthly / vuln_summary / asset_inventory / custom` |
| `status` | TEXT | `published / pending_review / editing / archived` |
| `critical_count` | INTEGER | 冗余字段，生成时聚合 |
| `author` | TEXT | actor_id |
| `created_at` | TEXT | ISO 8601 |
| `download_path` | TEXT | 相对 `~/.secbot/reports/` 的路径 |

索引：`(scan_id)`、`(status, created_at DESC)`。

### HTTP 接口（4 个）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reports` | GET | 列表 + 筛选 + 分页（`range=7d/30d/all, type, status, limit, offset`） |
| `/api/reports/{id}` | GET | 详情（元数据 + `download_url`） |
| `/api/sessions` | GET | 现有端点扩展：支持 `q`, `archived`, `limit`, `offset` |
| `/api/sessions/{key}/archive` | POST | 归档/取消归档（请求体 `{"archived": true\|false}`） |
| `/api/prompts` | GET | 从 YAML 读取快捷指令配置，见 `.trellis/spec/backend/prompts-config.md` |

### Orchestrator 写入集成

- `secbot/report/builder.py::build_report_model` 完成后，由调用方（Orchestrator / CLI report 命令）写入 `report_meta`。
- 失败场景：写入失败不回退报告生成，但记录 `logger.warning`。

## Contracts

### 1. `GET /api/reports`

查询参数：`?range=7d|30d|all&type=&status=&limit=50&offset=0`

```json
{
  "items": [
    {
      "id": "RPT-2026-0510-014",
      "scan_id": "01JS...",
      "title": "DC-IDC-A 段月报",
      "type": "compliance_monthly",
      "status": "published",
      "critical_count": 7,
      "author": "shan",
      "created_at": "2026-05-10T08:00:00+08:00"
    }
  ],
  "total": 28,
  "limit": 50,
  "offset": 0
}
```

### 2. `GET /api/reports/{id}`

响应 200：包含列表字段 + `download_url`（`/api/reports/{id}/download` 或 signed path）+ `body_preview`（可选，首 500 字）。

### 3. `GET /api/sessions?q=&archived=0|1&limit=&offset=`

**前置存储层改动**：当前 `secbot/session/manager.py` 未定义 session 级 `archived` 属性（仅在日志字符串出现）。本任务需在 session 元数据中新增 `archived: bool`（默认 `false`）字段，持久化到既有 session 文件头（兼容旧文件：读不到该字段时视为 `false`，不触发 migration）。

在现有 `_handle_sessions_list` 基础上：
- `q`：对 `title / last_message` 做 LIKE 模糊匹配。
- `archived`：`0` 仅返回未归档（默认），`1` 仅归档，省略返回全部。
- 响应新增 `archived: boolean`、`total: integer`。

### 4. `POST /api/sessions/{key}/archive`

请求 `{"archived": true}`；响应 `200 {"key": "...", "archived": true}`。

### 5. `GET /api/prompts`

见 `.trellis/spec/backend/prompts-config.md`。响应：

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

- YAML 位于 `secbot/config/prompts.yaml`（可通过 `SECBOT_PROMPTS_FILE` 环境变量覆盖）。
- 修改 YAML 后无需重启：使用 mtime 比较，请求命中时重载。

## Acceptance Criteria

- [ ] 新增 Alembic migration：创建 `report_meta` 表 + 2 个索引；`alembic upgrade head` 在全新 SQLite 成功。
- [ ] `secbot/cmdb/repo.py` 新增 `insert_report_meta()` / `list_reports()` / `get_report()`。
- [ ] Orchestrator 在 `build_report_model` 完成后写入 report_meta（可通过现有调用点 hook 注入）。
- [ ] `secbot/session/manager.py` 新增 `archived: bool` 元数据字段；旧 session 文件兼容读取（不存在时视为未归档）。
- [ ] 会话扩展参数向后兼容：不带参数调用返回形态与当前一致。
- [ ] 归档接口支持幂等；对不存在的 session 返回 `404`。
- [ ] `/api/prompts` YAML 缺失时返回 `200` 空数组（非 500），记录 warning 日志。
- [ ] 单元测试：
  - `tests/cmdb/test_report_meta.py` — CRUD + 筛选。
  - `tests/api/test_sessions_search.py` — q / archived / 分页。
  - `tests/api/test_prompts.py` — 正常 + 热加载 + 文件缺失。
- [ ] 前端 `recentReports` mock 下线；`PROMPTS[]` 改为 `useQuery('/api/prompts')`。

## Out of Scope

- 报告内容全文检索（后续需要再引入 FTS）。
- `/api/prompts` 的写接口（PUT/DELETE）；本期只读。
- 会话归档的批量操作接口。

## Technical Notes

- Spec：
  - `.trellis/spec/backend/cmdb-schema.md`（扩展 report_meta 表定义）
  - `.trellis/spec/backend/report-meta.md`（新增）
  - `.trellis/spec/backend/prompts-config.md`（新增）
- 主文件：
  - `secbot/cmdb/migrations/versions/<new>.py`
  - `secbot/cmdb/models.py` — 新增 `ReportMeta` ORM
  - `secbot/cmdb/repo.py` — 新增 CRUD
  - `secbot/report/builder.py` — 完成后回写入口
  - `secbot/session/manager.py` — archived 字段 + 过滤
  - `secbot/api/prompts.py` — 新文件，配置加载 + 热重载
  - `secbot/config/prompts.yaml` — 默认配置（将当前 `PROMPTS[]` 4 项原样迁入）
