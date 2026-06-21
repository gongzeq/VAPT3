# 威胁情报模块 PRD

> 版本：v1.1 | 状态：补充评审稿 | 关联ADR：[0003-threat-intelligence-as-independent-apt-centric-workspace.md](../docs/adr/0003-threat-intelligence-as-independent-apt-centric-workspace.md)

---

## 一、概述

### 1.1 背景

智海网盾（secbot）当前是一个以主动扫描为核心的对话式VAPT系统。用户需要一个**被动情报消费**能力：持续汇聚全球公开威胁情报，聚焦中国交通与海事行业，为安全运营人员提供 Threat Groups（威胁组织）、其基础设施（C2 IP）、武器库（木马家族）、已知漏洞（CISA KEV / 高危CVE）以及海事安全态势的结构化视图。

### 1.2 目标

构建一个**独立的威胁情报工作空间**，具备：

- 定时从公开数据源拉取结构化情报并入库
- 以威胁组织（Threat Group，含APT/犯罪团伙/国家级组织）为核心枢纽关联基础设施、木马家族与已知利用漏洞
- 独立跟踪高危漏洞与海事事件，避免把所有情报强行归因到APT
- 提供Dashboard式概览 + 下钻详情的浏览体验
- 支持用户设置重点关注组织（Watchlist）
- 记录Feed拉取状态、数据新鲜度、来源与置信度，便于人工校验和排错

### 1.3 非目标（本模块不涉及）

- 不主动扫描任何目标（非VAPT扩展）
- 不做实时流式威胁情报（非SIEM联动）
- 不与现有CMDB扫描数据混合存储
- 不自动处置资产、不自动封禁IP、不自动触发漏洞验证
- 不下载或执行恶意样本，不存储Exploit-DB利用代码正文，只记录元数据与来源链接

---

## 二、用户角色与使用场景

### 2.1 用户角色

| 角色 | 描述 |
|------|------|
| **安全运营人员** | 日常浏览威胁情报概览，关注特定APT组织动态，查看高危漏洞趋势 |
| **安全分析师** | 下钻到具体威胁组织查看关联的IP/木马/漏洞，分析攻击链路 |
| **安全管理员** | 管理Watchlist、维护行业CPE清单和国内APT别名映射 |
| **只读审计人员** | 查看情报来源、更新时间和Feed运行状态，不维护配置 |

### 2.2 核心场景

**场景1：每日态势感知**
> 安全运营人员打开"威胁情报"页面，30秒内看到：关注APT组织昨夜新增了3个C2 IP、CISA KEV新增了2个高危漏洞、海事区域发布了1条航行安全警告。

**场景2：APT组织深度分析**
> 安全分析师点击"APT41"进入详情页，查看该组织的别名（Winnti/Barium）、MITRE ATT&CK TTP矩阵、已知的C2 IP列表、使用的恶意软件家族（ShadowPad/PlugX）、以及该组织已知利用的高危漏洞列表。

**场景3：供应链漏洞筛查**
> 安全管理员发现CISA KEV/NVD新增了一个影响Siemens SIMATIC（港口SCADA常用）的RCE漏洞，系统基于Industry CPE List标记为"行业供应链相关"。若该CVE也出现在CMDB资产漏洞中，前端只展示匹配提示，不向CMDB写入新漏洞。

**场景4：设置重点监控**
> 安全管理员将"海莲花"（APT-C-00/OceanLotus）加入Watchlist，后续该组织的任何新活动（新C2、新木马、新利用漏洞）都会在概览页优先展示。

**场景5：Feed异常排查**
> 只读审计人员看到ThreatFox昨夜拉取失败，进入Feed运行记录查看失败原因、上次成功时间、跳过/无法映射记录数量，确认概览页的数据新鲜度是否受影响。

---

## 三、数据模型

### 3.1 核心架构：Threat Group星形模型

```
                  Threat Infrastructure IP (C2)
                          |
  Threat Vulnerability -- Group Vulnerability Association -- Threat Group -- Threat Malware Family
                          |
                  Threat Group Watchlist

  Maritime Intelligence Event (独立维度)
  Threat Intel Feed Run (运维维度)
  Industry CPE List / APT Alias (配置维度)
```

**Threat Group（威胁组织）** 是基础设施、木马家族与已知利用漏洞的中心枢纽。**Threat Vulnerability（威胁漏洞）** 可以独立存在；只有存在来源证据说明某组织利用该漏洞时，才通过 **Threat Group Vulnerability Association** 关联到组织。**Maritime Intelligence Event（海事情报事件）** 不做APT归因，独立存储。

### 3.2 跨实体通用字段与约束

| 字段 | 类型 | 说明 |
|------|------|------|
| actor_id | string | 预留多用户/租户字段；全局情报默认 `local`，Watchlist按用户隔离 |
| source_refs | JSON array | 来源证据列表：`{source, source_id, url, observed_at, confidence}` |
| confidence | float | 0.0-1.0，来源映射/LLM提取/人工确认的综合置信度 |
| first_seen | datetime/date | 首次在来源中观察到的时间 |
| last_seen | datetime/date | 最近在来源中观察到的时间 |
| last_ingested_at | datetime | 最近一次被Feed拉取写入/更新的时间 |

**统一约束：**

- 所有时间使用UTC存储，前端按本地时区展示。
- 所有外部枚举先进入内部规范枚举；无法映射的值进入 `tags` 或 `source_refs`，不直接污染核心枚举。
- 所有写入使用upsert，不允许同一Feed重复创建语义重复记录。
- Watchlist是用户范围数据；Threat Group、Threat Vulnerability、Threat Infrastructure IP、Threat Malware Family、Maritime Intelligence Event默认是全局共享数据。

