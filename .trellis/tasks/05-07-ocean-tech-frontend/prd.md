# 酷炫海蓝科技感前端重构

## Goal

为 VAPT3 / secbot 的 React webui 注入"科技感 + 海蓝主题"的视觉语言：在不破坏现有
assistant-ui 对话流和 4 个核心面板（chat / assets / scans / reports）的前提下，
**升级整个 webui（包括 nanobot 主 Shell + secbot Tab）**为中度 HUD 风格（S2），
通过 **shadcn blocks + Tremor Raw + MagicUI + @xyflow/react** 组合实现，最终为
渗透测试与 VAPT 研判分析师提供"既好看又信息密度高"的工作站体验。

## Requirements

### R1 主题与设计 token（海蓝 + 双主色）

- 在 `webui/src/globals.css` 的 `:root[data-theme="secbot"]` 块中新增/重写：
  - `--primary: 210 100% 56%` （**保留** `#1E90FF` Dodger Blue 作交互高亮）
  - `--brand-deep: 204 86% 36%` （**新增** `#0E6BA8` 作 sidebar / hero / brand badge）
  - `--brand-light: 210 100% 74%` （**新增** `#7AB8FF` 作 hover overlay / link visited）
  - 完整 8 步 Blue ramp（50 → 900），见上面色盘
  - `--success / --warning / --error / --info` HSL token 新增（与 severity 调色对齐）
- 同步 light 主题海蓝化（bg `#F4F8FD` · fg `#062E4D`），保持 WCAG AA
- `tailwind.config.js` 扩展：
  - `colors.brand-deep / brand-light / success / warning / error / info`
  - `boxShadow.glow-primary / glow-brand`（`0 0 20px hsl(var(--primary) / 0.4)` 形式）

### R2 PR0 / Phase 0 — 修复 SecbotThread 的 v0.10 API 不匹配（**前置依赖**）

- `webui/src/secbot/SecbotThread.tsx:5` 当前 import `Thread`，但 `@assistant-ui/react@0.10.x`
  并不导出 `Thread`（v0.7 后已移除）。`<Thread tools={SKILL_RENDERERS} components={...}>`
  签名也不匹配。
- 重写为 v0.10 正确签名：`ThreadPrimitive` + `MessagePrimitive.Content components={{ tools: { by_name, Fallback } }}`。
- 重新 `bun install` 清空 stale lockfile，验证 tsc / vite dev server 启动通过。
- 现有 6 个 skill 渲染器（fscan-asset-discovery / fscan-vuln-scan / nmap-port-scan /
  nuclei-template-scan / cmdb-query / report）和 `tool-call-card` fallback 在新签名下零回归。

### R3 引入新依赖 + 源代码拷贝

- npm 新依赖：
  - `@xyflow/react@^12.10` （唯一新 runtime；agent topology graph）
  - `framer-motion@^11` （MagicUI 的间接依赖；版本与 MagicUI 模板对齐）
- 源代码拷贝（CLI 落到 git，可钉可改）：
  - `webui/src/components/magicui/` ：border-beam / shine-border / animated-grid-pattern /
    marquee / number-ticker / animated-shiny-text / shimmer-button / animated-beam（共 8 个）
  - `webui/src/components/tremor/` ：donut-chart / area-chart / bar-chart / tracker /
    progress-bar / callout / metric（共 7 个）
  - `webui/src/blocks/` ：sidebar-07 / dashboard-01（共 2 个 block）
- 拷贝后**全文搜替**：把硬编码 hex 替换为 `hsl(var(--*))` token，确保命中海蓝主题
- 在 `tailwind.config.js → content` 追加 `./src/components/magicui/**/*.{ts,tsx}` 与
  `./src/components/tremor/**/*.{ts,tsx}`

### R4 主 Shell 海蓝化（nanobot 通用界面）

- `webui/src/App.tsx` ：headers / loading state 改用 brand-deep 渐变背景
- `webui/src/components/Sidebar.tsx` ：背景换 brand-deep 玻璃质 + 边框 `--border-subtle`
  + 当前选中项用 `<BorderBeam>` 描边
- `webui/src/components/thread/ThreadShell.tsx` ：composer 加 `<ShineBorder>` 包裹，
  发送按钮改 `<ShimmerButton>`；header 加 ConnectionBadge glow
- `webui/src/components/MessageBubble.tsx` ：用户/助手气泡用 `--brand-light` overlay
  + framer-motion 进场（fadeIn + 4px slide）
