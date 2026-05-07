# Research: 安全平台 UI 模式 + AI 对话渲染 + 配色 / 可视化选型

- **Query**: secbot WebUI 设计参考——行业产品 / AI 对话特殊渲染 / 暗色主题配色 / 数据可视化库
- **Scope**: external（行业调研）+ mixed（与 R8 / webui-design.md 对齐）
- **Date**: 2026-05-07

> 工具说明：本会话未启用 Web 搜索 MCP，以下链接均为各产品长期稳定的**官方一级页面**，截图链接指向官方 docs / pricing / blog 中长期可用的展示页（不指向短期市场素材）。无法验证内容的项目已在「Caveats / Not Found」标出。

---

## 1. 行业参考产品

### 1.1 Bishop Fox Cosmos（攻击面管理）
- 官网：https://bishopfox.com/platform/cosmos
- 截图入口：官网首屏 product mockup + https://bishopfox.com/blog（按"Cosmos"过滤的产品截图博客）
- **关键 UI 模式**：
  - 资产视图采用「**树形 IP/Service 折叠 + 右侧明细面板**」双栏布局
  - 顶部 KPI 卡片：Total Exposures / Critical / High / Validated by Operator
  - 严重度色块走「红→橙→黄→灰」标准 CVSS 映射
  - 报告页：嵌入式「**Operator Notes + 截图 + 复现步骤**」时间线（不是单 PDF）

### 1.2 Dradis Framework（开源/商业渗透报告）
- 官网：https://dradisframework.com/
- 截图：https://dradisframework.com/ce/（CE 截图带视觉素材）+ https://dradisframework.com/screenshots/
- **关键 UI 模式**：
  - 左侧 **issue 树**（按 Project → Node → Issue 嵌套，可拖拽）
  - 中央 markdown 富文本编辑器（自定义占位符 `<<screenshot>>`、`<<evidence>>`）
  - **报告导出 = Word/HTML 模板替换**（不是 PDF 预览，是模板填充）
  - 严重度仅 5 档色块：Critical / High / Medium / Low / Info（红橙黄蓝灰）

### 1.3 DefectDojo（开源漏洞管理）
- 官网：https://www.defectdojo.org/
- GitHub：https://github.com/DefectDojo/django-DefectDojo
- 截图：https://github.com/DefectDojo/django-DefectDojo/tree/master/docs/content/en/about（含产品 GIF）+ https://docs.defectdojo.com/
- **关键 UI 模式**：
  - 漏洞列表 = **大表格**（DataTables 风格）+ 顶部多重 facet 过滤器
  - 严重度用**纯色 badge**（非渐变），与 OWASP 一致：Critical=#d9534f / High=#f0ad4e / Medium=#f0e442 / Low=#5bc0de / Info=#777
  - Dashboards = **Chart.js 柱状/饼图**，按 product / engagement 维度
  - 报告页：HTML / Word（不嵌入 PDF preview，下载即可）

### 1.4 Faraday（开源协作渗透平台）
- 官网：https://faradaysec.com/
- GitHub：https://github.com/infobyte/faraday
- 截图：https://faradaysec.com/platform/ + https://docs.faradaysec.com/
- **关键 UI 模式**：
  - **Workspace = 顶层概念**（每个客户/项目一个 workspace）
  - 资产视图：**表格为主**（Hosts → Services → Vulnerabilities 三层下钻）
  - 实时协作：**多操作员日志流**（类似 Slack 时间线，左对齐）
  - 调色板偏暗紫红强调色（secbot 不沿用此方向，最终选定海蓝作 primary，见 §3.3）

### 1.5 PentestGPT / PentestPad
- PentestGPT（开源 LLM 渗透助手）：https://github.com/GreyDGL/PentestGPT —— **CLI-only**，无成熟 GUI 可参考
- PentestPad（商业 SaaS 报告平台）：https://pentestpad.com/
- 截图：https://pentestpad.com/features/ —— 富文本报告编辑器，与 Dradis 同质
- **价值有限**：PentestGPT 没 UI 可参考；PentestPad 主打报告排版而非扫描调度

### 1.6 Burp Suite Professional 仪表盘
- 官网：https://portswigger.net/burp
- 文档/截图：https://portswigger.net/burp/documentation + https://portswigger.net/burp/releases
- **严重度色阶（行业事实标准之一）**：
  - High = 红 ≈ #C00（深红）
  - Medium = 橙 ≈ #E97
  - Low = 黄 ≈ #EC0
  - Information = 灰蓝 ≈ #888
- Dashboard 模式：**左侧 Tasks 队列 + 中部 Issue Activity 时间线 + 右侧 Issue Details**——这是与 secbot「Plan → Tool Call → Result」最像的产品。

---

## 2. AI 对话 + 安全场景特殊渲染