### 3.3 数据实体

#### 3.3.1 Threat Group（威胁组织）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| name | string | 组织名称（MITRE标准名） |
| aliases | JSON array | 别名列表（含国内命名） |
| description | text | 组织简介 |
| origin_country | string | 归因国家 |
| target_sectors | JSON array | 目标行业标签 |
| mitre_id | string | MITRE ATT&CK Group ID (G0xxx) |
| techniques | JSON array | 使用的ATT&CK技术ID列表 |
| first_seen | date | 首次活动时间 |
| last_seen | date | 最近在来源中观察到的时间 |
| source | string | 数据来源（mitre/otx/manual） |
| confidence | float | 归一化置信度 |
| source_refs | JSON array | 来源证据 |
| last_ingested_at | datetime | 最近入库更新时间 |
| created_at | datetime | 记录创建时间 |
| updated_at | datetime | 记录更新时间 |

唯一约束：`mitre_id`（非空时唯一）；否则 `lower(name)` 唯一。别名搜索必须覆盖 `aliases` 与 APT Alias 表。`is_watched` 不是数据库列，而是 API 响应计算字段，由 Watchlist 表按 `actor_id` JOIN 得出。

#### 3.3.2 Threat Infrastructure IP（威胁基础设施IP）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| group_id | string (FK) | 关联的威胁组织 |
| ip_address | string | IP地址 |
| ip_type | enum | c2 / scanner / proxy / drop |
| malware_family | string | 来源返回的原始标签字符串（如 ThreatFox 的 `malware_name`），不保证与 Threat Malware Family 表一一对应；P1 图谱通过 `lower()` 模糊匹配关联 |
| geo_country | string | GeoIP国家 |
| asn | string | ASN号 |
| first_seen | datetime | 首次发现时间 |
| last_seen | datetime | 最近活跃时间 |
| status | enum | active / inactive |
| source | string | 数据来源（threatfox/feodo/manual） |
| confidence | float | 组织/IP映射置信度 |
| source_refs | JSON array | 来源证据 |
| last_ingested_at | datetime | 最近入库更新时间 |
| tags | JSON array | 附加标签 |
| created_at | datetime | 记录创建时间 |

唯一约束：`group_id + ip_address + ip_type`。若同一IP被多个组织声称使用，P0保留置信度最高的主归属，并在 `source_refs` 中记录冲突来源；P1可扩展为多组织关联。

#### 3.3.3 Threat Vulnerability（威胁漏洞）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| cve_id | string | CVE编号（唯一约束） |
| title | string | 漏洞标题 |
| description | text | 漏洞描述 |
| cvss_score | float nullable | CVSS评分；CISA KEV在NVD补充前可为空 |
| severity | enum | high / critical |
| affected_products | JSON array | 影响的CPE列表 |
| is_supply_chain | boolean | 是否命中行业CPE清单 |
| has_poc | boolean | 是否有公开PoC |
| exploit_available | boolean | Exploit-DB是否有利用代码 |
| is_cisa_kev | boolean | 是否来自/命中CISA KEV |
| cisa_kev_date | date | CISA KEV收录日期（如有） |
| published_date | date | CVE发布日期 |
| primary_source | string | 主数据来源（cisa_kev/nvd/manual） |
| sources | JSON array | 合并来源列表 |
| source_refs | JSON array | 来源证据 |
| last_ingested_at | datetime | 最近入库更新时间 |
| tags | JSON array | 附加标签 |
| created_at | datetime | 记录创建时间 |
| updated_at | datetime | 记录更新时间 |

唯一约束：`cve_id`。纳入规则：`is_cisa_kev = true` 或 `cvss_score >= 7.0`；CISA KEV 漏洞 `severity` 取 `max(CVSS映射值, high)`——CVSS >= 9.0 为 critical，否则为 high，CVSS 缺失时为 high。NVD 非 KEV 漏洞按 CVSS 标准映射（7.0-8.9=high，9.0+=critical）。

#### 3.3.4 Threat Group Vulnerability Association（组织-漏洞利用关系）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| group_id | string (FK) | 关联威胁组织 |
| vulnerability_id | string (FK) | 关联威胁漏洞 |
| relationship_type | enum | exploited / targeted / reported |
| first_seen | date | 首次观察到组织利用/关注该漏洞 |
| last_seen | date | 最近观察时间 |
| confidence | float | 关系置信度 |
| source_refs | JSON array | 关系来源证据 |
| created_at | datetime | 记录创建时间 |
| updated_at | datetime | 记录更新时间 |

唯一约束：`group_id + vulnerability_id + relationship_type`。只有 `exploited` 关系进入组织详情页"已知利用漏洞"默认列表；`targeted/reported` 作为弱证据折叠展示。

#### 3.3.5 Threat Malware Family（威胁木马家族）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| group_id | string (FK) | 关联的威胁组织 |
| family_name | string | 恶意软件家族名称 |
| aliases | JSON array | 别名 |
| description | text | 家族描述 |
| type | enum | rat / backdoor / ransomware / stealer / dropper / botnet / other |
| platform | JSON array | 目标平台（windows/linux/macos/android） |
| sample_hashes | JSON array | 样本哈希列表 [{md5, sha256, source}] |
| yara_rules | JSON array | 关联YARA规则名 |
| first_seen | date | 首次发现日期 |
| last_active | date | 最近活跃日期 |
| source | string | 数据来源（malwarebazaar/manual） |
| confidence | float | 家族/组织映射置信度 |
| source_refs | JSON array | 来源证据 |
| last_ingested_at | datetime | 最近入库更新时间 |
| tags | JSON array | 附加标签 |
| created_at | datetime | 记录创建时间 |

