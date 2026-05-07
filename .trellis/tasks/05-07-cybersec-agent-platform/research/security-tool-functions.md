# Research: Security Tool → Function → Skill Mapping Blueprint

- **Query**: 为 secbot baseline 三步流程 + 高危弱口令 + 报告生成准备 fscan / nmap / nuclei / hydra / masscan 的 "工具→功能→skill" 映射蓝图
- **Scope**: external（工具官方文档 + CLI 手册）
- **Date**: 2026-05-07
- **Audience**: ADR-006 PR6 任务的 implement agent
- **约束**：所有 CLI 模板可被 `shlex.split` 解析（无 `|` `>` `&&` `;` 等 shell 元字符）；`{{var}}` 为占位符，由 skill 层在白名单校验后注入。

---

## 1. fscan —— 国产综合扫描器（shadow1ng/fscan）

### 1.1 官方资料

| 项 | 值 |
|---|---|
| Repo | https://github.com/shadow1ng/fscan |
| 最新稳定版 | **2.0.0**（2024-Q4，重构为模块化架构；1.8.4 仍是单机用户主流）|
| Wiki | https://github.com/shadow1ng/fscan/wiki |
| 协议 | MIT |
| 二进制 | 单文件 Go 编译，约 30 MB |

### 1.2 功能矩阵（→ skill）

| # | 子功能 | 建议 skill 名 | 风险等级 |
|---|---|---|---|
| 1 | ICMP / ARP 主机存活探测 | `fscan-host-discovery` | low |
| 2 | TCP 端口扫描（含常用 100 端口预设） | `fscan-port-scan` | low |
| 3 | 服务/Banner 识别（MySQL / Redis / SSH / SMB） | `fscan-service-detect` | low |
| 4 | Web 指纹与标题抓取 | `fscan-web-fingerprint` | low |
| 5 | 内置 PoC 漏洞扫描（MS17-010 / Shiro550 / Weblogic / Struts2 / Druid 等） | `fscan-vuln-scan` | high |
| 6 | 多服务弱口令爆破（SSH/RDP/MySQL/MSSQL/PG/Redis/Oracle/FTP/MongoDB/SMB/Memcached/Telnet） | `fscan-weak-password` | **critical** |
| 7 | 资产探测一体化（host+port+service 一键） | `fscan-asset-discovery` | medium |

### 1.3 CLI 模板（每个 skill 一例）

```text
# fscan-host-discovery（仅存活）
fscan -h {{target}} -m icmp -no -nopoc -nobr -o {{out_file}}

# fscan-port-scan
fscan -h {{target}} -p {{port_range}} -nopoc -nobr -t {{concurrency}} -o {{out_file}}

# fscan-service-detect（端口扫描 + 服务识别，关闭 PoC 与暴破）
fscan -h {{target}} -p {{port_range}} -nopoc -nobr -o {{out_file}}

# fscan-web-fingerprint
fscan -h {{target}} -p 80,443,8080,8443 -nopoc -nobr -o {{out_file}}

# fscan-vuln-scan（开 PoC，关暴破）
fscan -h {{target}} -p {{port_range}} -nobr -o {{out_file}}

# fscan-weak-password（仅指定服务，强约束字典）
fscan -h {{target}} -p {{port_range}} -m {{service}} -nopoc -userf {{user_dict}} -pwdf {{pwd_dict}} -t {{concurrency}} -o {{out_file}}

# fscan-asset-discovery（默认扫描套餐）
fscan -h {{target}} -nopoc -nobr -t {{concurrency}} -o {{out_file}}
```

### 1.4 输入参数 schema

```python
target: str            # CIDR | IPv4 | hostname；regex 校验
port_range: str        # "1-65535" | "80,443,8080"；仅 [0-9,-] 字符
concurrency: int       # default 600，max 2000
service: Literal["ssh","rdp","mysql","mssql","postgres","redis","oracle","ftp","mongodb","smb","memcached","telnet"]
user_dict: Path        # 必须落在 secbot 受控字典目录（白名单）
pwd_dict: Path         # 同上；行数上限 10000 防 DoS
out_file: Path         # 由 skill 自动生成，写入 task workspace
timeout_sec: int       # default 600
```

### 1.5 输出格式

- **原生**：stdout 彩色文本 + `-o result.txt` 行式日志（`[+] 192.168.1.10:22 ssh weak password root:123456` 风格）
- **喂 LLM 的摘要 JSON（裁剪版）**：

