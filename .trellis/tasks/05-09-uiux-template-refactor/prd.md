# UI-UX 模板落地：前端重构与品牌替换

## Goal

按 [`UI/UI-UX建设模版.md`](../../../UI/UI-UX建设模版.md)（海盾漏洞检测智能体管控台风格模板）对 `webui/` 前端进行**视觉与交互体系对齐**：
- 采用模板的设计令牌（海蓝/青蓝色板、玻璃拟态、4px 色条、微动效）和页面骨架（Sticky Navbar + `container py-6 space-y-6` + KPI/图表/列表网格）；
- **功能超出当前后端能力的部分**（Dashboard/TaskDetail/Whitelists/EngineResources/AuditLog/PlatformSettings 等管控台功能）以"差距文档 + 测试数据"形式**先在前端落地**，后端 API 契约后续同步跟进；
- **品牌资产全量替换**：删除所有 nanobot 的 logo 和图片（`webui/public/brand/nanobot_*.*`、`images/nanobot_*.png` 等），统一换为项目根目录下的 `banner.png`、`logo.png`、`Text logo.jpg`。

## What I already know

### 当前 webui 状态（事实）

- **技术栈**：React 18.3 + Vite 5 + Tailwind 3.4 + `@assistant-ui/react` + `@radix-ui/*` + `recharts` + `react-i18next` + `@tanstack/react-query`。
- **路由**：**没有 react-router**，`App.tsx` 用 `view: "chat" | "settings"` 条件渲染单页 Shell。
- **设计令牌**：`src/globals.css` 使用 shadcn neutral 灰度 + `.dark` + `[data-theme="secbot"]` 海蓝主题（主色 `210 100% 56%` Dodger Blue `#1E90FF`）。
- **组件资产**：Sidebar、ThreadShell（聊天）、SettingsView、SecbotShell/SecbotThread（4 Tab HUD：AssetsView/ReportsView/ScanHistoryView/AgentThoughtChain）、MessageBubble、BlackboardCard、ConnectionBadge、LanguageSwitcher、MagicUI 效果组件（ShineBorder/BorderBeam/AnimatedShinyText/AnimatedGridPattern）。
- **鉴权**：`fetchBootstrap` 共享 secret → WebSocket token，`localStorage['nanobot-webui.sidebar']` 等持久化键。
- **品牌资产**：`webui/public/brand/nanobot_{logo,icon,favicon_32,apple_touch}.{png,webp}` 共 5 个；`images/` 下还有 `GitHub_README.png`、`nanobot_arch.png`、`nanobot_logo.png`、`nanobot_webui.png`；根 README、`index.html`、`banner.png` 等多处引用。
- **历史任务沉淀**：`05-07-ocean-tech-frontend` 已完成一轮海蓝科技感重构（MagicUI + Tremor），`05-08-ocean-tech-frontend-gap-fix` 做过跟进。
- **国际化**：`src/i18n/locales/{en,zh-CN}/common.json`，全 key 化。

### 模板要求（事实）

- **新增技术栈**：`react-router-dom@7`、`echarts` + `echarts-for-react`、`react-virtuoso`、`sonner`、`class-variance-authority`（已有）。
- **新减技术栈**：需决定是否替换 `recharts` → `echarts`、替换 `@assistant-ui` → 自建 `ChatMessage`。
- **主色**：模板 `--primary: 189 94% 43%`（青蓝 cyan-500 风）。与当前 secbot 主题 `210 100% 56%`（海蓝）**不完全一致**。
- **页面矩阵**：登录 / 首页（对话型智能体台）/ 大屏分析（KPI+ECharts+列表）/ 任务详情（信息卡+实时流+表格+报告）/ 白名单 / 平台设置 / 引擎资源 / 审计日志 共 **8 类** 页面。
- **品牌替换**：根目录 `banner.png`（1.39 MB）、`logo.png`（1.28 MB）、`Text logo.jpg`（34 KB）实物存在。

## Assumptions (temporary, need validation)