唯一约束：`group_id + lower(family_name)`。样本哈希只存储哈希与来源元数据，不下载样本。

#### 3.3.6 Maritime Intelligence Event（海事情报事件）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| event_type | enum | piracy / security_warning / gnss_interference / navigation_warning / other |
| title | string | 事件标题 |
| description | text | 事件描述 |
| location | JSON | {lat, lon, region, description} |
| severity | enum | critical / high / medium / low |
| event_date | datetime | 事件发生时间 |
| source | string | 数据来源（imo/ukmto/recaap/other） |
| source_url | string | 原始来源链接（供人工验证） |
| extraction_confidence | float | LLM提取置信度 |
| verification_status | enum | unreviewed / confirmed / dismissed |
| source_refs | JSON array | 来源证据 |
| tags | JSON array | 附加标签 |
| created_at | datetime | 记录创建时间 |

唯一约束：`source + source_url + event_date`，无URL时用 `source + title + event_date + location.region` 指纹去重。

#### 3.3.7 辅助表

**Watchlist（关注清单）**

| 字段 | 类型 | 说明 |
|------|------|------|
| actor_id | string | 用户/租户范围，默认 `local` |
| group_id | string (FK) | 关联威胁组织 |
| added_at | datetime | 加入时间 |
| note | text | 用户备注 |

唯一约束：`actor_id + group_id`。

**Industry CPE List（行业CPE清单）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| cpe_string | string | CPE标识符 |
| product_name | string | 产品名称 |
| vendor | string | 厂商 |
| industry_tag | string | 行业标签（maritime/port/scada/transport） |
| confidence | float | 行业相关性置信度 |
| source | string | 维护来源（manual/vendor/report） |
| updated_at | datetime | 最近维护时间 |
| note | text | 备注 |

**APT Alias（国内APT别名映射）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| group_id | string (FK) | 关联威胁组织 |
| alias_name | string | 别名（如"海莲花"） |
| naming_org | string | 命名机构（奇安信/安恒/360等） |
| confidence | float | 映射置信度 |
| source_url | string | 映射来源 |

唯一约束：`lower(alias_name) + naming_org`。

**Feed Pull Run（Feed拉取运行记录）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (ULID) | 主键 |
| source | string | 数据源（mitre/cisa_kev/threatfox等） |
| trigger | enum | manual / schedule |
| status | enum | running / ok / partial / failed |
| started_at | datetime | 开始时间 |
| finished_at | datetime nullable | 结束时间 |
| inserted_count | int | 新增记录数 |
| updated_count | int | 更新记录数 |
| skipped_count | int | 去重/过滤跳过数 |
| unmapped_count | int | 无法映射到Threat Group/CVE/CPE的记录数 |
| error_message | text nullable | 失败摘要 |
| metadata | JSON | Rate limit、分页游标、原始统计等 |

---

## 四、数据源与接入策略

### 4.1 数据源矩阵

| 数据源 | 情报类型 | 接入方式 | 更新频率 | 免费层级 | MVP阶段 |
|--------|---------|---------|---------|---------|---------|
| **MITRE ATT&CK Groups** | 威胁组织 | 全量导入（JSON） | 初始导入+季度更新 | 完全免费 | P0 |
| **CISA KEV** | 已知被利用漏洞 | API定时拉取 | 每日 | 完全免费 | P0 |
| **abuse.ch ThreatFox** | C2 IP + 组织关联 | API定时拉取 | 每日 | 完全免费 | P0 |
| **国内APT别名种子** | 中文别名映射 | 内置种子+人工维护 | 初始导入+人工更新 | 公开报告 | P0 |
| **abuse.ch Feodo Tracker** | Botnet C2 | API定时拉取 | 每日 | 完全免费 | P1 |
| **NVD** | 全量CVE | API定时拉取（CVSS>=7.0过滤） | 每日 | 完全免费 | P1 |
| **abuse.ch MalwareBazaar** | 木马样本哈希 | API定时拉取 | 每日 | 完全免费 | P1 |
| **AlienVault OTX** | 行业相关Pulse | API定时搜索 | 每周 | 完全免费 | P1 |
| **Exploit-DB** | PoC可用性 | Git仓库diff | 每周 | 完全免费 | P1 |
| **IMO GISIS** | 海事海盗事件 | LLM提取（HTML） | 每周 | 完全免费 | P2 |
| **UKMTO** | 海事安全警告 | LLM提取（PDF/HTML） | 每周 | 完全免费 | P2 |
| **ReCAAP ISC** | 亚洲海盗事件 | LLM提取（PDF） | 每月 | 完全免费 | P2 |

### 4.2 过滤规则

| 维度 | 过滤条件 |
|------|---------|
| 漏洞 | CISA KEV直接纳入；NVD按CVSS >= 7.0纳入 |
| 攻击IP | 必须关联已知威胁组织 |
| 木马样本 | 必须关联已知威胁组织 |
| 供应链漏洞 | CPE命中Industry CPE List额外标记 |
| 海事事件 | 不做APT关联，独立存储 |

### 4.3 映射与去重规则

