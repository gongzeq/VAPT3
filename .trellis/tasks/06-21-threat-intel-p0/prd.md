# 威胁情报模块P0开发

> 完整PRD：[docs/prd-threat-intelligence.md](../../../docs/prd-threat-intelligence.md)
> 架构决策：[ADR-0003](../../../docs/adr/0003-threat-intelligence-as-independent-apt-centric-workspace.md)

## P0 交付范围

### 1. 存储层
- 独立数据库 `threat_intel.sqlite3`（`~/.secbot/threat_intel.sqlite3`）
- 10张核心ORM表：threat_group, threat_infra_ip, threat_vuln, threat_group_vuln_assoc, threat_malware_family, maritime_event, watchlist, industry_cpe, apt_alias, feed_pull_run
- SQLAlchemy 2.x models + 独立 Alembic 迁移
- 路径：`secbot/threat_intel/`（db.py, models.py, repo.py, migrations/）

### 2. 数据接入
- MITRE ATT&CK Groups 初始导入脚本（≥150组织）
- 国内APT别名种子（≥20条中文/厂商别名）
- CISA KEV 每日拉取 Workflow
- abuse.ch ThreatFox 每日拉取 Workflow
- 每次 Feed Pull 写入 feed_pull_run 记录

### 3. API层（`/api/threat-intel/`前缀）
- GET /overview — 概览统计（5类卡片）
- GET /groups — 组织列表（分页+搜索+watchlist过滤）
- GET /groups/:id — 组织详情（含关联IP/木马/漏洞）
- POST/DELETE /groups/:id/watch — Watchlist管理
- GET /ips — 攻击IP列表
- GET /vulns — 漏洞列表
- GET /malware — 木马家族列表
- GET /feeds/runs — Feed运行记录
- POST /feeds/pull — 手动触发Feed拉取

### 4. 前端
- 导航入口 `/threat-intel`（Shield图标，亮色风格 #F5F7FA）
- 概览页（5态势卡片 + 数据新鲜度条）
- 威胁组织列表页 + 详情页
- Feed运行页
- `webui/src/lib/threat-intel-client.ts` API封装
- `webui/src/pages/threat-intel/` 页面组件

### 5. 调度
- 2个每日Workflow定时任务（CISA KEV + ThreatFox）

### 6. 测试
- Repo层：upsert去重、watchlist、overview统计
- API层：列表分页、详情关联、Feed run计数

## 验收标准
- 迁移可运行，外键开启
- 重复导入不产生重复记录
- 空库/部分失败/正常数据三态下overview可渲染
- 中文别名搜索命中组织
- Watchlist幂等
- CVSS缺失显示"待补充"非0
- ThreatFox无法映射记录计入unmapped_count，不创建伪组织
- CMDB表无变更
