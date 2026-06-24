# 威胁情报模块全面Gap分析

## Goal

系统性审查威胁情报模块前后端实现，识别所有未对齐的Gap，为后续修复提供优先级排序和实施计划。

## What I already know

### 后端已实现（16个Feed + 完整API + 定时调度）

**Feed列表（16个）**：mitre, cisa_kev, threatfox, nvd, malwarebazaar, feodo, otx, exploit_db, urlhaus, ransomware_live, asam, osv, phishtank, ukmto, recaap, imo

**API端点（29个）**：
- overview, groups(CRUD+watch), ips(list+detail), vulns(list+detail), malware(list+detail)
- maritime(list+review), graph, feeds(runs+pull), config(cpes+aliases+api-keys)
- review-queue, expiry-sweep, **urls(list)**, **ransomware(list)**

**定时调度**：所有16个Feed均已注册cron job

### 前端已实现（15个页面）

OverviewPage, GroupsPage, GroupDetailPage, GraphPage, VulnsPage, VulnDetailPage, MalwareListPage, MalwareDetailPage, IPDetailPage, MaritimePage, WatchlistPage, AliasManagementPage, IndustryCPEPage, ReviewQueuePage, FeedsPage

---

## Gap 清单（按严重程度排序）

### 🔴 P0 — 数据已入库但用户完全无法查看

#### Gap 1: 恶意URL列表页缺失
- **后端**：✅ `/api/threat-intel/urls` 端点已实现（`list_threat_infra_urls`）
- **前端缺失**：
  - `threat-intel-client.ts` 无 `fetchThreatURLs` 函数
  - 无 `UrlsPage.tsx` 页面组件
  - `App.tsx` 无 `/threat-intel/urls` 路由
  - `ThreatIntelLayout.tsx` 导航无"恶意URL"入口
- **影响**：URLhaus 501条 + PhishTank 数据完全不可见
- **涉及文件**：`webui/src/lib/threat-intel-client.ts`, `webui/src/App.tsx`, `webui/src/pages/threat-intel/ThreatIntelLayout.tsx`, 新建 `UrlsPage.tsx`

#### Gap 2: 勒索软件事件页缺失
- **后端**：✅ `/api/threat-intel/ransomware` 端点已实现（`list_ransomware_events`）
- **前端缺失**：
  - `threat-intel-client.ts` 无 `fetchRansomwareEvents` 函数
  - 无 `RansomwarePage.tsx` 页面组件
  - `App.tsx` 无 `/threat-intel/ransomware` 路由
  - 导航无"勒索事件"入口
- **影响**：Ransomware.live 数据完全不可见
- **涉及文件**：同Gap 1模式 + 新建 `RansomwarePage.tsx`

#### Gap 3: C2 IP列表页缺失
- **后端**：✅ `/api/threat-intel/ips` 端点已实现（`list_threat_infra_ips`）
- **前端缺失**：
  - 仅有 `IPDetailPage.tsx`（单条详情），无 IP 列表页
  - `App.tsx` 只有 `/threat-intel/ips/:id` 路由，无 `/threat-intel/ips` 列表路由
  - 导航无"C2 IP"入口
  - `threat-intel-client.ts` 有 `fetchThreatIPs` 函数但无页面使用
- **影响**：无法从任何入口浏览C2 IP列表
- **涉及文件**：新建 `IPListPage.tsx`, `webui/src/App.tsx`

---

### 🟠 P1 — 概览页数据不完整

#### Gap 4: 概览统计缺少URL和勒索数据
- **后端**：`get_overview()` 返回6个区块（freshness, watched_groups, vulns, c2_ips, maritime, malware），**无URL统计、无勒索事件统计**
- **前端**：`OverviewData` 类型无对应字段
- **影响**：概览页无法反映P3新增数据的任何信息
- **涉及文件**：`secbot/threat_intel/repo.py` (`get_overview`), `webui/src/lib/threat-intel-client.ts` (`OverviewData`), `webui/src/pages/threat-intel/OverviewPage.tsx`

#### Gap 5: 概览卡片"即将上线"徽章过时 + 导航错误
- 漏洞卡片标记"即将上线"但 `/threat-intel/vulns` 页面已存在
- C2 IP卡片标记"即将上线"但无列表页可跳转（无onClick）
- 海事事件卡片标记"即将上线"但 `/threat-intel/maritime` 页面已存在
- 木马家族卡片标记"即将上线"但 `/threat-intel/malware` 页面已存在
- "威胁雷达"卡片onClick跳转到 `/threat-intel/groups` 而非 `/threat-intel/graph`
- **涉及文件**：`webui/src/pages/threat-intel/OverviewPage.tsx`

---

### 🟡 P2 — 知识图谱和组织详情缺少URL维度

#### Gap 6: 知识图谱不含URL节点
- **后端**：`get_graph_data()` 只处理 group/ip/malware/vuln 四种节点类型，**不含URL节点**
- **前端**：`GraphNode` type 只有 `"group" | "ip" | "malware" | "vuln" | "cluster"`，无 `"url"` 类型
- `GraphPage.tsx` 无URL节点渲染组件
- **影响**：即使URL已关联到威胁组织，也不会出现在知识图谱中
- **涉及文件**：`secbot/threat_intel/repo.py` (`get_graph_data`), `webui/src/lib/threat-intel-client.ts`, `webui/src/pages/threat-intel/GraphPage.tsx`, `webui/src/pages/threat-intel/GroupDetailPage.tsx`