| 对象 | 规则 |
|------|------|
| 威胁组织 | 先按 `mitre_id` 匹配，再按规范化名称与别名匹配；无法匹配时进入 `unmapped_count`，不自动新建低置信组织 |
| C2 IP | 必须映射到Threat Group；映射来源包括ThreatFox threat_type/tag、OTX Pulse、人工别名表 |
| 木马家族 | 必须映射到Threat Group；若只知道家族但未知组织，P0跳过并计入未映射 |
| 漏洞 | 按 `cve_id` upsert，CISA KEV与NVD来源合并到同一记录 |
| 组织-漏洞关系 | 只有来源明确陈述某组织利用/关注某CVE时创建关联；不得仅凭行业相关性或CVSS推断 |
| 供应链标记 | NVD CPE与Industry CPE List命中后置 `is_supply_chain=true`，命中证据写入 `source_refs` |
| 海事事件 | 按来源URL、事件时间、区域与标题指纹去重；LLM置信度低于0.65的记录默认 `unreviewed` |
| 图谱节点归并 | `GET /api/threat-intel/graph` 返回节点时，对相同 `ip_address` 或 `lower(family_name)` 的实体合并为单节点，边分别连到各自关联组织；数据库写入逻辑不变，归并仅在图谱 API 响应层执行 |

### 4.4 调度方式

使用现有Workflow系统的定时任务功能，每个Feed Pull为一个独立的Workflow Job：

- **每日任务**：CISA KEV拉取 + ThreatFox拉取（+P1阶段的NVD/MalwareBazaar/Feodo）
- **每周任务**：OTX行业搜索 + Exploit-DB diff
- **每月任务**：海事源LLM提取（P2）
- 每次运行必须写入 `feed_pull_run`，记录状态、计数、失败原因、上次成功时间和Rate Limit元数据。
- 手动触发与定时触发使用同一套Feed Pull实现，差异只体现在 `trigger` 字段。

### 4.5 非结构化源处理（P2）

海事情报源（IMO GISIS / UKMTO / ReCAAP）无结构化API，采用LLM提取：

1. Workflow Job定时触发
2. 调用LLM读取源页面/PDF内容
3. LLM提取结构化事件数据（事件类型、位置、时间、严重性）
4. 写入 `maritime_event` 表，保留 `source_url` 与 `extraction_confidence` 供人工验证
5. 置信度低或字段缺失的事件不进入概览"最近事件"计数，只进入待审列表

---

## 五、存储架构

### 5.1 独立数据库

- 数据库文件：`~/.secbot/threat_intel.sqlite3`（默认，与 `~/.secbot/cmdb.sqlite3` 同级；可通过 `SECBOT_THREAT_INTEL_URL` 覆盖）
- ORM：SQLAlchemy 2.x（复用项目现有技术栈）
- 独立的models、repo、migrations模块
- 路径：`secbot/threat_intel/db.py`、`secbot/threat_intel/models.py`、`secbot/threat_intel/repo.py`、`secbot/threat_intel/migrations/`
- SQLite连接PRAGMA与CMDB保持一致：WAL、`synchronous=NORMAL`、`foreign_keys=ON`、`busy_timeout=5000`
- 迁移入口独立于CMDB Alembic，避免Threat Intel schema演进影响VAPT扫描数据

### 5.2 与现有系统的边界

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ cmdb.sqlite3    │     │detection_results│     │threat_intel.sqlite3│
│  (VAPT数据)     │     │  (钓鱼/日志)    │     │  (威胁情报)     │
│                 │     │                 │     │                 │
│ Scan/Asset/     │     │ Phishing/       │     │ ThreatGroup/    │
│ Vulnerability/  │     │ LogAnalysis/    │     │ ThreatIP/       │
│ Service         │     │ Stats           │     │ ThreatVuln/     │
│                 │     │                 │     │ ThreatMalware/  │
│                 │     │                 │     │ MaritimeEvent/  │
│                 │     │                 │     │ FeedPullRun     │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────┬───────────┘                       │
                     │                                   │
              VAPT API Routes                   Threat Intel API Routes
                     │                                   │
                     └───────────┬───────────────────────┘
                                 │
                           Frontend (WebUI)
```

**边界规则：**

- Threat Intel Store不写入CMDB的 `Vulnerability` / `VulnerabilityCandidate` 表。
- 前端可以在资产/漏洞视图展示"命中Threat Vulnerability"徽标，但徽标来自查询匹配，不改变CMDB记录状态。
- Workflow负责调度Feed Pull，但Feed Pull的领域写入只经过 `secbot/threat_intel/repo.py`。
- `detection_results.db` 仍只服务钓鱼邮件与日志分析，不承载威胁情报实体。

---

## 六、API设计

### 6.1 API路由

所有威胁情报API挂在 `/api/threat-intel/` 前缀下。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/threat-intel/overview` | 概览页统计数据（5类卡片数据） |
| GET | `/api/threat-intel/groups` | 威胁组织列表（分页+搜索+watchlist过滤） |
| GET | `/api/threat-intel/groups/:id` | 威胁组织详情（含关联IP/木马/漏洞） |
| POST | `/api/threat-intel/groups/:id/watch` | 加入Watchlist |
| DELETE | `/api/threat-intel/groups/:id/watch` | 移出Watchlist |
| GET | `/api/threat-intel/ips` | 攻击IP列表（分页+按组织过滤） |
| GET | `/api/threat-intel/ips/:id` | 攻击IP详情 |
| GET | `/api/threat-intel/vulns` | 漏洞列表（分页+严重性+供应链过滤） |
| GET | `/api/threat-intel/vulns/:id` | 漏洞详情 |
| GET | `/api/threat-intel/malware` | 木马家族列表（分页+按组织过滤） |
| GET | `/api/threat-intel/malware/:id` | 木马家族详情（含样本哈希） |
| GET | `/api/threat-intel/maritime` | 海事事件列表（分页+时间范围+类型过滤） |
| GET | `/api/threat-intel/feeds/runs` | Feed运行记录列表 |
| POST | `/api/threat-intel/feeds/pull` | 手动触发Feed拉取，返回Feed Pull Run ID |
| GET | `/api/threat-intel/config/industry-cpes` | 行业CPE清单 |
| POST | `/api/threat-intel/config/industry-cpes` | 新增行业CPE（管理员） |
| GET | `/api/threat-intel/config/aliases` | APT别名映射 |
| POST | `/api/threat-intel/config/aliases` | 新增APT别名映射（管理员） |
| GET | `/api/threat-intel/graph` | 知识图谱数据（nodes+edges），支持 `group_id`（局部）、`watched=true`（全局）、`group_ids=a,b,c`（多组织对比）— **P1** |