- `webui/src/components/ConnectionBadge.tsx` ：online 状态用 `--success` + animate-pulse
  glow，offline 用 `--error`
- `webui/src/components/settings/SettingsView.tsx` ：分组卡片用 shadcn `Card` + 海蓝 ring

### R5 secbot Tab 海蓝化 + HUD 化

- `webui/src/secbot/SecbotShell.tsx` ：Tab 栏改用 shadcn `Tabs` + brand-deep 选中态 +
  `<AnimatedGridPattern>` 背景
- **Chat Tab**（`SecbotThread.tsx`）：在 `<ThreadPrimitive.Root>` 外包裹 `<BorderBeam>`
  高亮"当前 active 思考";流式状态用 `<AnimatedShinyText>` 替代 "Thinking…" 文本
- **工具卡片渲染器**（`renderers/*.tsx`）：6 个卡片统一改用 shadcn `Card` + Tremor Raw
  `Callout` 高危 / 严重提示 + status pulse；nmap-port-scan 加 `<NumberTicker>` 显示
  端口数；nuclei-template-scan 加 Tremor `DonutChart` 严重度分布
- **Assets 页**：表格改用 shadcn `DataTable`（TanStack Table）+ Tremor `Metric` 三联
  "总资产 / 总服务 / 总漏洞" + Tremor `BarChart` Top 10 风险资产
- **Scans 历史页**：DAG 进度改用 Tremor `Tracker`（kill-chain 风），单项进度用 Tremor
  `ProgressBar`；加一个**新页签**或子区域用 `@xyflow/react` 显示 orchestrator → 专家
  agent → tool 的实时调用图（节点用 shadcn Card 自定义）
- **Reports 页**：改用 shadcn block `dashboard-01` 骨架 + Tremor `DonutChart` 严重度分布
  + Tremor `AreaChart` 历史趋势 + Tremor `Callout` Top critical 提示

### R6 AI agent 工具卡 / 思考链（自建，无成熟库）

- 新增 `webui/src/secbot/components/AgentThoughtChain.tsx` ：
  - 由 shadcn `Collapsible` + `Card` + lucide `Brain/Wrench/Search/FileText/ChevronDown`
    + `<BorderBeam>` 当前步骤指示 + `<AnimatedShinyText>` 流式 token 组成
  - 数据契约对齐 assistant-ui `MessagePrimitive.Content components.tools.by_name`，
    新增一种 `thought` part 类型供 orchestrator 推送推理过程

### R7 性能 / 兼容 / 可观察性

- `bun run build` 后 gzip 增量 ≤ 110 KB（实际目标）/ ≤ 200 KB（硬上限）
- Lighthouse Performance 分数与 main 比不退化（目标 ≥ 90）
- `prefers-reduced-motion` 全程退场：所有 framer-motion 动画与 MagicUI 背景动画
  在该媒体查询命中时降级为静态
- 暗色为默认；light 模式同步海蓝化保持 WCAG AA 对比度
- i18n：所有新增 UI 文案走 `react-i18next`，覆盖 zh-CN / en-US

## Acceptance Criteria

- [ ] **PR0**：`SecbotThread.tsx` 在 `@assistant-ui/react@0.10.x` 下正确编译并 dev 启动；
      `bun install` 重生 lockfile 含 `@assistant-ui/react`；6 个 skill 渲染器零回归
- [ ] **R1**：`globals.css` 含 `--brand-deep / --brand-light / --success / --warning /
      --error / --info` token；`tailwind.config.js` 含对应 `colors.*`；切到 light 主题
      时背景变 `#F4F8FD` 而非中性灰
- [ ] **R3**：`@xyflow/react` 与 `framer-motion` 安装成功；`webui/src/components/{magicui,tremor}/`
      含 8 + 7 个 .tsx；ESLint 通过；含至少 1 个 vitest 渲染快照测试每个新组件
- [ ] **R4**：所有列出的 5 个主 Shell 文件改造完成；MessageBubble 进场动画在
      `prefers-reduced-motion: reduce` 下静态
- [ ] **R5**：`SecbotShell` 4 Tab 全部海蓝化；Reports 页含 DonutChart 严重度分布
      （视觉验证截图）；Scans 历史含 xyflow agent 调用图
- [ ] **R6**：`AgentThoughtChain` 新建并与 assistant-ui MessagePrimitive 集成；至少 1 个
      集成测试覆盖"orchestrator 思考过程 → 工具调用 → 结果展示"全流程