#### Gap 7: 组织详情页缺少URL Tab
- **后端**：`get_threat_group()` 返回 infra_ips/malware_families/vulnerabilities/apt_aliases，**无URL列表**
- **前端**：GroupDetailPage tabs = ips/malware/vulns/aliases/graph，**无URL tab**
- **影响**：查看威胁组织时看不到关联的恶意URL
- **涉及文件**：`secbot/threat_intel/repo.py` (`get_threat_group`), `webui/src/pages/threat-intel/GroupDetailPage.tsx`

---

### 🟢 P3 — 数据生命周期和辅助功能缺口

#### Gap 8: 过期清理不含URL和勒索事件
- `run_expiry_sweep()` 只处理：IP自动失活/归档、海事事件删除、Feed记录删除
- **缺失**：URL无过期机制（永久active）、勒索事件无清理策略
- **影响**：数据库无限增长
- **涉及文件**：`secbot/threat_intel/repo.py` (`run_expiry_sweep`)

#### Gap 9: 复核队列不支持URL
- `get_review_queue()` 只支持 `entity_type="ip"` 和 `"maritime"`
- **缺失**：无URL低置信度复核
- **影响**：URLhaus/PhishTank 低置信度的组织归因无法人工复核
- **涉及文件**：`secbot/threat_intel/repo.py` (`get_review_queue`)

#### Gap 10: 配置页面无导航入口
- `AliasManagementPage` (APT别名管理) 和 `IndustryCPEPage` (行业CPE) 有路由但不在导航栏
- 用户只能通过直接输入URL访问
- **涉及文件**：`webui/src/pages/threat-intel/ThreatIntelLayout.tsx`

---

## Gap 汇总矩阵

| # | Gap描述 | 后端状态 | 前端状态 | 优先级 | 影响范围 |
|---|--------|---------|---------|--------|---------|
| 1 | 恶意URL列表页 | ✅ | ❌ 全缺 | P0 | URLhaus+PhishTank数据不可见 |
| 2 | 勒索事件页 | ✅ | ❌ 全缺 | P0 | Ransomware.live数据不可见 |
| 3 | C2 IP列表页 | ✅ | ❌ 缺列表页 | P0 | 无法浏览C2 IP |
| 4 | 概览缺URL/勒索统计 | ❌ 缺后端 | ❌ 缺前端 | P1 | 仪表盘不完整 |
| 5 | 概览卡片徽章/导航错误 | — | ❌ | P1 | UX误导 |
| 6 | 知识图谱缺URL节点 | ❌ | ❌ | P2 | 图谱维度不全 |
| 7 | 组织详情缺URL Tab | ❌ | ❌ | P2 | 组织分析不完整 |
| 8 | 过期清理缺URL/勒索 | ❌ | — | P3 | DB无限增长 |
| 9 | 复核队列缺URL | ❌ | — | P3 | 无法复核低置信URL |
| 10 | 配置页无导航入口 | — | ❌ | P3 | 配置页隐藏 |

## Acceptance Criteria

- [ ] Gap 1-3: 新增3个列表页（URL/勒索/IP），含路由、导航、API客户端函数
- [ ] Gap 4: `get_overview` 返回URL和勒索统计；概览页新增对应卡片
- [ ] Gap 5: 移除过时"即将上线"徽章；修复卡片导航链接
- [ ] Gap 6: `get_graph_data` 支持URL节点；前端图谱渲染URL节点
- [ ] Gap 7: `get_threat_group` 返回关联URL；GroupDetailPage新增URL Tab
- [ ] Gap 8: `run_expiry_sweep` 覆盖URL和勒索事件
- [ ] Gap 9: `get_review_queue` 支持 `entity_type="url"`
- [ ] Gap 10: 导航栏添加配置页入口

## Out of Scope

- 新增Feed源（当前16个已足够）
- PRD文档更新（P3功能未在PRD中规划，属于增量开发）
- 性能优化（分页已实现，暂无性能瓶颈）
- WebSocket网关GET/POST适配问题（独立问题，不影响数据展示）

## Technical Notes

### 关键文件索引
- 后端API路由：`secbot/api/threat_intel_routes.py`
- 后端Repo函数：`secbot/threat_intel/repo.py` (2585行)
- 后端数据模型：`secbot/threat_intel/models.py`
- 前端API客户端：`webui/src/lib/threat-intel-client.ts`
- 前端路由：`webui/src/App.tsx`
- 前端导航：`webui/src/pages/threat-intel/ThreatIntelLayout.tsx`
- 前端页面目录：`webui/src/pages/threat-intel/`
- 定时调度：`secbot/threat_intel/scheduler.py`
- PRD文档：`docs/prd-threat-intelligence.md`

### 实现模式参考
- 列表页参考：`VulnsPage.tsx`（分页+过滤+表格）
- API客户端函数参考：`fetchVulns`（URLSearchParams构建查询）
- 导航项参考：`ThreatIntelLayout.tsx` navItems数组