```json
{
  "tool": "fscan",
  "skill": "fscan-vuln-scan",
  "target": "192.168.1.0/24",
  "duration_sec": 142,
  "alive_hosts": 18,
  "open_ports_total": 73,
  "findings": [
    {"host": "192.168.1.10", "port": 445, "type": "vuln",
     "name": "MS17-010", "severity": "critical", "evidence": "EternalBlue PoC OK"},
    {"host": "192.168.1.20", "port": 6379, "type": "weak_password",
     "name": "redis-unauth", "severity": "high"}
  ],
  "raw_log_path": ".secbot/runs/{run_id}/fscan-vuln-scan.txt"
}
```

### 1.6 危险等级

- `low`: host-discovery / port-scan / service-detect / web-fingerprint
- `medium`: asset-discovery（量较大）
- `high`: vuln-scan（部分 PoC 有写马动作，需在受控网内）
- **`critical`**: `fscan-weak-password`（强制走 ask-user 二次确认 + 默认禁用）

### 1.7 依赖与安装

| 平台 | 命令 |
|---|---|
| Linux | `wget https://github.com/shadow1ng/fscan/releases/download/2.0.0/fscan_amd64 -O /usr/local/bin/fscan && chmod +x /usr/local/bin/fscan` |
| macOS | `brew install --no-quarantine fscan`（无官方 brew，建议从 Releases 下载 `fscan_darwin_arm64` / `_amd64`，手动 `chmod +x`）|
| 内嵌字典 | 二进制内置常用弱口令字典，无需额外文件 |

### 1.8 跨平台兼容

- Windows: ✅ 官方提供 `fscan.exe`；ARP 探测需管理员
- Linux: ICMP 探测需 root（或 setcap cap_net_raw）；TCP-Connect 端口扫描不需要
- macOS: 同 Linux，建议 sudo 运行

### 1.9 命令注入风险点

| 字段 | 校验规则 |
|---|---|
| `target` | `^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$` 或合法 hostname；禁 `;` `&` `|` `$` ``` |
| `port_range` | `^[0-9,\-]+$`，长度 ≤ 256 |
| `service` | `Literal` 枚举校验 |
| `user_dict / pwd_dict` | `Path.resolve()` 必须以受控目录为前缀 |
| `out_file` | 同上 |

---

## 2. nmap —— 行业标杆（nmap.org）

### 2.1 官方资料

| 项 | 值 |
|---|---|
| 官网 | https://nmap.org |
| 最新稳定版 | **7.95**（2024-09）|
| 文档 | https://nmap.org/book/man.html |
| 协议 | NPSL（类 GPLv2 + 反商业 SaaS）|

### 2.2 功能矩阵

| # | 子功能 | 建议 skill 名 | 风险等级 |
|---|---|---|---|
| 1 | Ping/ARP 存活扫描（`-sn`） | `nmap-host-discovery` | low |
| 2 | TCP SYN 端口扫描（`-sS`） | `nmap-port-scan` | low |
| 3 | 全连接扫描（`-sT`，无需 root） | `nmap-port-scan-connect` | low |
| 4 | UDP 端口扫描（`-sU`） | `nmap-udp-scan` | medium |
| 5 | 服务/版本指纹（`-sV`） | `nmap-service-fingerprint` | low |
| 6 | OS 指纹（`-O`） | `nmap-os-fingerprint` | low |
| 7 | 默认脚本（`-sC` ≈ `--script=default`） | `nmap-default-scripts` | low |
| 8 | 漏洞 NSE（`--script vuln`） | `nmap-vuln-scripts` | high |

### 2.3 CLI 模板

```text
# nmap-host-discovery（无端口扫描）
nmap -sn -PE -PA80,443 -n -oX {{out_xml}} {{target}}

# nmap-port-scan（SYN，需 root）
nmap -sS -p {{port_range}} -T{{timing}} -n -Pn -oX {{out_xml}} {{target}}

# nmap-port-scan-connect（无 root）
nmap -sT -p {{port_range}} -T{{timing}} -n -Pn -oX {{out_xml}} {{target}}

# nmap-udp-scan（慢，端口受限）
nmap -sU -p {{port_range}} -T{{timing}} -n -Pn --max-retries 1 -oX {{out_xml}} {{target}}

# nmap-service-fingerprint
nmap -sV -p {{port_range}} --version-intensity {{intensity}} -n -Pn -oX {{out_xml}} {{target}}