- [ ] **R7**：`bun run build` gzip 增量在 ≤110KB 范围；`bun run test` 全绿；
      Lighthouse Performance ≥ 90（运行 1 次 baseline + 1 次 after，截图记录）

## Definition of Done

- 所有新增组件有 vitest 渲染测试（最低限度的 snapshot + 关键交互）
- ESLint + tsc + CI 全绿
- `webui/README.md` 更新组件库说明（MagicUI / Tremor Raw / xyflow / 主题 token）
- 截图对照（baseline vs after）放在 `docs/secbot-ui/` 或 PR 描述
- 渐进式落地，每个 PR 单独可回滚
- README 主页更新海蓝色板说明（双主色策略）
- 可关闭：feature flag `VITE_SECBOT_HUD=1`（默认开），允许一键回退到 main 风格

## Technical Approach

### 关键决策（ADR-lite）

#### Decision 1：放弃 `@prompt-or-die/tech-ui`
- **Context**：原计划集成 `@prompt-or-die/tech-ui`，但调研显示该包是 v0.0.1 单人副业
  项目，1 star、3 commits、5 个月停滞、Tailwind v4 语法（与我们 v3.4 不兼容）、
  23 处硬编码 `#ff5800` 橙色 glow、多数 Layout 组件是含 mock 数据的演示组件。
- **Decision**：不引入。改用成熟、活跃维护的替代组合。
- **Consequences**：放弃了 `TechAgentWorkbench / TechRadar / TechNeuralMesh` 这些"现成"
  组件名，但获得更可靠的供应链与可控源代码；AI agent UI 必须自建（见 R6）。

#### Decision 2：组件库 = shadcn blocks + Tremor Raw + MagicUI + @xyflow/react
- **Context**：8 个候选库评估后，唯一同时满足 shadcn 兼容、活跃维护、覆盖 5 个组件
  类别的组合。
- **Decision**：Recipe B（中等覆盖）。**Tremor 使用 Raw 拷贝形式而非 npm 包**，因为
  `@tremor/react@3.18.7` 已停滞 16 个月、4.x 卡在 beta。
- **Consequences**：
  - 唯一新 runtime npm 依赖：`@xyflow/react`（间接 framer-motion）
  - 17 个新源文件落入 git，可钉可改但需要把硬编码 hex 替换为 token
  - 升级路径明确：xyflow 是行业标准（5.5M weekly DL），其他都是源拷贝可独立演进

#### Decision 3：双主色策略 (#0E6BA8 brand + #1E90FF interaction)
- **Context**：README 宣称 `#0E6BA8`，代码用 `#1E90FF`。HUD glow 需要更亮的高饱和度
  反馈色；品牌识别需要更稳重的深蓝。
- **Decision**：保留 `--primary: #1E90FF` 作交互高亮；新增 `--brand-deep: #0E6BA8`
  作品牌身份；`--brand-light: #7AB8FF` 作 hover overlay。参考 Linear / Vercel / Splunk
  的双色调实践。
- **Consequences**：现有代码不需要迁移，只新增 token；README 品牌色保持一致；HUD
  动效有充足"能量色"。

#### Decision 4：scope = B（主 Shell + secbot Tab 都海蓝化）
- **Context**：用户在 Q1 选择"secbot Tab + 主 Shell 也海蓝化（推荐）"。
- **Decision**：完整 webui 视觉一致升级；不放弃 nanobot 主 Shell。
- **Consequences**：触面更大，需要更细的回归测试，但避免了"两套并列风格"的体验割裂。

#### Decision 5：intensity = S2（中度科技感）
- **Context**：用户在 Q2 选择 S2，避免 S3 的"过度 cinematic"对长时间研判的干扰。
- **Decision**：TechFrame / GlassPanel 风的卡片 + 数据可视化 + 微动效，不做
  Workbench 三栏 + Neural Mesh 背景。
- **Consequences**：bundle 预算可控（~80-110 KB gzip）；分析师效率不被损害；保留
  S3 升级空间（feature flag）。

#### Decision 6：feature flag 守护
- **Decision**：所有 secbot HUD 升级走 `VITE_SECBOT_HUD=1` env flag（默认开）。
- **Consequences**：一键回退、增量上线、可对比新旧体验。

### 关键技术细节

- **assistant-ui 0.10 正确 API**（PR0 修复）：用 `ThreadPrimitive.Root` /
  `ThreadPrimitive.Messages` / `MessagePrimitive.Content` + `components.tools.by_name`
  注册 SKILL_RENDERERS，而不是顶层 `<Thread tools=...>`。
