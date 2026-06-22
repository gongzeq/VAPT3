# 威胁情报模块P1/P2开发

## Goal

根据 `.trellis/spec/threat-intel/` 下的4个 spec 文档，实现威胁情报模块 P1 和 P2 阶段的全部功能。

## P0 基线（已完成，不修改）

- 后端: `secbot/threat_intel/` — models.py(10表), db.py, repo.py, scheduler.py, feeds/(mitre, cisa_kev, threatfox, apt_aliases_seed)
- API: `secbot/api/threat_intel_routes.py` — 17个端点
- 前端: `webui/src/pages/threat-intel/` — 5页面 + `threat-intel-client.ts`
- 测试: 28个测试通过

## P1 实施内容

### Batch 1: 后端 Feed Pullers

| 源 | 文件 | 关键点 |
|----|------|--------|
| NVD | `feeds/nvd.py` | CVSS>=7.0过滤, KEV合并, CPE提取, 限流处理(6s/1s) |
| MalwareBazaar | `feeds/malwarebazaar.py` | 样本→家族映射, group lookup via signature |
| Feodo Tracker | `feeds/feodo.py` | C2 IP, malware→group映射 |
| AlienVault OTX | `feeds/otx.py` | 行业搜索(maritime/transport/scada), adversary→group |
| Exploit-DB | `feeds/exploit_db.py` | git clone+diff, CVE匹配→has_poc标记 |
| Industry CPE | `feeds/cpe_match.py` | `check_supply_chain()` + seed data |
| 调度 | `scheduler.py` 扩展 | 5个新Cron Job + handler扩展 |
| 注册 | `feeds/__init__.py` | 导入5个新puller |
| Enum | `models.py` | FEED_SOURCES已包含新源 |

### Batch 2: 后端 APIs

| API | 方法 | 说明 |
|-----|------|------|
| `/graph` | GET | 图谱聚合API: 节点归并+聚类+展开+置信度过滤 |
| `/vulns/{id}` | GET | 漏洞详情 + exploiting_groups |
| `/ips/{id}` | GET | IP详情 + group_name |
| `/malware/{id}` | GET | 木马详情 + sample_hashes |
| `/config/aliases/batch` | POST | 批量别名导入 |
| `/config/industry-cpes/{id}` | DELETE | CPE删除 |
| Feed失败通知 | WS | `threat_intel_feed_failed` 事件广播 |
| Repo函数 | — | `get_graph_data()`, `get_threat_vuln()`, `get_threat_infra_ip()`, `get_threat_malware()`, `run_expiry_sweep()`, `get_review_queue()`, `apply_review_action()` |

### Batch 3: 前端页面

| 页面 | 路由 | 说明 |
|------|------|------|
| 知识图谱 | `/threat-intel/graph` | reactflow力导向布局, 节点/边/聚类/抽屉/展开 |
| 漏洞详情 | `/threat-intel/vulns/:id` | CVSS/KEV/供应链徽章 + 来源证据 + 利用组织 |
| IP详情 | `/threat-intel/ips/:id` | 关联组织 + 时间线 + 来源 |
| 木马详情 | `/threat-intel/malware/:id` | 样本哈希 + YARA + 平台 |
| Watchlist管理 | `/threat-intel/watchlist` | 列表/移除/备注 |
| APT别名管理 | `/threat-intel/config/aliases` | CRUD + CSV批量导入 |
| CPE管理 | `/threat-intel/config/industry-cpes` | 列表/新增/删除 |
| GroupDetail局部图谱 | 嵌入GroupDetailPage | 径向布局 |
| Feed失败Toast | 全局 | WS事件→toast通知 |

## P2 实施内容

### Batch 4: 后端

| 功能 | 文件 | 说明 |
|------|------|------|
| 海事LLM提取 | `feeds/maritime.py` | IMO/UKMTO/ReCAAP获取 + pdfplumber + LLM提取 + 置信度 |
| 海事审核API | `threat_intel_routes.py` | PATCH /maritime/:id |
| 过期淘汰 | `repo.py` + `scheduler.py` | IP 90天归档 + maritime 365天删除 + FeedRun 90天删除 |
| 复核队列API | `threat_intel_routes.py` | GET /review-queue + POST /review-queue/:id/action |
| IP_STATUSES | `models.py` | 添加 "archived" |

### Batch 5: 前端

| 页面 | 路由 | 说明 |
|------|------|------|
| 海事事件 | `/threat-intel/maritime` | 列表+筛选+审核操作 |
| 复核队列 | `/threat-intel/review` | 低置信度记录+操作按钮 |

## Acceptance Criteria

- [ ] 5个新Feed Puller遵循P0 Feed Pull Lifecycle
- [ ] NVD拉取含限流处理和KEV合并
- [ ] Exploit-DB仅更新已有ThreatVuln（不新建）
- [ ] 图谱API支持节点归并、聚类、展开、置信度过滤
- [ ] 3个详情API返回完整数据
- [ ] 批量别名导入返回inserted/updated/failed
- [ ] Feed失败触发WebSocket通知
- [ ] 知识图谱页reactflow渲染正确，节点/边视觉编码符合spec
- [ ] 海事LLM提取含置信度计算和阈值过滤
- [ ] 过期淘汰job按策略执行
- [ ] 复核队列支持confirm/remap/dismiss操作
- [ ] lint (ruff) + typecheck (mypy) 通过
- [ ] 新增测试覆盖关键功能

## Out of Scope

- P0已完成的代码（仅扩展不重写）
- PRD修改（PRD已定稿）
- 商业情报源接入

## Technical Notes

- Spec: `.trellis/spec/threat-intel/` (5个文件, 2860行)
- P0 Feed模式参考: `feeds/cisa_kev.py`
- P0 Repo模式参考: `repo.py` upsert函数
- 前端亮色风格: `bg-slate-50 text-slate-900`
- API客户端: `webui/src/lib/threat-intel-client.ts`
- reactflow 11.11.4 已在package.json中