### 6.2 通用API约定

- 列表接口统一支持 `page`、`page_size`、`sort`、`order`，默认 `page=1&page_size=20`，最大 `page_size=100`。
- 列表响应统一为 `{items, page, page_size, total}`。
- `GET /groups` 支持 `q`、`watched=true|false`、`origin_country`、`target_sector`；默认排序 `is_watched DESC, name ASC`，`is_watched` 由 Watchlist 表 JOIN 计算得出。
- `GET /ips` 支持 `group_id`、`ip_type`、`status`、`q`。
- `GET /vulns` 支持 `q`、`severity`、`is_supply_chain`、`is_cisa_kev`、`has_poc`、`exploit_available`。
- `GET /malware` 支持 `group_id`、`type`、`platform`、`q`。
- `GET /maritime` 支持 `event_type`、`severity`、`from`、`to`、`verification_status`。
- `GET /graph` 支持 `group_id`（单组织局部图谱）、`watched=true`（Watchlist全局图谱）、`group_ids=a,b,c`（多组织对比）。可选参数 `top_n`（每个组织每类关联节点上限，默认30）、`min_confidence`（边置信度阈值，默认0.0）、`node_types`（过滤节点类型，逗号分隔：`ip,malware,vuln`）。响应结构为 `{nodes: [{id, type, label, data}], edges: [{source, target, type, confidence}]}`。当某类关联超过 `top_n` 时，返回 `type: "cluster"` 的聚合节点（如 `label: "C2 IP x67"`），点击聚合节点可通过 `GET /graph?group_id=xxx&expand_cluster=ip` 获取展开数据。
- 写接口在当前单用户版本使用 `actor_id=local`；后续RBAC接入后，Watchlist按当前用户隔离，CPE/Alias维护仅管理员可写。
- 错误响应沿用aiohttp JSON风格：`{error: {message, type, code}}`。

### 6.3 概览API响应结构

**活动计算口径**：`watched_groups_activity` 中的"活动"指关注组织在近7天内有新入库记录（`last_ingested_at >= now - 7d`）的实体。`recent_activity_count` 为近7天有新入库记录的关注组织数量。`activities` 数组按 `group_id + activity_type` 聚合，`activity_type` 枚举为 `new_c2_ip` / `new_malware` / `new_vuln`；每条 `count` 为该组织该类型近7天新入库记录数，`timestamp` 为最近一次入库时间。判定字段统一使用 `last_ingested_at`（Feed 拉取写入时间），而非 `first_seen`（情报首现时间）。

```json
{
  "freshness": {
    "last_success_at": "2026-06-16T08:00:00Z",
    "stale_sources": ["threatfox"],
    "failed_sources": []
  },
  "watched_groups_activity": {
    "total_watched": 12,
    "recent_activity_count": 3,
    "activities": [
      {
        "group_id": "01HQ...",
        "group_name": "APT41",
        "activity_type": "new_c2_ip",
        "count": 2,
        "timestamp": "2026-06-16T08:00:00Z"
      }
    ]
  },
  "high_severity_vulns": {
    "total": 847,
    "new_last_7d": 12,
    "supply_chain_count": 34,
    "trend": "up"
  },
  "active_c2_ips": {
    "total": 1243,
    "by_group": [
      {"group_name": "APT41", "count": 87},
      {"group_name": "Lazarus Group", "count": 64}
    ]
  },
  "maritime_events": {
    "total": 156,
    "recent_count": 3,
    "latest": {
      "title": "Piracy incident - Gulf of Guinea",
      "event_date": "2026-06-15T14:30:00Z",
      "severity": "high"
    }
  },
  "malware_activity": {
    "total_families": 89,
    "recent_samples_7d": 45,
    "top_families": [
      {"family": "ShadowPad", "group": "APT41", "sample_count": 23},
      {"family": "PlugX", "group": "APT-C-00", "sample_count": 18}
    ]
  }
}
```

---

## 七、前端设计

### 7.1 导航入口

在顶部导航栏新增一级入口 **"威胁情报"**，使用 `Shield` 图标（lucide-react）。

路由：`/threat-intel`

**视觉风格**：威胁情报模块作为独立工作空间，整体采用**亮色风格**（背景 `#F5F7FA` 浅色底），与现有 VAPT 模块的暗色海蓝风格区分。Navbar 在 `/threat-intel/*` 路由下切换为亮色变体（白底 + 轻阴影 + 深色文字），其余路由保持暗色。图谱节点采用双色渐变填充（如 indigo→violet、amber→orange），卡片使用 14-16px 圆角与柔和阴影，整体追求高吸引力和现代感。

现有WebUI落点：