1. 此次重构**不要求**后端 API 真实提供 Dashboard/TaskDetail/Whitelists 等端点，前端用 MSW / 本地 mock 数据兜底即可；差距项写入 `gap/<topic>.md`。
2. 品牌替换时 **所有 `nanobot_*` 资产** 都替换（含 `images/` 下 README 用图），不仅限于 webui 下。
3. 模板中的 "管理员角色门" (`fetchMe()` → `role === 'admin'`) 在当前后端缺失，首版用**前端配置开关 / localStorage 假角色** 代替，计入差距。
4. 沿用当前 i18n 基础设施（不迁回硬编码中文），所有新文案走 `t()`。
5. 保留现有聊天/会话核心逻辑（`NanobotClient` + WebSocket + `@assistant-ui`）到 Home 页内嵌，不一次性推翻。

## Open Questions

- ~~[BLOCKING Q1]~~ ✅ **已决策**：采用**原地替换 Shell + 保留对话核心**。在 `webui/` 内引入 `react-router-dom@7`，聊天核心迁为 Home 页内嵌；原子组件替换为模板版；差距页用 mock 数据新建；保留 `VITE_UIUX_TEMPLATE` flag 支持一键回退。
- ~~[BLOCKING Q2]~~ ✅ **已决策**：MVP = **Login + Home + Dashboard + TaskDetail + 统一 Settings**。Whitelists / EngineResources / AuditLog / 独立 PlatformSettings 全部写入 `gap/<page>.md` 延后。
- ~~[BLOCKING Q3]~~ ✅ **已决策**：`logo.png` → favicon + apple-touch + 顶栏 h-9 w-9 图标 + 加载页 hero；`Text logo.jpg` → Sidebar 顶部品牌区 + 登录页标题上方；`banner.png` → 登录页装饰背景 + Dashboard 顶部欢迎横幅 + README 首图。
- ~~[BLOCKING Q4]~~ ✅ **已决策**：主色沿用海蓝 `#1E90FF` (`hsl(210 100% 56%)`)，对齐 `cybersec-ui-patterns.md` spec 与 `[data-theme="secbot"]` 主题。
- ~~[PREFERENCE Q5]~~ ✅ **已决策**：**引入 `echarts` + `echarts-for-react`** 用于 Dashboard；`recharts` 保留不动。
- ~~[PREFERENCE Q6]~~ ✅ **已决策**：**保留 `@assistant-ui/react`** 作为 Home 对话引擎，仅调整样式。
- ~~[PREFERENCE Q7]~~ ✅ **已决策**：**不引入 `react-virtuoso`**；日志用滑窗/截断，后续优化入差距。
- ~~[PREFERENCE Q8]~~ ✅ **已决策**：**不引入 `sonner`**，沿用 `window.alert`；对齐已有决策记忆。
- ~~[BLOCKING Q9]~~ ✅ **已决策**：品牌扫清**全量范围** —— `webui/index.html`、6 处 `Sidebar.tsx`、`webui/public/brand/nanobot_*` 5 个旧资产、`README.md` 引用、`images/{nanobot_arch,nanobot_logo,nanobot_webui,GitHub_README}.png` 全部替换或删除。
- ~~[BLOCKING Q10]~~ ✅ **已决策**：**Phase 0 交付静态 HTML 原型**——在开始 React 改造前，先用 5 个独立 HTML 页面（Login / Home / Dashboard / TaskDetail / Settings）含完整模板设计令牌、Tailwind CDN、品牌资产、ECharts mock 图表，交由用户评审反馈后再启动代码实施。

## Requirements (locked)

### R1 设计体系

- R1.1 设计令牌根据模板 §3 重写 `webui/src/globals.css`：保留现有 `[data-theme="secbot"]` 主色海蓝、补全 `--gradient-primary/--gradient-subtle/--gradient-card/--shadow-elegant/--shadow-glow/--transition-smooth`、`bg-glass / border-glow / hover-lift / text-gradient` utilities。
- R1.2 `tailwind.config.ts` 补全 `keyframes`/`animation`（`pulse-glow / fade-in-up / slide-in-right`）与 `ocean / cyan.glow / alert` 拓展色板；`fontFamily.sans = ['Inter','Noto Sans SC',…]`，新增 `fontFamily.mono = ['JetBrains Mono',…]`。
- R1.3 `index.html` 顶部 import Google Fonts（Inter + Noto Sans SC + JetBrains Mono）。