- **shimmer 实现**：tw-shimmer 是 Tailwind v4 only，必须手写 keyframes（CSS 内嵌或
  `globals.css @layer utilities`）。
- **AnimatePresence vs assistant-ui auto-scroll**：不要用 `mode="popLayout"` 包整个
  Messages 列表，会与自动滚动打架。只对单条 message 用 `motion.div`，或在
  `ThreadPrimitive.Viewport` 外层用 `mode="wait"`。
- **MagicUI 拷贝后清理**：MagicUI 部分组件源码含硬编码 hex / 渐变（不像 tech-ui 那么
  严重，但仍需 sweep），grep 命中后替换为 `hsl(var(--primary))` 等 token 形式。
- **xyflow CSS 隔离**：必须 `import '@xyflow/react/dist/style.css'`，CSS 不走 Tailwind；
  通过 wrap 节点为自定义 React 组件 + `style` 属性透传 token，把节点视觉拉回海蓝主题。

## Implementation Plan（5 个 PR，从基建到完整 HUD）

| PR | 范围 | 估时 | 风险 |
|----|------|------|------|
| **PR0** | 修复 `SecbotThread.tsx` 的 v0.10 API 不匹配 + 重生 bun.lock + 校验 6 个 skill 渲染器零回归 | 0.5 天 | 低（独立改造、可单独 merge） |
| **PR1** | R1 主题 token + Tailwind 扩展 + light 海蓝化 + WCAG 检查 | 0.5 天 | 低 |
| **PR2** | R3 安装 npm + 拷贝 17 个源文件 + 替换硬编码 hex + 加 vitest 快照 | 1 天 | 中（拷贝源量大、需 sweep） |
| **PR3** | R4 主 Shell 海蓝化（5 个文件） + R6 AgentThoughtChain 自建 | 1.5 天 | 中（触面较广，回归测试重） |
| **PR4** | R5 secbot 4 Tab 海蓝 + HUD 化（含 xyflow agent 调用图） | 2 天 | 中高（xyflow 学习成本 + DAG 数据契约） |
| **PR5** | R7 性能验证 + Lighthouse + bundle 报告 + feature flag + 文档更新 | 0.5 天 | 低 |

**总估时：~6 天**

## Out of Scope (explicit)

- 不引入 Vue（避免双栈）
- 不重写后端 REST / WebSocket 协议
- 不替换 assistant-ui（继续用 0.10，**只修 API 不匹配 bug**，不升级到 0.14）
- 不引入 `@prompt-or-die/tech-ui`
- 不引入 `@tremor/react` npm 包（用 Tremor Raw 源拷贝代替）
- 不做 S3 重度 HUD（Workbench 三栏 / Neural Mesh / 全息投影）—— 保留为未来扩展
- 不引入 Aceternity Pro 收费组件（只可能选 OSS 子集，且 Recipe B 不依赖它）

## Research References

- [`research/tech-ui-package.md`](research/tech-ui-package.md) ✅ — tech-ui 不可用结论
- [`research/tech-ui-alternatives.md`](research/tech-ui-alternatives.md) ✅ — Recipe B
  组合推荐（shadcn + Tremor Raw + MagicUI + xyflow）
- [`research/assistant-ui-customization.md`](research/assistant-ui-customization.md) ✅ —
  SecbotThread v0.10 API 修复路径 + theming hook + framer-motion 协作注意事项
- ⚠️ `research/cybersec-hud-patterns.md` — 第 4 个 sub-agent 超时未产出；本次决策不
  阻塞（视觉强度由 Q2 选择 + tech-ui-alternatives.md 的组件清单 + 主流参考 Linear /
  Vercel / Splunk 已能确定方向）

## Technical Notes

- 现有主题 token：`webui/src/globals.css` 已有完整 secbot 暗色主题 + severity 调色板
- 现有 chat runtime：`webui/src/secbot/runtime.ts`（**不动**）
- 现有 6 个 skill 渲染器：`webui/src/secbot/renderers/*` —— 是 PR4 的核心改造点
- README 里 secbot 章节宣称"海蓝主题"，但现有仪表板（纯 HTML 表格）远未达"酷炫"目标
- 既往 commit：`99cf6ed9 feat(webui): add secbot pages and ocean-blue theme`
- 关键预存 bug 已记录在 PR0
- bun.lock stale，PR0 顺手重生