- `webui/src/App.tsx` 注册 `/threat-intel` 及子路由。
- `webui/src/components/Navbar.tsx` 的 `NAV_ITEMS` 增加威胁情报入口；Navbar 组件增加路由感知主题切换逻辑（`useLocation().pathname.startsWith('/threat-intel')` 时切换为亮色变体）。
- `webui/src/i18n/locales/*/common.json` 增加 `nav.threatIntel`，中文默认"威胁情报"。
- 新增 `webui/src/lib/threat-intel-client.ts` 封装 `/api/threat-intel/*`。
- 新增 `webui/src/pages/threat-intel/` 目录存放所有威胁情报页面组件。

### 7.2 页面结构

#### 概览页（`/threat-intel`）

5个态势卡片响应式排列，点击下钻；顶部展示数据新鲜度条（最近成功Feed时间、失败源、过期源）：

| 卡片 | 核心指标 | 下钻路由 |
|------|---------|---------|
| 关注组织动态 | watchlist组织数 + 近7天活动数 | `/threat-intel/groups?watched=true` |
| 高危漏洞速览 | 漏洞总数 + 近7天新增 + 趋势箭头 | `/threat-intel/vulns` |
| 活跃C2统计 | 活跃C2总数 + Top3组织分布 | `/threat-intel/ips` |
| 海事安全事件 | 事件总数 + 最近事件摘要 | `/threat-intel/maritime` |
| 木马家族活跃 | 家族总数 + 近7天新样本数 | `/threat-intel/malware` |

#### 威胁组织列表页（`/threat-intel/groups`）

- 搜索框（支持名称/别名搜索）
- 过滤：Watchlist / 全部 / 按归因国家
- 卡片列表展示每个组织：名称、别名、目标行业、关联IP数/木马数/漏洞数、Watchlist标记
- 若该组织在概览 API 的 `activities` 列表中，卡片展示"最近活动"徽标（如 `2个新C2 IP · 6月16日`），点击跳转到组织详情页对应 Tab

#### 威胁组织详情页（`/threat-intel/groups/:id`）

- 头部：组织名称 + 别名列表 + Watchlist切换按钮
- 基本信息区：归因国家、首次活动、最近活跃、MITRE ID
- ATT&CK技术矩阵（可视化热力图或列表）
- 关联Tab：C2 IP列表 / 木马家族列表 / 已知利用漏洞 / 来源证据

#### 漏洞列表页（`/threat-intel/vulns`）

- 搜索框（CVE编号/关键词）
- 过滤：严重性（high/critical）、供应链相关、CISA KEV
- 表格展示：CVE编号、标题、CVSS、严重性、影响产品、供应链标记、PoC可用性

#### 攻击IP列表页（`/threat-intel/ips`）

- 过滤：按组织、IP类型、状态（active/inactive）
- 表格展示：IP、类型、关联组织、恶意软件家族、GeoIP、首次/最近发现

#### 木马样本列表页（`/threat-intel/malware`）

- 过滤：按组织、类型（RAT/后门/勒索等）、平台
- 卡片列表：家族名、类型、关联组织、样本数、目标平台

#### 海事动态详情页（`/threat-intel/maritime`） — P2

- 时间线列表展示事件
- 过滤：事件类型、严重性、时间范围
- 每条事件含来源链接供人工验证
- `verification_status=unreviewed` 的事件显示待审标记，默认不进入概览最近事件计数

#### Feed运行页（`/threat-intel/feeds`）

- 表格展示每个Feed Pull Run：数据源、触发方式、状态、开始/结束时间、新增/更新/跳过/未映射数量、失败摘要
- 支持按数据源和状态过滤
- 手动触发按钮仅显示给管理员/本地单用户模式

#### 知识图谱页（`/threat-intel/graph`）— P1

全局知识图谱页面，使用 reactflow 渲染 Threat Group、C2 IP、Malware Family、Threat Vulnerability 之间的关联关系。

**布局**：力导向布局，共享基础设施的组织自动聚类。

**默认加载范围**：Watchlist 中的全部组织及其关联实体。

**顶部工具栏**：
| 控件 | 功能 |
|------|------|
| 搜索框 | 按名称/CVE/IP搜索，命中后镜头飞向目标节点 |
| 组织多选下拉 | 选择要展示的组织（默认=Watchlist全部） |
| 节点类型过滤 | 复选框：IP / Malware / Vulnerability |
| 关系强度过滤 | 滑块：只显示 confidence >= 阈值的边 |

**右下角**：常驻图例（节点类型与颜色对照）。

**底部状态栏**：当前渲染的节点数/边数 + 数据新鲜度。

**交互**：
- 单击节点 → 右侧抽屉展示摘要信息（名称、类型、关键指标、来源证据前3条），同时图谱动画平移缩放至该节点为中心
- 点击聚合节点（cluster）→ 后端请求展开数据，替换为真实子节点
- Maritime Intelligence Event 不纳入图谱（独立时间序列维度）

**节点视觉编码**（亮色底 `#F5F7FA` 上的高饱和度双色渐变填充，节点文字/图标用白色确保对比度）：
| 节点类型 | 形状 | 图标 | 渐变配色 |
|---------|------|------|---------|
| Threat Group | 六边形 | Shield | `indigo → violet`（`#6366F1 → #8B5CF6`） |
| C2 IP | 圆形 | Server | `amber → orange`（`#F59E0B → #F97316`） |
| Malware Family | 菱形 | Bug | `rose → red`（`#F43F5E → #DC2626`） |
| Vulnerability (critical) | 圆角矩形 | AlertTriangle | `rose → red`（`#F43F5E → #DC2626`） |
| Vulnerability (high) | 圆角矩形 | AlertTriangle | `amber → orange`（`#F59E0B → #F97316`） |