# nmap-os-fingerprint
nmap -O -n -Pn --osscan-limit -oX {{out_xml}} {{target}}

# nmap-default-scripts
nmap -sC -sV -p {{port_range}} -n -Pn -oX {{out_xml}} {{target}}

# nmap-vuln-scripts
nmap --script vuln -p {{port_range}} -n -Pn -oX {{out_xml}} {{target}}
```

### 2.4 输入参数 schema

```python
target: str            # CIDR | IP-range | hostname；多目标用空格分隔（skill 层拼装）
port_range: str        # "1-1024" | "80,443"；regex [0-9,\-]+
timing: Literal["0","1","2","3","4","5"]  # default "4"，禁 "5"（极易丢包）
intensity: int         # 0–9，default 7
out_xml: Path          # 受控目录
```

### 2.5 输出格式

- **原生**：stdout 文本 + `-oX` XML（**首选**，结构化稳定）+ `-oN` 文本 + `-oG` grepable
- **解析**：Python `python-libnmap` 或 `xml.etree` 解析 XML
- **摘要 JSON**：

```json
{
  "tool": "nmap",
  "skill": "nmap-port-scan",
  "target": "192.168.1.10",
  "duration_sec": 23,
  "hosts": [
    {"ip": "192.168.1.10", "state": "up", "os_guess": null,
     "ports": [
       {"port": 22, "proto": "tcp", "state": "open", "service": "ssh", "version": "OpenSSH 8.9"},
       {"port": 80, "proto": "tcp", "state": "open", "service": "http", "version": "nginx 1.22.0"}
     ]}
  ],
  "raw_log_path": ".secbot/runs/{run_id}/nmap-port-scan.xml"
}
```

### 2.6 危险等级

- `low`：所有非 vuln 脚本 + 服务指纹
- `medium`：UDP 扫描（耗时 + 部分服务可能崩溃）
- `high`：`--script vuln`（含部分 DoS 类脚本，需配 `--script-args unsafe=0`）

### 2.7 依赖与安装

| 平台 | 命令 |
|---|---|
| Linux (apt) | `sudo apt-get install -y nmap` |
| Linux (yum) | `sudo yum install -y nmap` |
| macOS | `brew install nmap` |
| Python 解析 | `pip install python-libnmap` |

### 2.8 跨平台兼容

- Windows: ✅ 官方安装包，含 Npcap；SYN 扫描需管理员
- Linux/macOS: SYN/UDP/OS 指纹需 root；Connect 扫描无需

### 2.9 命令注入风险点

| 字段 | 校验 |
|---|---|
| `target` | 拒绝包含 `-`（避免被解析为 nmap 选项），仅允许 IP/CIDR/合法 hostname |
| `port_range` | `^[0-9,\-]+$`，长度 ≤ 256 |
| `timing` | 枚举 |
| `out_xml` | 受控目录前缀 |

> ⚠️ nmap 支持 `--script` 加载任意 NSE 脚本，**禁止**让 LLM 自由指定脚本路径，必须维护白名单（`vuln`, `default`, `safe`, 单脚本名）。

---

## 3. nuclei —— 模板化漏洞扫描（projectdiscovery/nuclei）

### 3.1 官方资料

| 项 | 值 |
|---|---|
| Repo | https://github.com/projectdiscovery/nuclei |
| 最新稳定版 | **v3.3.x**（2025 年初；v3 起为默认主线，v2 已停维护）|
| 模板库 | https://github.com/projectdiscovery/nuclei-templates（持续更新，>9000 模板）|
| 文档 | https://docs.projectdiscovery.io/tools/nuclei/overview |
| 协议 | MIT |

### 3.2 功能矩阵

| # | 子功能 | 建议 skill 名 | 风险等级 |
|---|---|---|---|
| 1 | 全模板库扫描（按 severity 过滤） | `nuclei-template-scan` | high |
| 2 | 仅运行单个 Tag/CVE 模板 | `nuclei-single-template` | medium |
| 3 | 自定义模板路径执行 | `nuclei-custom-template` | high（仅内部用，禁 LLM 自由传入）|
| 4 | DAST/Fuzz 模式 | `nuclei-dast-fuzz` | high |
| 5 | SSL/TLS 检查（`ssl` workflow） | `nuclei-ssl-audit` | low |
| 6 | 模板库更新（系统类，非业务 skill） | `nuclei-templates-update` | low |

### 3.3 CLI 模板

```text
# nuclei-template-scan（按严重度过滤）
nuclei -u {{target_url}} -severity {{severity}} -j -o {{out_jsonl}} -timeout {{timeout}} -rl {{rate_limit}}

