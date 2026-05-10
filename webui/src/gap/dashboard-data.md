# Gap: Dashboard 大屏数据接口

## 前端数据需求清单

Dashboard 页面（`src/pages/DashboardPage.tsx`）当前使用 `src/data/mock/dashboard.ts` 中的静态 mock，共 6 大模块：

| 模块 | 数据项 | 当前来源 | 后端接口状态 |
|------|--------|----------|-------------|
| **KPI 卡片** | 活跃任务、已完成扫描、高危漏洞、资产总量、待处理告警、智能体在线（含环比 delta） | `kpiCards[]` mock | ❌ 无聚合接口 |
| **风险趋势** | 7/30/90 天 × 4 级 severity（critical/high/medium/low）每日序列 | `riskTrend7/30/90[]` mock | ❌ 无趋势接口 |
| **资产分布饼图** | Web应用/API端点/数据库/服务器/网络设备/其他 | `assetDistribution[]` mock | ❌ 无分布接口 |
| **漏洞类型分布饼图** | 注入/认证缺陷/XSS/配置错误/敏感数据暴露/其他 | `vulnDistribution[]` mock | ❌ 无分布接口 |
| **资产聚类柱图** | 8 个业务系统 × 3 级风险（high/medium/low）堆叠 | `assetCluster[]` mock | ❌ 无聚类接口 |
| **历史报告表格** | 近 7 天报告列表（ID/标题/类型/高危数/状态/严重程度） | `recentReports[]` mock | ❌ 无报告列表接口 |

## 后端缺口

### 缺失接口（6 个）

| 端点 | 方法 | 说明 | 依赖数据模型 |
|------|------|------|-------------|
| `/api/dashboard/summary` | GET | KPI 全量聚合（资产/漏洞/任务/报告） | CMDB Scan/Asset/Vulnerability + 任务队列 |
| `/api/dashboard/vuln-trend?range=7d\|30d\|90d` | GET | 按日聚合漏洞 severity 趋势 | CMDB Vulnerability.created_at + severity |
| `/api/dashboard/vuln-distribution?group_by=category` | GET | 漏洞类型分布（OWASP 分类） | CMDB Vulnerability.category |
| `/api/dashboard/asset-distribution` | GET | 资产类型分布（Web/API/DB/服务器/网络设备） | CMDB Asset.tags 或新增 asset_type 字段 |
| `/api/dashboard/asset-cluster` | GET | 按业务系统聚类的高/中/低漏洞数 | CMDB Asset.tags["system"] 或新增 system 字段 |
| `/api/reports?range=7d&limit=5` | GET | 历史报告列表（分页） | **缺失 Report 持久化表** |

### 数据模型缺口

1. **Asset 缺少「业务系统」与「资产类型」字段 —— 已确认方案 A**
   - 当前 `Asset` 模型：`id, scan_id, target, ip, hostname, os_guess, tags`
   - 前端 mock 中的「CRM/ERP/官网/OA/支付/大数据/BI/内部工具」需要 `system` 或 `business_unit` 字段
   - 前端 mock 中的「Web应用/API端点/数据库/服务器/网络设备」需要 `asset_type` 枚举字段
   - **已确认**：复用现有 `tags: JSON` 字段，资产发现 agent 入库时写入 `{"system": "CRM", "type": "web_app"}`

2. **Vulnerability.category 扩展 —— 已确认方案 A**
   - 当前 `VALID_VULN_CATEGORIES = {"cve", "weak_password", "misconfig", "exposure"}`
   - 前端需要：injection, auth, xss, misconfig, exposure, other 等 OWASP 映射
   - **已确认**：直接扩展现有 `category` 枚举，新增 `injection`, `auth`, `xss`, `other` 等值，统一为一级分类

3. **缺失 Report 持久化表 —— 已确认方案 A**
   - 当前 `report/builder.py` 的 `ReportModel` 是内存对象，仅用于单 scan 的 PDF/Markdown 渲染
   - 前端「历史报告」需要持久化存储：报告元数据（ID/标题/类型/状态/作者/scan_id/创建时间）
   - **已确认**：新增 `report_meta` 表（Alembic migration），扫描完成后由 orchestrator 写入报告元数据
   - 表结构：`report_meta { id, scan_id, title, type, status, author, created_at, download_path }`

### 已有但可直接复用的后端能力

| 能力 | 位置 | 用途 |
|------|------|------|
| `list_scans()` / `list_assets()` / `list_vulnerabilities()` | `secbot/cmdb/repo.py` | Dashboard 聚合查询的底层数据源 |
| `build_report_model()` | `secbot/report/builder.py` | 单 scan 报告生成（需包装为列表接口） |
| `VALID_SCAN_STATUSES` / `VALID_SEVERITIES` | `secbot/cmdb/models.py` | 状态/严重级别枚举校验 |

## Mock 数据现状

- **位置**：`webui/src/data/mock/dashboard.ts`
- **数据量**：~220 行，覆盖全部 6 个模块
- **切换方式**：DashboardPage 直接 import，无开关；后端接口就绪后替换为 `useQuery` hook 即可

## 建议后续任务

1. **P0 — Dashboard Summary 聚合接口**（1-2d）
   - 在 CMDB repo 层新增 `dashboard_summary(actor_id)` 聚合函数
   - 暴露 `GET /api/dashboard/summary`，复用现有 `list_scans/assets/vulnerabilities`
   - 前端新增 `useDashboardSummary()` hook 替换 `kpiCards` mock

2. **P0 — 风险趋势 + 分布 + 聚类接口**（2-3d）
   - `vuln_trend`：按 `DATE(created_at)` + `severity` GROUP BY
   - `vuln_distribution`：按 `category`（或新增 `owasp_category`）GROUP BY
   - `asset_cluster`：按 `tags->system` 或新增字段 GROUP BY + severity 交叉统计
   - 前端新增 `useVulnTrend/useVulnDistribution/useAssetCluster()` hooks

3. **P1 — Report 持久化 + 列表接口**（2-3d）
   - 新增 `report_meta` 表（Alembic migration）
   - 扫描完成后由 orchestrator 写入报告元数据
   - 暴露 `GET /api/reports`
   - 前端替换 `recentReports` mock

4. **P2 — Asset 模型扩展**（1-2d）
   - 决策：复用 `tags` vs 新增字段（需与用户确认，见下方「不确定项」）
   - 更新资产发现 agent 入库逻辑，写入 system/type 信息