**边样式**：
| 边类型 | 标签 | 样式 |
|--------|------|------|
| Group → IP | uses_c2 | 实线 |
| Group → Malware | uses_malware | 实线 |
| Group → Vuln (exploited) | exploits | 粗实线 |
| Group → Vuln (targeted/reported) | targets | 虚线 |

**性能策略**：每个组织每类关联节点默认 Top 30，超出合并为聚合节点（如 "C2 IP x67"）；全局图谱初始渲染控制在 100-200 个节点以内。

#### 组织详情页局部图谱（`/threat-intel/groups/:id` 内嵌）— P1

在组织详情页嵌入以该 Threat Group 为中心的局部知识图谱，使用径向布局（组织居中，IP/Malware/Vuln 分布在外圈）。交互方式与全局图谱一致（单击 → 抽屉 + 动画居中）。默认不启用聚类（单组织节点量可控）。

### 7.3 前端状态

- 首次没有数据时显示空状态，并提示执行首次Feed Pull或等待定时任务，不展示假数据。
- 任一Feed失败时，概览页只对受影响卡片显示新鲜度告警，不阻断其他卡片渲染。
- Watchlist为空时，关注组织动态卡片展示"尚未关注组织"并提供进入组织列表的按钮。
- CVSS缺失但属于CISA KEV的漏洞，列表中 `CVSS` 显示为 `待补充`，严重性显示 `high`。
- CVSS存在但低于7.0的CISA KEV漏洞，列表中正常显示CVSS数值，severity显示 `high` 并附 tooltip 说明"因在CISA KEV中而提升为 high"。
- 所有外部链接使用新窗口打开，并显示来源域名，避免把来源正文复制进页面。

---

## 八、MVP分期

### P0 — 第一版交付物

| 层次 | 内容 | 验收标准 |
|------|------|---------|
| 存储 | `threat_intel.sqlite3` + 10张核心ORM表 + 独立Alembic迁移 | 数据库可创建，迁移可运行，外键开启 |
| 存储 | Feed Pull Run运行记录 | 每次手动/定时拉取都有运行记录和计数 |
| 数据接入 | MITRE ATT&CK Groups初始导入脚本 | 不少于150个组织入库；`mitre_id`唯一 |
| 数据接入 | 国内APT别名种子 | 不少于20条中文/厂商别名，可通过中文搜索命中组织 |
| 数据接入 | CISA KEV每日拉取Workflow | KEV漏洞自动upsert；缺CVSS时标记为high且显示待补充 |
| 数据接入 | ThreatFox每日拉取Workflow | C2 IP自动入库并关联组织；无法映射记录计入 `unmapped_count` |
| API | 概览API + 组织列表/详情API + 漏洞列表API + IP列表API + 木马列表API + Feed运行列表API | 前端可消费，列表响应含分页总数 |
| API | Watchlist添加/移除API | 用户可管理关注 |
| 前端 | 导航入口 + 概览页（5卡片+数据新鲜度） | 数据正确展示，Feed失败时局部告警 |
| 前端 | 威胁组织列表页 + 详情页 | 列表/详情/搜索可用 |
| 前端 | Feed运行页 | 可查看最近运行状态和失败原因 |
| 调度 | 2个每日Workflow定时任务 | CISA KEV与ThreatFox每日自动执行 |
| 测试 | Repo/API最小测试 | upsert去重、watchlist、overview、feed run计数通过 |

### P1 — 第二版

| 层次 | 内容 |
|------|------|
| 数据接入 | NVD CVSS>=7.0过滤拉取 |
| 数据接入 | MalwareBazaar + Feodo Tracker + OTX行业搜索 |
| 数据接入 | Exploit-DB PoC可用性标记 |
| 数据接入 | Industry CPE匹配与供应链漏洞标记 |
| 前端 | 漏洞详情页 + 攻击IP详情页 + 木马样本详情页 |
| 前端 | 知识图谱全局页（`/threat-intel/graph`，力导向布局，搜索/过滤/聚类） |
| 前端 | 组织详情页局部图谱（径向布局，Group→IP/Malware/Vuln星形） |
| API | 图谱专用聚合接口（`GET /api/threat-intel/graph`，nodes+edges结构，支持局部/全局/多组织对比/聚类展开） |
| 功能 | Watchlist管理界面 |
| 数据 | APT别名维护界面与批量导入 |
| 运维 | Feed拉取失败通知 |

### P2 — 第三版

| 层次 | 内容 |
|------|------|
| 数据接入 | 海事情报LLM提取（IMO GISIS/UKMTO/ReCAAP） |
| 前端 | 海事动态详情页 |
| 运维 | 情报数据过期淘汰策略（如C2 IP超过90天inactive自动归档） |
| 运维 | 低置信映射人工复核队列 |

---

## 九、技术约束与风险

### 9.1 约束

- 所有公开数据源API调用需遵守各平台Rate Limit和Terms of Service
- 暗网相关数据仅做元数据级感知，不触碰原始非法数据
- 人员情报不涉及，本模块只关注组织/基础设施/漏洞/恶意软件
- 不下载恶意样本，不执行PoC，不主动连接情报中的C2地址
- CISA KEV/NVD/ThreatFox等外部数据必须保留来源URL或来源ID，便于人工追溯
- P0按单用户本地模式交付，但数据库和Watchlist保留 `actor_id`，避免后续RBAC破坏性迁移