# nuclei-single-template（按 ID 跑单条）
nuclei -u {{target_url}} -id {{template_id}} -j -o {{out_jsonl}}

# nuclei-custom-template（受控目录）
nuclei -u {{target_url}} -t {{template_path}} -j -o {{out_jsonl}}

# nuclei-dast-fuzz
nuclei -u {{target_url}} -dast -j -o {{out_jsonl}} -rl {{rate_limit}}

# nuclei-ssl-audit
nuclei -u {{target_url}} -tags ssl -j -o {{out_jsonl}}

# nuclei-templates-update（无需 target）
nuclei -update-templates
```

### 3.4 输入参数 schema

```python
target_url: str        # http://… | https://… ；urlparse 校验，禁 file://、ftp://
severity: Literal["info","low","medium","high","critical"]  # default "high,critical"
template_id: str       # ^[a-zA-Z0-9_-]+$
template_path: Path    # 受控模板目录前缀（如 secbot 内置 ./templates/）
rate_limit: int        # default 150 req/s，max 500
timeout: int           # default 10s
out_jsonl: Path        # 受控目录
concurrency: int       # default 25，max 100
```

### 3.5 输出格式

- **原生**：stdout 彩色 + `-j -o file.jsonl`（每行一个 JSON 结果）
- **JSONL 单行示例**：

```json
{"template-id":"CVE-2021-44228","info":{"name":"Log4j RCE","severity":"critical","tags":["cve","rce"]},"host":"https://x.com","matched-at":"https://x.com/api/login","timestamp":"2026-05-07T10:11:12Z"}
```

- **喂 LLM 的摘要 JSON**：

```json
{
  "tool": "nuclei",
  "skill": "nuclei-template-scan",
  "target": "https://x.com",
  "templates_loaded": 4821,
  "duration_sec": 87,
  "findings": [
    {"id":"CVE-2021-44228","name":"Log4j RCE","severity":"critical","matched_at":"https://x.com/api/login"}
  ],
  "by_severity": {"critical":1,"high":0,"medium":2,"low":5,"info":12},
  "raw_log_path": ".secbot/runs/{run_id}/nuclei.jsonl"
}
```

### 3.6 危险等级

- `low`: SSL audit / templates-update
- `medium`: 单模板（受控）
- `high`: 全库扫描 / DAST（部分 PoC 含真实 payload，可能被 WAF 触发或对靶机造成影响）

### 3.7 依赖与安装

| 平台 | 命令 |
|---|---|
| Go 安装 | `go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest` |
| Linux (snap) | `sudo snap install nuclei` |
| macOS | `brew install nuclei` |
| 模板初始化 | `nuclei -update-templates`（首次必跑，约 200 MB）|

### 3.8 跨平台兼容

- Windows: ✅；无需管理员（除非扫本机端口）
- Linux/macOS: 普通用户即可；扫描 <1024 本机端口时需 root

### 3.9 命令注入风险点

| 字段 | 校验 |
|---|---|
| `target_url` | `urllib.parse.urlparse` + scheme 白名单 `{http,https}` |
| `template_id` | 严格 regex |
| `template_path` | 受控目录前缀 + `Path.resolve()` |
| `severity` | 枚举 |

> ⚠️ nuclei 的 `-headless` 与 `-it` 交互模板可执行任意 JS/HTTP，secbot 默认 **禁用** `-headless`、不允许 LLM 透传 `-iv` 等高危参数。

---

## 4. hydra —— 网络服务弱口令爆破（vanhauser-thc/thc-hydra）

### 4.1 官方资料

| 项 | 值 |
|---|---|
| Repo | https://github.com/vanhauser-thc/thc-hydra |
| 最新稳定版 | **9.5**（2023-05；社区主流；2024-2025 仅小修补）|
| 协议 | AGPLv3 |

### 4.2 功能矩阵

| # | 子功能 | 建议 skill 名 | 风险等级 |
|---|---|---|---|
| 1 | SSH 弱口令爆破 | `hydra-ssh-bruteforce` | **critical** |
| 2 | RDP 弱口令爆破 | `hydra-rdp-bruteforce` | **critical** |
| 3 | FTP 弱口令爆破 | `hydra-ftp-bruteforce` | **critical** |
| 4 | SMB 弱口令爆破 | `hydra-smb-bruteforce` | **critical** |
| 5 | HTTP-Form POST 爆破 | `hydra-http-form-bruteforce` | **critical** |
| 6 | MySQL / MSSQL / PostgreSQL 数据库爆破 | `hydra-db-bruteforce` | **critical** |

> 设计建议：所有 hydra 子 skill **共享一个底层 runner**，按 `service` 参数路由，对外仍暴露独立 skill 名以便 LLM 精准选择 + 二次确认提示语贴合场景。

### 4.3 CLI 模板（每协议一例）

```text
# hydra-ssh-bruteforce
hydra -L {{user_dict}} -P {{pwd_dict}} -t {{tasks}} -f -o {{out_file}} ssh://{{target}}:{{port}}