### R2 品牌资产迁移

- R2.1 从根目录 `banner.png` / `logo.png` / `Text logo.jpg` 生成增量位图：`webui/public/brand/{logo.png, logo.svg-or-webp, favicon-32.png, apple-touch-180.png, text-logo.png, banner.png}`（需 sips/imagemagick 压压，logo.png 原图 1.28MB 不能直接上）。
- R2.2 `webui/index.html` favicon / apple-touch 指向新资产；`Sidebar.tsx` 品牌区改使用 `text-logo.png`；顶栏 h-9 w-9 位置使用 `logo.png` 的 32px 裁剪。
- R2.3 删除 `webui/public/brand/nanobot_*.{png,webp}` 5 个旧资产与 `images/{nanobot_arch,nanobot_logo,nanobot_webui,GitHub_README}.png`；根 `README.md` 以新 banner.png 为顶部横图，补充新的 webui 截图占位（可后补）。
- R2.4 `rg -i 'nanobot[_-]?(logo|icon|favicon|apple_touch|webui|arch)|GitHub_README'` 仅命中文档说明性描述。

### R3 路由与 Shell 重构

- R3.1 `webui/src/App.tsx` 接入 `react-router-dom@7` `BrowserRouter`，路由表：`/login`、`/`(=Home)、`/dashboard`、`/tasks/:id`、`/settings`。
- R3.2 `<ProtectedRoute>` 包裹（复用现有 bootstrap secret 校验），未鉴权 redirect `/login?next=`。
- R3.3 顶栏 `Navbar` 提取为共享组件（sticky h-16 backdrop-blur），嵌入 logo / Text logo / 路由菜单 / Sidebar toggle / 设置入口。
- R3.4 引入 `VITE_UIUX_TEMPLATE` env flag；false 时走原有 view 条件渲染（一键回退路径）。

### R4 5 个 MVP 页面

- R4.1 **LoginPage**（模板 §7.1）：双栏布局，左 `banner.png` 装饰 + 右侧居中卡片，表单复用 `bootstrapWithSecret`；存在错误 inline `border-destructive/40`。
- R4.2 **HomePage**（模板 §7.2）：内嵌现有 `ThreadShell`；左 1/右 3 栅格，左侧 PromptSuggestions chips + Quick stats；右侧对话区保留 @assistant-ui 的 streaming。
- R4.3 **DashboardPage**（模板 §7.3）：顶部 `banner.png` hero strip + 6 列 KPI + ECharts 风险趋势 + 最近报告列表 + 资产聚类。全量 mock 数据从 `src/data/mock/dashboard.ts` 读取。
- R4.4 **TaskDetailPage**（模板 §7.4）：复用现有 `SecbotShell` 4 Tab 改造；AssetView / ReportsView / ScanHistoryView 包装为「任务详情」面板，顶栏內 TaskStatusBadge + 心跳微动。`/tasks/:id` 有 `:id=demo` 作 mock。
- R4.5 **SettingsPage**（模板 §7.5 + 现有 SettingsView）：Tab 划分为「用户偏好（外观主题 / 语言与时区 / 通知与推送）」 + 「平台管理（模型与提供方）」 + 「危险区（退出登录 / 清空所有会话）」。根据 R2 决策，**不含个人资料 / 安全与鉴权 / 阈值与限流 / 用户与角色 / 重置平台**（登录后统一 admin，无分级）。

### R5 差距文档

- R5.1 生成 `gap/whitelists.md`、`gap/engine-resources.md`、`gap/audit-log.md`、`gap/platform-settings.md`，各含：后端缺口（端点 / 数据模型）、前端预计表现（截图 wireframe 可选）、mock 数据存放位置、建议后续任务拆分。
- R5.2 生成 `gap/role-gate.md`：说明现代 admin 角色门缺失、临时用 `localStorage['secbot.fakeRole']` 实现的 mock 现状、后端 `/auth/me` 需补全的字段。
- R5.3 生成 `gap/realtime-stream.md`：说明模板假设 SSE，当前使用 WebSocket，TaskDetail 实时日志用 mock 轮询，后续可补 SSE 层。