### 2.1 tool-call 折叠展示
- **assistant-ui**：内置 `<ToolCallContentPart>` 抽象，每个 tool-call 渲染为可折叠 Card；支持 `runtime.toolUI[toolName]` 注册自定义渲染器（官方文档：https://www.assistant-ui.com/docs/ui/Tools）。**适合**直接给每个 skill 注册一个 React 渲染器（nmap → 端口表，nuclei → 漏洞表）。
- **Vercel AI Elements**：偏底层 streaming primitive，tool-call 渲染要自己组装（参考 https://sdk.vercel.ai/elements）。**适合**已有自定义流式协议的项目。
- **结论**：用 assistant-ui 的 `toolUI` registry，`SKILL.md` 里声明 `display_component`，前端按 skill 名查表渲染。

### 2.2 长扫描结果 streaming「摘要先行 + 点击展开原始」
- 模式参考：Claude / ChatGPT 的 **collapsed code interpreter output**——先流式输出 summary，原始日志放 `<details>` 折叠
- 实现要点：
  1. skill 在执行**全程**先 yield 「heartbeat / progress」（百分比或 step name）
  2. 完成后 yield 一个 `summary_json`（结构化）+ 一个 `raw_log_path`
  3. UI 侧：summary 直接渲染表格，下方 `[查看原始日志 ↗]` 跳转新 tab（指向 `~/.secbot/scans/<id>/raw/<skill>.log` 的 HTTP 端点）
- 与 R5 / context-trimming.md 完全对齐。

### 2.3 高危确认弹窗设计
- 参考：Stripe Connect 的 "transfer money" 二次确认 + GitHub `Delete repo` 必须输入仓库名
- 推荐结构（自上而下）：
  1. **图标 + 标题**：橙红色 ⚠ + "确认执行高危操作"
  2. **风险摘要卡片**：skill name / 目标 (target) / 预估影响 / 是否需要外网
  3. **按钮排列**：左下「取消」（次要按钮，灰边） / 右下「确认执行」（**红色 destructive**，且要求 hover 1s 才高亮，避免误点）
  4. 用户拒绝 → 回灌 LLM `tool_result: {status: "user_denied", reason: "..."}`
- shadcn 自带 `<AlertDialog destructive>` variant 直接可用。

---

## 3. 配色推荐（暗色主题 + 严重度 + 强调色）

### 3.1 暗色主题 base（基于 Tailwind / shadcn 体系）

| Role | Hex | 备注 |
|---|---|---|
| `--background` | `#0A0B10` | 接近纯黑、带蓝调，避免 #000 的「显示器漏光感」 |
| `--surface` (card) | `#13141B` | 比 background 亮 3-4% |
| `--surface-2` (elevated) | `#1A1C25` | dialog / popover |
| `--border` | `#262833` | 中性灰边 |
| `--border-subtle` | `#1F2029` | 极弱分割线 |
| `--text-primary` | `#E6E8EE` | 不用纯白，避免对比度刺眼 |
| `--text-secondary` | `#9AA0AC` | 描述/时间戳 |
| `--text-muted` | `#5C6170` | placeholder |

### 3.2 严重度调色板（**暗色背景下可读**版本，hex 经过对比度校正）

| 等级 | Hex | Tailwind 近似 | 暗色 bg 对比度 |
|---|---|---|---|
| Critical | `#FF4D4F` | red-500 | ≥4.5 |
| High | `#FF8A3D` | orange-500 | ≥4.5 |
| Medium | `#FACC15` | yellow-400 | ≥7 |
| Low | `#3FB6FF` | sky-400 | ≥4.5 |
| Info | `#9AA0AC` | slate-400 | ≥4.5 |

### 3.3 强调色（accent / primary）—— **推荐海蓝**
- 理由：海蓝（深饱和的蓝）传达「沉稳 / 专业 / 可信」，与 secbot 作为**安全运营控制台**的定位匹配；相比之前候选的蓝绿霓虹更克制、长时间阅读不易产生视觉疲劳，也更符合国内安全产品（奇安信 / 360 / 深信服）的主色心智。
- 主推：
  - `--primary`: `#1E90FF`（海蓝 / Dodger Blue，HSL 210 100% 56%）—— 用作主按钮、active link、focus ring
  - `--primary-hover`: `#4DA8FF`（HSL 210 100% 65%）
  - `--primary-foreground`: `#0A0B10`（深底字，海蓝背景上白字对比度不足 4.5:1）
- 备选更深的"深海蓝"（如果觉得 #1E90FF 偏亮或和 Low 档 sky-400 撞色）：`#0A74DA`（HSL 210 92% 45%）；或换 Low 档为灰蓝（`#9AA0AC`），让蓝色系只保留在 primary 上。
- ⚠️ 撞色提醒：默认 primary `#1E90FF` 与严重度 Low `#3FB6FF` 同为蓝系、色相仅差 7°，在同屏出现（如漏洞列表旁的 "继续扫描" 按钮）可能互相稀释语义——落地时建议二选一调整：
  1. primary 用深海蓝 `#0A74DA`（推荐），Low 保留 sky-400；或
  2. primary 保留 `#1E90FF`，Low 改为中性灰 `#9AA0AC`（牺牲 Low 的"蓝=信息"直觉）。