# hydra-rdp-bruteforce
hydra -L {{user_dict}} -P {{pwd_dict}} -t {{tasks}} -f -o {{out_file}} rdp://{{target}}:{{port}}

# hydra-ftp-bruteforce
hydra -L {{user_dict}} -P {{pwd_dict}} -t {{tasks}} -f -o {{out_file}} ftp://{{target}}:{{port}}

# hydra-smb-bruteforce
hydra -L {{user_dict}} -P {{pwd_dict}} -t {{tasks}} -f -o {{out_file}} smb://{{target}}:{{port}}

# hydra-http-form-bruteforce（form 串需在 skill 层经模板生成，禁 LLM 直接拼装）
hydra -L {{user_dict}} -P {{pwd_dict}} -t {{tasks}} -f -o {{out_file}} {{target}} http-post-form {{form_template}}

# hydra-db-bruteforce（mysql / mssql / postgres / oracle）
hydra -L {{user_dict}} -P {{pwd_dict}} -t {{tasks}} -f -o {{out_file}} {{db_service}}://{{target}}:{{port}}
```

### 4.4 输入参数 schema

```python
target: str            # 单 IP / hostname；禁 CIDR（hydra 不支持）
port: int              # 1–65535
user_dict: Path        # 受控目录；行数 ≤ 1000
pwd_dict: Path         # 受控目录；行数 ≤ 10000
tasks: int             # default 4，max 16（防触发账户锁定）
out_file: Path         # 受控目录
db_service: Literal["mysql","mssql","postgres","oracle"]
form_template: str     # 例 "/login.php:user=^USER^&pass=^PASS^:F=incorrect"
                       # 必须在受控模板表中，禁 LLM 自由拼接
```

### 4.5 输出格式

- **原生**：stdout 文本 + `-o file` 命中行
- **典型成功行**：`[22][ssh] host: 192.168.1.10   login: root   password: 123456`
- **摘要 JSON**：

```json
{
  "tool": "hydra",
  "skill": "hydra-ssh-bruteforce",
  "target": "192.168.1.10",
  "port": 22,
  "service": "ssh",
  "tried": 5000,
  "duration_sec": 122,
  "credentials": [
    {"username": "root", "password": "123456"}
  ],
  "raw_log_path": ".secbot/runs/{run_id}/hydra-ssh.txt"
}
```

### 4.6 危险等级

- **全部 critical**。元数据强制：`risk_level: critical`、`require_confirmation: true`、`default_disabled: true`。
- 二次确认提示需明示 "目标可能触发账户锁定 / 安全告警 / 法律风险"。

### 4.7 依赖与安装

| 平台 | 命令 |
|---|---|
| Linux (apt) | `sudo apt-get install -y hydra hydra-gtk` |
| Linux (yum) | `sudo yum install -y hydra` |
| macOS | `brew install hydra` |
| 编译依赖 | libssl, libssh, libidn, libpcre, libmysql；macOS 上 brew 自动处理 |

### 4.8 跨平台兼容

- Windows: ⚠️ 官方仅有源码，无官方二进制；建议 WSL 内运行
- Linux/macOS: ✅ 普通用户即可

### 4.9 命令注入风险点

| 字段 | 校验 |
|---|---|
| `target` | regex IPv4 / hostname；禁 `:` 之外的特殊符号 |
| `port` | `int`，范围校验 |
| `form_template` | **必须**来自 skill 内置模板表（dict lookup），不接受 LLM 直接传入字符串 |
| `db_service` | 枚举 |
| 字典路径 | 受控目录 + 行数上限 |

> ⚠️ 额外加固：runner 必须在调用前校验 `target` 不在公网保留段（除非用户显式 ack）；命中即终止（`-f`）减少噪声。

---

## 5. masscan —— 大规模端口扫描（robertdavidgraham/masscan）

### 5.1 官方资料

| 项 | 值 |
|---|---|
| Repo | https://github.com/robertdavidgraham/masscan |
| 最新稳定版 | **1.3.2**（2023-11；2024-2025 极少变更，社区稳定）|
| 协议 | AGPLv3 |
| 特点 | 用户态 TCP/IP 栈，单机可达 10M pps |

### 5.2 功能矩阵

| # | 子功能 | 建议 skill 名 | 风险等级 |
|---|---|---|---|
| 1 | 大规模 TCP SYN 端口扫描 | `masscan-port-scan` | medium |
| 2 | Banner 抓取（`--banners`） | `masscan-banner-grab` | medium |

> 注：masscan 没有完整的服务指纹/PoC，定位为 "广度扫描器"，深度交给 nmap/nuclei。

### 5.3 CLI 模板

```text
# masscan-port-scan
masscan {{target}} -p {{port_range}} --rate {{rate}} -oJ {{out_json}} --wait {{wait_sec}}