### R6 Phase 0 静态 HTML 原型（首交付）

- R6.1 在 `.trellis/tasks/05-09-uiux-template-refactor/prototypes/` 下输出 5 个独立 HTML：`01-login.html`、`02-home.html`、`03-dashboard.html`、`04-task-detail.html`、`05-settings.html`。
- R6.2 每份 HTML 含：Tailwind CDN + 模板 CSS 变量 + Google Fonts + lucide CDN + ECharts CDN（Dashboard） + 品牌资产（指向以相对路径读根目录 banner.png/logo.png/Text logo.jpg） + mock 数据内联。
- R6.3 面上需呈现：顶栏 / 主体网格 / 状态色徽 / 品牌位置 / Hover 动效 / 字体 / KPI / 图表 / 表格 / 表单 / 错误态。
- R6.4 **交付后等待用户选择/反馈**，决定哪些原型可进入 Phase 1 代码实施，哪些需调整重发。

### R7 任务编排与黑板协作（对齐 [`网络安全多智能体平台产品文档.md`](../../../网络安全多智能体平台产品文档.md)）

> 基于产品文档 §7.2 主智能体调度、§7.6 黑板协作、§8 多智能体协作流程，本节定义本次 MVP 的**任务逻辑落地范围**。接口契约见 [`api-design.md`](./api-design.md) §4 / §6。6 项分叉点决策（2026-05-09）：任务级审批 ❌ 不做｜scope ❌ 不扩展 schema（自然语言）｜黑板事件 ✅ 加｜Finding 统一入口 ✅ 加｜周期任务 ❌ 延后｜Tool Registry ✅ 只读。

- R7.1 **任务状态机**（不加 WaitingApproval）：沿用 `cmdb/models.py::VALID_SCAN_STATUSES = {queued, running, awaiting_user, completed, failed, cancelled}` 加 `paused`，**不新增** `waiting_approval / planning / archived`。前端 TaskStatusBadge 只渲染这 7 态。产品文档中的「Planning」阶段折叠进 `queued`（主 Agent 在 queued→running 切换瞬间完成计划）。
- R7.2 **Scan 配置 schema**（不扩展为完整 schema）：`POST /api/scans` 请求体仅保留 `{ target: string, scope?: { ports?: string, agents?: string[] }, priority?, description? }`。`target` 可为自然语言（"扫描生产 CRM 整段"）或 CIDR/域名列表，主 Agent 在调度前自行解析；**不强制** `domains/ip_ranges/excluded_targets/authorization_id/risk_mode/rate_limit/require_approval_for`。授权合规由人工前置审核 + 审计日志兜底。
- R7.3 **黑板双层模型**：
  - **聚合层**（现有）：`GET /api/scans/{task_id}/blackboard` 返回 agents 数组 + stats，用于 TaskDetail「智能体活动」面板快速渲染；
  - **事件层**（新增）：`POST /api/scans/{task_id}/blackboard/query`（复杂筛选）+ `GET /api/scans/{task_id}/blackboard/events?since=&limit=`（分页拉取历史事件）+ WS `event:"blackboard_event"`（单事件实时推送，对齐产品文档 §7.6.3 事件结构）。事件写入端仅内部 Agent 调用，不暴露给前端。
