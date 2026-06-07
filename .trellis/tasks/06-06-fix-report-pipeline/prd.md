# 修复扫描报告生成链路

## Goal

修复 secbot 扫描管道中 **报告无法生成** 的致命问题：vuln_scan 子智能体通过 `asset_push` 推送的漏洞发现仅存于内存态 asset feed，未持久化到 CMDB，导致 `report-html` 技能读取 CMDB 时返回空数据，HTML 报告无法生成。同时修复 orchestrator 冗余消息消费和报告失败处理两个关联问题。

## What I already know

### 问题根因

1. **P0 — 报告链路断裂**
   - Skills（nuclei/fscan/qscan）通过 `SkillResult.cmdb_writes` → `apply_cmdb_writes()` 写入 CMDB ✅
   - vuln_scan 子智能体的手动 curl 验证通过 `asset_push` 工具推送到内存态 asset feed ❌ 不写 CMDB
   - `report-html` 仅从 CMDB 读取（`build_report_model(session, scan_id)` → `list_assets/list_vulnerabilities`）
   - 结果：`{status: "empty", asset_count: 0, finding_count: 0}`

2. **P1 — Orchestrator 未处理报告失败**
   - 报告子智能体返回 `{status: "empty"}` 后，orchestrator 继续输出 "⏳ 等待报告生成完成"
   - 未识别为错误，未尝试补救

3. **P2 — 冗余资产消费循环**
   - `asset_push` 每次推送都唤醒 orchestrator（通过 bus `InboundMessage`）
   - Orchestrator 反复调用 `read_assets` 读取已知数据，产生 ~46 条冗余消息

### 架构现状

| 组件 | 存储 | 写入方式 | 读取方式 |
|------|------|---------|---------|
| Asset Feed | 内存（per-chat） | `asset_push` 工具 | `read_assets` 工具 |
| Blackboard | 内存（per-chat） | `blackboard_write` 工具 | `read_blackboard` 工具 |
| CMDB | SQLite（持久化） | `SkillResult.cmdb_writes` → `apply_cmdb_writes()` | `report-html` / dashboard API |

### 关键文件

- `secbot/agent/tools/asset_feed.py` — AssetPushTool 实现
- `secbot/cmdb/writes.py` — apply_cmdb_writes 桥接层
- `secbot/skills/report-html/handler.py` — 报告渲染入口
- `secbot/report/builder.py` — build_report_model (CMDB→ReportModel)
- `secbot/agents/orchestrator.py` — Orchestrator 提示词
- `secbot/agent/loop.py` — asset_feed 生命周期

## Assumptions (temporary)

* 修复不应破坏现有 skill → CMDB 写入链路
* scan_id 在子智能体运行期间可从 session context 获取
* report-html 的 CMDB-only 读取策略保持不变（不引入 fallback 数据源）

## Open Questions

* [ ] 资产落盘策略选择（见下方方案）

## Requirements (evolving)

* asset_push 推送的 vuln/credential/tech 类资产必须持久化到 CMDB
* orchestrator 必须在调用 report 前确保所有发现已落盘
* orchestrator 必须识别报告子智能体的失败返回并采取补救措施
* 消除或显著减少 orchestrator 的冗余资产消费消息

## Acceptance Criteria (evolving)

* [ ] 扫描 `http://111.228.2.47:8080` 后，CMDB 中存在对应的 scan/asset/vulnerability 记录
* [ ] `report-html` 能基于 CMDB 数据生成完整 HTML 报告
* [ ] orchestrator 收到报告 `{status: "empty"}` 时能重试或明确报错
* [ ] 冗余 read_assets 调用从 ~46 条减少到 <5 条

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* 实际扫描测试验证报告生成

## Out of Scope (explicit)

* 不修改 report-html 的 CMDB-only 读取策略
* 不改变 asset feed 的内存态设计（仍是实时协作通道）
* 不修改 nuclei/fscan 等 skill 的 cmdb_writes 逻辑
* 不实现报告 PDF/Markdown 导出

## Technical Notes

### 数据流现状

```
vuln_scan 子智能体
  ├── asset_push(vuln) → Asset Feed (内存) → orchestrator 通知 → 不持久化 ❌
  ├── blackboard_write → Blackboard (内存) → 不持久化 ❌
  └── skill 调用 (nuclei/fscan)
       └── cmdb_writes → apply_cmdb_writes → CMDB ✅
```

### 目标数据流

```
vuln_scan 子智能体
  ├── asset_push(vuln) → Asset Feed (内存) + CMDB (持久化) ✅
  ├── blackboard_write → Blackboard (内存)
  └── skill 调用 (nuclei/fscan)
       └── cmdb_writes → apply_cmdb_writes → CMDB ✅
```