### 9.2 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| MITRE ATT&CK组织与ThreatFox C2的关联不精确（命名不一致） | C2 IP无法自动关联到组织 | 维护组织名-MalwareBazaar家族名的映射表，人工校对 |
| CISA KEV的CPE/CVSS数据可能不完整 | 供应链漏洞标记遗漏、评分显示缺失 | P1阶段补充NVD的完整CVSS/CPE交叉匹配；P0显示"待补充" |
| LLM提取海事源质量不稳定 | 事件数据有噪音 | 保留source_url供人工验证，标记LLM置信度 |
| 国内APT命名与MITRE命名无标准映射 | 别名表维护成本高 | 参考奇安信/安恒/360年度报告建立初始映射，持续更新 |
| 同一IP可能被多个组织复用或误报 | 错误归因影响分析 | P0采用最高置信主归属并保留冲突来源；P1引入低置信复核队列 |
| 免费数据源API变更或限流 | Feed失败、数据过期 | Feed Pull Run记录失败详情与上次成功时间，概览页显示新鲜度告警 |

### 9.3 已澄清的PRD歧义

| 原表述/问题 | 澄清后口径 |
|-------------|------------|
| "APT星形模型"是否只支持APT？ | 使用Threat Group作为正式术语，覆盖APT、犯罪团伙、国家级组织等命名对手 |
| "所有其他维度通过组织ID关联"是否包括漏洞和海事事件？ | 不包括。漏洞可独立存在，只有明确组织利用证据才建立组织-漏洞关联；海事事件独立存储 |
| CISA KEV是否都能按CVSS>=7过滤？ | 不能。P0直接纳入KEV，CVSS/CPE由P1 NVD补充 |
| 供应链相关是否表示供应链攻击归因？ | 不是。仅表示漏洞影响的CPE命中交通/海事行业产品清单 |
| Threat Intel是否能写入CMDB漏洞？ | 不能。只允许前端查询匹配后展示徽标或提示 |
| 手动Feed拉取是否只是调试接口？ | 不是。它是管理员运维能力，和定时任务共享同一套运行记录 |
| 国内APT别名是否可以后置？ | 搜索"海莲花"等中文别名是核心场景，P0至少需要种子映射 |
| `is_watched` 是否应作为 Threat Group 表的数据库列？ | 不是。`is_watched` 是 API 响应计算字段，由 Watchlist 表按 `actor_id` JOIN 得出，避免多用户场景下的状态冲突 |
| 同一 IP/木马被多个组织使用时如何在图谱展示共享？ | 数据库按 `group_id` upsert 不变；图谱 API 返回时按 `ip_address` 或 `lower(family_name)` 归并为单节点，边分别连到各自组织 |
| CISA KEV 中 CVSS < 7.0 的漏洞 severity 如何赋值？ | CISA KEV 漏洞 `severity` 取 `max(CVSS映射值, high)`——"已知被利用"的威胁优先级高于纯评分 |
| Threat Infrastructure IP 的 `malware_family` 是外键还是标签？ | 来源标签字符串，不与 Threat Malware Family 表外键关联；P1 图谱通过 `lower()` 模糊匹配 |
| 概览 API `watched_groups_activity` 的活动如何计算？ | `last_ingested_at >= now - 7d` 的关注组织新入库记录，按 `group_id + activity_type` 聚合 |
| Threat Group 的 `last_active` 与通用 `last_seen` 是否同一语义？ | 是。统一为 `last_seen`，与通用字段定义和同族实体保持一致 |
| 威胁情报模块使用暗色还是亮色风格？ | 亮色。整个模块采用亮色风格（`#F5F7FA` 底 + 双色渐变节点），Navbar 路由感知切换为亮色变体 |
| 图谱节点用纯色还是渐变？ | 双色渐变填充（Group=indigo→violet，IP=amber→orange，Malware=rose→red，Vuln 按严重性），文字/图标白色 |

### 9.4 P0验收检查清单

- 运行迁移后可创建 `threat_intel.sqlite3`，并启用外键。
- 重复执行MITRE/CISA KEV/ThreatFox导入不会产生重复Threat Group、Threat Vulnerability或Threat Infrastructure IP。
- `GET /api/threat-intel/overview` 在空库、部分Feed失败、正常数据三种状态下均返回可渲染结构。
- 组织列表能用 MITRE 名称、英文别名、中文别名搜索同一组织。
- Watchlist添加/移除幂等，重复添加不报500。
- CISA KEV缺CVSS时前端显示 `待补充`，不会把 `null` 渲染为0分。
- ThreatFox无法映射组织的记录不会创建伪组织，Feed Run的 `unmapped_count` 增加。
- CMDB资产/漏洞表没有因Threat Intel Feed Pull产生新增或状态变更。

---

## 十、附录

### 附录A：数据源网址

| 数据源 | 网址 |
|--------|------|
| MITRE ATT&CK Groups | https://attack.mitre.org/groups/ |
| CISA KEV | https://www.cisa.gov/known-exploited-vulnerabilities-catalog |
| abuse.ch ThreatFox | https://threatfox.abuse.ch |
| abuse.ch Feodo Tracker | https://feodotracker.abuse.ch |
| abuse.ch MalwareBazaar | https://bazaar.abuse.ch |
| NVD | https://nvd.nist.gov |
| AlienVault OTX | https://otx.alienvault.com |
| Exploit-DB | https://www.exploit-db.com |
| IMO GISIS | https://gisis.imo.org |
| UKMTO | https://www.ukmto.org |
| ReCAAP ISC | https://www.recaap.org |

### 附录B：关联文档

- [CONTEXT.md](../CONTEXT.md) — 领域术语表（Threat Intelligence Glossary章节）
- [ADR-0003](../docs/adr/0003-threat-intelligence-as-independent-apt-centric-workspace.md) — 架构决策记录
- [开源情报.md](../开源情报.md) — 公开数据源完整调研