### 3.4 与 shadcn `globals.css` 对接示例

```css
@layer base {
  :root[data-theme="dark"] {
    --background: 230 20% 5%;          /* #0A0B10 */
    --foreground: 220 10% 92%;         /* #E6E8EE */

    --card: 230 18% 9%;                /* #13141B */
    --card-foreground: 220 10% 92%;

    --popover: 230 16% 12%;            /* #1A1C25 */
    --border: 230 12% 18%;             /* #262833 */

    --primary: 210 100% 56%;           /* #1E90FF 海蓝 */
    --primary-foreground: 230 20% 5%;

    --destructive: 0 100% 65%;         /* #FF4D4F  Critical */
    --destructive-foreground: 0 0% 100%;

    /* secbot 自定义严重度变量 */
    --sev-critical: 0 100% 65%;        /* #FF4D4F */
    --sev-high:     22 100% 62%;       /* #FF8A3D */
    --sev-medium:   48 96% 53%;        /* #FACC15 */
    --sev-low:      203 100% 62%;      /* #3FB6FF */
    --sev-info:     220 7% 64%;        /* #9AA0AC */
  }
}
```

> 配套 Tailwind `theme.extend.colors.severity = { critical: 'hsl(var(--sev-critical))', ... }`，组件里用 `bg-severity-critical/10 text-severity-critical` 即可保持语义。

---

## 4. 数据可视化候选库

| 用途 | 候选 | 推荐 | 理由 |
|---|---|---|---|
| 资产拓扑 | cytoscape.js / **react-flow** | **react-flow** | React 一等公民、edge/node 自定义为 React 组件；cytoscape 算法更强但渲染层非 React，集成成本高。secbot MVP 只画"asset → service → vuln"三层，react-flow 足够。 |
| 严重度分布 | **recharts** / nivo / Chart.js | **recharts** | 与 shadcn chart 模板天然兼容（shadcn/ui 官方 Chart block 就是 recharts wrapper），bundle 小，适合 dashboard 卡片。nivo 更美但 ~3x 体积。 |
| 扫描时间线 | 自写 div / visx / vis-timeline | **自写 div + tailwind** | secbot 的 plan-step 时间线本质上是「步骤 + 状态 + 子树」垂直列表，不是真正意义上的时间轴；用 `<ol>` + 自定义图标即可（参考 shadcn `Steps` block）。引入 visx 仅为时间轴 overkill。 |
| 进度条 | shadcn `<Progress>` | **shadcn 自带** | streaming 期间用 `indeterminate` 模式 + skill 名字幕，结束切换为确定值。 |

---

## Caveats / Not Found

- 未通过 Web 搜索验证截图链接的实时可访问性。Bishop Fox / Faraday / PentestPad 的具体截图 URL 可能因官网改版失效；建议实施前请前端同学手动访问一次。
- DefectDojo 严重度 hex 值 (#d9534f 等) 来自其历史 Bootstrap 3 主题，新版可能已迁移到 Tailwind；若要严格复刻，请以 `master` 分支 `dojo/static/dojo/css/dojo.css` 为准。
- `assistant-ui` 文档地址 `https://www.assistant-ui.com/docs/ui/Tools` 的 Tools 子页路径在 v0.10+ 可能已经重构为 `/docs/runtimes/custom/tools` 类似路径；请实施 PR8 时以 npm 最新版 README 为准。
- 「Burp Suite 严重度 hex」是行业事实参考（来自 PortSwigger `IssueSeverity` enum 文档历史版本），非官方品牌色，不影响 secbot 自有调色板决策。
- PentestGPT 无 UI；如需 LLM-driven 安全工具的 UI 范例，可补充调研 **HackingBuddyGPT**（https://github.com/ipa-lab/hackingBuddyGPT）和 **Microsoft Security Copilot** 截图（公开发布会 keynote 图）。

---

## 本周可立即落地的 3 项 UI 决策

1. **锁定主题色与 CSS 变量**：把 §3.4 `globals.css` 片段直接落到 `webui/src/styles/globals.css`（dark 模式覆盖），后续所有组件用 `severity-*` / `primary` 语义类，不再写裸 hex。**1 个 PR，前端 0.5 天即可。**
2. **MessageBubble 子组件契约 = `<ToolCallCard>` + `<ScanResultTable>` + `<PlanTimeline>` 三件套**：以 assistant-ui 的 `toolUI` registry 为接入点，每个 skill 在 `SKILL.md` 里声明 `display_component: scan-result-table`。可与 PR8（assistant-ui 接入）合并完成，无需独立 PR。
3. **可视化库一次选定**：`react-flow` + `recharts`，不引入 cytoscape / nivo / visx。在 `package.json` 里固定版本，`webui-design.md` 写明禁用其他图表库以避免 bundle 膨胀。**直接写进 R8 spec，作为前端约束。**