- R7.4 **Finding 统一查询**：新增 `GET /api/scans/{task_id}/findings?category=cve|weak_password|misconfig|exposure&severity=&limit=&offset=` + `GET /api/findings/{finding_id}`（含 `evidence_refs`、`recommendation`、`impact`）。字段对齐产品文档 §10.6。原 `/api/assets/{id}/vulnerabilities` 保留（按资产视角用），新增接口承担「任务视角聚合风险」职责。`GET /api/evidences/{evidence_id}` 提供证据文件下载（对应 §7.5.4）。
- R7.5 **Tool Registry 只读**：新增 `GET /api/tools`（返回当前可用工具元数据：`name/display_name/version/kind/risk_level/allowed_in_agents[]`），供 Settings「平台能力概览」与 TaskDetail「活动流」工具名展开。**不暴露** POST/PUT/DELETE。
- R7.6 **调度可视化映射**：
  - TaskDetail「思维链 Tab」← WS `activity_event`（category=thought/tool_call/tool_result，对齐产品文档 §7.2.5 调度伪代码）；
  - TaskDetail「黑板 Tab」← 聚合快照 + WS `blackboard_event` 事件流（对齐产品文档 §8.3 动态重规划）；
  - Home「在线专家智能体」← `GET /api/agents?include_status=true` 轮询 + 共享 `blackboard_event` 推送状态变迁。
- R7.7 **操作级审批链路**（保留，非任务级）：Agent 执行高危动作前主动发 `event:"high_risk_confirm"`（WS Server→Client）→ 前端弹出「高危确认」卡片 → 用户 `POST /api/high-risk-confirms/{confirm_id}/decide` 回复 `approve|reject` → Agent 继续/中止。对齐产品文档 §7.2.5 `policy.evaluate_step` + `approval.request` 流程。
- R7.8 **延后项（写入差距文档）**：`gap/scheduled-tasks.md`（周期扫 + Workflow DSL）、`gap/tool-policy.md`（Tool POST CRUD + Policy Rules + Workflow manifest）、`gap/authorization-scope.md`（authorization_id / excluded_targets / 多租户）。

## Acceptance Criteria

### Phase 0 原型验收
- [ ] 5 个 HTML 页面能直接用浏览器打开（双击或 `python -m http.server`），资产加载正常，ECharts/lucide 渲染成功。
- [ ] 品牌位置、主色、玻璃拟态、现代动效与模板 §15 「30 秒风格自检清单」一致。
- [ ] 用户明确选出需推进的页面集（或调整点）。

### Phase 1+ 代码实施验收
- [ ] `bun run build` + `vitest` + `eslint --max-warnings 0` 全绿。
- [ ] `webui/public/brand/` 下无 `nanobot_*` 资产；`images/` 下无 `nanobot_*`/`GitHub_README*`。
- [ ] `rg -i 'nanobot[_-]?(logo|icon|favicon|apple_touch|webui|arch)|GitHub_README' webui src docs README.md` 仅命中文档说明性。
- [ ] 5 个 MVP 路由能访问且渲染与原型一致；Dashboard ECharts 有数据；TaskDetail mock 任务可点击。
- [ ] `gap/*.md` 6 份完整，每份包含后端缺口 + 前端表现 + mock 数据路径 + 建议后续任务。
- [ ] `VITE_UIUX_TEMPLATE=false` 能回退到原 Shell。

## Definition of Done

- 单元测试：新增路由、页面 smoke render 测试覆盖；错误/空/加载三态有测试。
- README、docs/UX设计-* 同步更新品牌与路由。
- 差距文档为后续“后端同步修改”任务提供明确输入。
- Lighthouse 回归与 `.trellis/.runtime/lighthouse-baseline.md` 对比记录。

## Out of Scope

- 后端 API 实现（仅出 gap doc）。
- 迁移现有 `recharts` 为 `echarts`；`@assistant-ui` 替换。
- 安装/接入 `react-virtuoso`、`sonner`。
- 全面冲 README/使用文档重写（仅品牌项更新）。
- 后台 admin 角色鉴权（mock，计入 gap）。

## Implementation Plan (small PRs)