# masscan-banner-grab（开 banner，速率必须降）
masscan {{target}} -p {{port_range}} --banners --rate {{rate}} -oJ {{out_json}} --wait {{wait_sec}}
```

### 5.4 输入参数 schema

```python
target: str            # CIDR | IP；支持 `--exclude` 黑名单（skill 内置）
port_range: str        # "0-65535" | "80,443"；regex [0-9,\-]+
rate: int              # default 1000，max 10000（再高需运维显式调）
wait_sec: int          # default 3；扫完后等待回包秒数
out_json: Path         # 受控目录
```

### 5.5 输出格式

- **原生**：`-oJ` JSON / `-oX` XML / `-oG` grepable / `-oL` 行式列表
- **JSON 单条**：

```json
{"ip":"192.168.1.10","timestamp":"1746604800","ports":[{"port":22,"proto":"tcp","status":"open","reason":"syn-ack","ttl":64}]}
```

- **摘要 JSON**：

```json
{
  "tool": "masscan",
  "skill": "masscan-port-scan",
  "target": "10.0.0.0/16",
  "rate_pps": 1000,
  "duration_sec": 614,
  "hosts_with_open_ports": 213,
  "open_ports_total": 1024,
  "top_ports": [{"port":80,"count":189},{"port":443,"count":167}],
  "raw_log_path": ".secbot/runs/{run_id}/masscan.json"
}
```

### 5.6 危险等级

- `medium`: 速率高 → 可能被 IDS 报警 + 触发上游限速；secbot 默认 cap rate=1000，>5000 走 ask-user。

### 5.7 依赖与安装

| 平台 | 命令 |
|---|---|
| Linux (apt) | `sudo apt-get install -y masscan` |
| Linux (源码) | `git clone https://github.com/robertdavidgraham/masscan && cd masscan && make && sudo make install` |
| macOS | `brew install masscan` |
| 运行依赖 | libpcap |

### 5.8 跨平台兼容

- Windows: ⚠️ 实验性支持，需 WinPcap/Npcap，**不推荐**
- Linux/macOS: 必须 root（用户态原始套接字）

### 5.9 命令注入风险点

| 字段 | 校验 |
|---|---|
| `target` | 同 nmap，拒绝 `-` 开头与 shell 元字符 |
| `port_range` | regex |
| `rate` | int 范围；强 cap |
| `out_json` | 受控目录 |

> ⚠️ secbot 必须维护 `--exclude` 文件包含 RFC1918 之外的保留段（如 169.254/16、224/4）以及用户外网公司 IP 黑名单，runner 默认追加。

---

## 6. 总览 / 决策

### 6.1 全集 skill 数量统计

| 工具 | skill 数 | 其中 critical |
|---|---|---|
| fscan | 7 | 1 |
| nmap | 8 | 0 |
| nuclei | 6 | 0 |
| hydra | 6 | 6 |
| masscan | 2 | 0 |
| **合计** | **29** | **7** |

### 6.2 推荐 P0 skill 清单（MVP 6 个，对应 ADR-006 PR6）

> 选择原则：覆盖 baseline 三步流程（资产→端口→漏洞）+ 1 个高危样本（验证二次确认链路）+ 报告类不在此列（独立 PR）。

| # | skill | 工具 | 阶段 | risk |
|---|---|---|---|---|
| 1 | `nmap-host-discovery` | nmap | 资产探测 | low |
| 2 | `fscan-asset-discovery` | fscan | 资产探测（一体化兜底）| medium |
| 3 | `nmap-port-scan-connect` | nmap | 端口扫描（无需 root，CI/容器友好）| low |
| 4 | `nmap-service-fingerprint` | nmap | 服务识别 | low |
| 5 | `nuclei-template-scan` | nuclei | 漏洞扫描 | high |
| 6 | `hydra-ssh-bruteforce` | hydra | 弱口令（critical 链路验证）| **critical** |

> 备选（若工期紧可砍）：`fscan-vuln-scan`（与 nuclei 重叠，作为内网兜底）、`masscan-port-scan`（仅 /16 以上目标启用）。

### 6.3 MCP 化潜力评估

> 评估维度：① 是否有清晰的"工具→子命令"边界 ② 是否值得复用到其他 LLM 客户端（Claude Desktop / Cursor / 其他 agent 框架） ③ 输出是否易结构化

| 工具 | MCP 化优先级 | 理由 |
|---|---|---|
| **nuclei** | ⭐⭐⭐ 最高 | 模板化 + JSONL 输出 + 社区已有 mcp-nuclei 雏形；功能切片清晰；幂等性好 |
| **nmap** | ⭐⭐⭐ 高 | XML 输出结构稳定；子命令众多但语义独立；适合作 "标准能力 server" 复用 |
| **masscan** | ⭐⭐ 中 | 功能少（端口/banner），单独 MCP server 价值有限，可与 nmap 合并为 "port-scan server" |
| **fscan** | ⭐ 低 | 国产 + 功能耦合强（PoC 与暴破混在一起）+ 输出非结构化（行式日志），MCP 化前需自行包装 JSON 摘要层；建议先维持 subprocess+skill |
| **hydra** | ✗ 不建议 | critical 风险 + 法律敏感 + 输出简单，建议**始终**走 secbot 内 ask-user 控制流，不暴露 MCP |

**演进建议**：先全量走 subprocess + skill，待 nuclei/nmap 稳定后抽出 `secbot-mcp-nuclei` / `secbot-mcp-nmap` 两个独立 MCP server，给外部生态复用；fscan 与 hydra 保留在 secbot 闭环内。

---

## 7. 跨工具实施约束（给 implement agent）

1. **统一 runner**：`secbot/skills/_runner.py` 提供 `run_subprocess(argv: list[str], timeout: int, cwd: Path) -> RunResult`，禁止任何 skill 直接 `subprocess.Popen` 拼字符串。
2. **白名单二次封装**：每个 skill 的 `args_to_argv()` 函数负责 schema → argv 转换，必须 100% 单元测试覆盖（含 fuzz 注入用例：`target="1.1.1.1; rm -rf /"`）。
3. **输出双轨**：原始日志写 `.secbot/runs/{run_id}/{skill}.{ext}`；摘要 JSON 内联返回 LLM；摘要中只引 `raw_log_path` 字符串。
4. **超时与杀死**：所有 subprocess 必须设 `timeout`；超时调 `Process.kill()` + 标记 `status: "timeout"`，避免悬挂任务卡死 expert agent。
5. **并发沙盒**：同一 skill 同 run_id 内串行；不同 run_id 之间通过 `asyncio.Semaphore(MAX_CONCURRENT_SCANS)` 限流。

---

## Caveats / Not Found

- fscan 2.0 重构后部分 1.x 参数（如 `-no` 简写）行为有差异，正式集成前需在 sandbox 跑 `fscan --help` 二次核对。
- nuclei v3 的 `-dast` 参数在 v3.2 之前为实验性，secbot 集成时需要锁定 `>=v3.3`。
- hydra HTTP-Form 模板字符串的复杂度极高（含 `^USER^` `^PASS^` `F=` 等），首批仅实现 SSH/RDP/FTP/SMB/DB 五类，HTTP-Form 推到 P1。
- masscan 在 macOS 下必须用 sudo 且 brew 版本偶尔与 1.3.2 源码版本有出入，CI 矩阵建议双跑。
- 所有版本号截至 2026-05-07 训练知识；正式选型前应再次 `tool --version` 核对。