- **Phase 0：PR0** 按 R6 交付 5 个 HTML 静态原型 + 品牌资产预生成（等待用户评审）。
- **PR1**：品牌扫清 + 资产迁移 + favicon/index.html/Sidebar/README 入口替换（R2）。
- **PR2**：设计令牌升级 + tailwind.config + globals.css utilities 补全 + Google Fonts（R1）。
- **PR3**：路由接入 + Navbar 提取 + ProtectedRoute + VITE_UIUX_TEMPLATE flag（R3）。
- **PR4**：Login + Home 页落地（R4.1、R4.2，保留聊天核心）。
- **PR5**：Dashboard + ECharts 接入 + mock 数据（R4.3）。
- **PR6**：TaskDetail 复用 SecbotShell + mock 任务（R4.4）。
- **PR7**：Settings 重整为 Tab 布局（R4.5） + gap/*.md 6 份交付（R5）。
- **PR8**：测试 + Lighthouse 回归 + 文档同步 + 清理。

## Decision (ADR-lite)

**Context**：安全平台 webui 现为聊天为主的单页 Shell；需以「海盾漏洞检测智能体控制台」模板为基线升级为有路由的多页管控台；同时品牌从 nanobot 全量切换为新品牌。

**Decision**：
1. 采用“原地替换 Shell + 保留对话核心”，加 `VITE_UIUX_TEMPLATE` flag 保留一键回退。
2. MVP 五页（Login/Home/Dashboard/TaskDetail/Settings）以 mock 数据完整落地；模板剩余管理页进差距文档。
3. 主色海蓝 `#1E90FF` + 模板玻璃拟态/发光/渐变令牌。
4. 仅增 `echarts`；保留 `@assistant-ui` `recharts`；不引入 `virtuoso/sonner`。
5. 品牌扫清全范围；Phase 0 先交 5 个 HTML 原型评审。

**Consequences**：
- 正面：升级渐进，有回退开关；对话核心不被破坏；Phase 0 原型降低返工风险。
- 负面：`recharts + echarts` 双图表库增加 bundle。
- 后续：需后台兑现差距文档，及后端鉴权/角色/REST/SSE 补齐。

## Expansion Sweep 记录

- **Future evolution**：后续可加入「主题切换」（海蓝/青蓝/集团个性化）、「大屏模式」（仅 Dashboard）、「多租户品牌」插槽。
- **Related scenarios**：Home 与 Dashboard 的 KPI 状态卡需保持交互对齐；各后台页后续补齐时可复用同一套「列表 + 模态框」模式。
- **Failure / edge cases**：
  - 根 secret 鉴权失败 → 部分路由 redirect `/login`，mock 数据也需鉴权拦截；
  - WebSocket 断连时，Home/TaskDetail 需给出 connection badge；
  - mock 数据补齐 deterministic seed，避免成文 deps 闪跳；
  - 差距页路由里需明确点击提示「本页仅示范，后端未接入」。

## Technical Notes

- 现状源码核心：[`webui/src/App.tsx`](../../../webui/src/App.tsx#L1-L450)、[`webui/src/globals.css`](../../../webui/src/globals.css#L1-L160)、[`webui/src/components/`](../../../webui/src/components/)、[`webui/src/secbot/`](../../../webui/src/secbot/)、[`webui/src/i18n/`](../../../webui/src/i18n/)。
- 模板与原子 UI：[`UI/UI-UX建设模版.md`](../../../UI/UI-UX建设模版.md)、[`UI/index.css`](../../../UI/index.css)、[`UI/ui/{button,card,badge,input,textarea}.tsx`](../../../UI/ui/)。
- 品牌原图：`/banner.png`、`/logo.png`、`/Text logo.jpg`（根目录）。
- 现有 brand 资产清单：
  - `webui/public/brand/nanobot_{logo.png, logo.webp, icon.png, favicon_32.png, apple_touch.png}`
  - `images/{GitHub_README.png, nanobot_arch.png, nanobot_logo.png, nanobot_webui.png}`
  - `logo.png`（根，是本次要替换进去的新 logo？需与用户确认是"覆盖"还是"并存"）
- 历史经验文件索引：[05-07-ocean-tech-frontend 任务核心文件](../05-07-ocean-tech-frontend/)、`.trellis/.runtime/lighthouse-baseline.md`。

## Research References

> 后续若进入"research-first"分支，持久化到 `research/*.md`，再在此处回链。

## Decision (ADR-lite)

> 待 brainstorm 收敛后补充。
