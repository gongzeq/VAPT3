# 试验性功能：HTML-in-Canvas 前端渲染

## Goal

在 webui 中引入 Chromium 的实验性 "HTML-in-Canvas"（Canvas 2D `drawElement()` / `CanvasRenderingContext2D.drawElement()`，规范名 *element() for canvas / HTML-in-Canvas*）能力，作为一个**试验性、可开关**的渲染路径，用于探索把部分 DOM 片段渲染进 Canvas 的新视觉/性能玩法，而不是整体替换现有 React SPA。

## What I already know

### 来自用户输入
- 关键词："试验性"——意味着要可开关、可回退，不承诺稳定性
- 方向：HTML-in-Canvas（`drawElement()` 系列 API）

### 来自仓库 (webui/) 探查
- 技术栈：React 18.3 + Vite 5 + TypeScript + Tailwind 3 + PostCSS
- 交互强依赖：
  - Radix UI（Dialog/Dropdown/Tooltip/ScrollArea/Tabs/...）——大量 portal + 焦点管理
  - `@assistant-ui/react`（聊天 UI）
  - `@xyflow/react`（流程图 Canvas/SVG）
  - `framer-motion`（动画）
  - `react-markdown` + `react-syntax-highlighter` + `rehype-katex`（富文本渲染）
- 入口：`webui/src/main.tsx` → `App.tsx`（14.5KB，推测承载路由/布局）
- 产物目录：`nanobot/web/dist/`（后端托管静态资源）

### 关于 xyflow 的重要发现（由 Search 子 agent 核实）
- `@xyflow/react ^12.10` 已装、`src/lib/xyflow-bootstrap.ts` 已导入 CSS，但**当前整个 webui 没有任何一处实际挂载的 `<ReactFlow>`**。
- `ScanHistoryView.tsx` 的注释（1行 L60–L62）明确标注：xyflow DAG 可视化是“PR4 Phase B”后续工作，当前视图仍是原生 `<table>`。
- README 也確认：“xyflow 已安装，未来用于 ScanHistoryView 的 agent-graph”。
- 危险后果：B 方案实际意味着 **“新建一个 xyflow 画布 + 在其上做 HTML-in-Canvas 试验”**，不是“改造已有画布”。

### 来自 HTML-in-Canvas 规范/实现现状
- 当前只有 **Chromium 实现**，且位于 experimental flag `chrome://flags/#canvas-2d-layers` / `--enable-features=CanvasDrawElement`（具体 flag 名需研究子任务确认）
- Firefox / Safari / WebKit 无等价 API
- 绘制是"快照"型：事件、文本选择、无障碍树、IME、表单交互都**不会自动转发**到画布内
- 对动效/滤镜/CSS 过渡支持有限（draw 时的瞬时状态）
- 适合：背景特效、数据可视化合成、离屏截图、WebGL/Canvas 与 HTML 合成

## Assumptions (temporary)

- 用户要的是**试验性开关**，不是把整个 webui 改成画布；整体替换对 Radix/assistant-ui 不现实
- 试验范围可能聚焦在 1~2 处：如欢迎页/空状态背景、或 `@xyflow/react` 画布与 HTML 节点的合成、或聊天气泡的视觉特效
- 默认关闭，通过 URL 参数（如 `?exp=html-canvas`）或设置页开关启用
- 非支持环境（非 Chromium/未开 flag）静默回退到原生 DOM 渲染，不破坏现有体验

## Open Questions

- **[Blocking]** B 方案里以哪张 xyflow 视图为试验目标（项目中可能有多处使用）？
- **[Preference]** MVP 要合成什么：①节点背景/装饰层（交互不变）②整节点快照叠加（点击态需同步）③边/连接线辅助特效？
- **[Preference]** 开关入口：URL 参数 `?exp=html-canvas` vs 设置页开关 vs 同时支持？

## Requirements (evolving)

- 提供一个可开关的试验性渲染路径，默认 **关闭**
- 在不支持 `drawElement()` 的环境中必须**自动回退**到现有 DOM 渲染，无报错、无空白
- 仅作为**渲染副本**或**独立试验区**，不破坏现有路由、状态、键盘/鼠标交互与无障碍
- 构建产物不应增加默认加载体积（新代码按需动态 import 或树摇掉）

## Acceptance Criteria (evolving)

- [ ] 试验开关默认关闭；开启路径明确（URL 参数 or 设置项）
- [ ] 支持环境下能在目标区域看到 HTML-in-Canvas 效果
- [ ] 非支持环境自动回退，功能行为与开关关闭时完全一致
- [ ] 关闭开关后无任何副作用（事件监听、RAF、worker 全部清理）
- [ ] 增加的默认 bundle 体积 ≤ 既定阈值（待与 MVP 范围一起定）

## Definition of Done (team quality bar)

- 单元 / 组件测试覆盖开关开/关 & 能力探测回退
- `npm run lint`、`tsc -p tsconfig.build.json`、`npm test` 全绿
- 文档：在 `docs/` 或 `webui/README.md` 增加试验特性说明（启用方式、已知限制、浏览器要求）
- 风险/回退策略写入 PRD Decision 段

## Out of Scope (explicit, 初稿)

- 把整个 webui 替换为 Canvas 渲染
- 在 Firefox/Safari 上提供等价 polyfill（规范尚不稳定，代价过大）
- 无障碍树在 Canvas 内的重建（浏览器未提供，不在本期承诺）

## Technical Notes

### 关键参考（待 research 子任务补全链接）
- Chrome Status: "Canvas 2D: drawElement()" / HTML-in-Canvas proposal
- whatwg/html 相关 issue & WICG 提案
- Chromium flag 实际名称与启用步骤
- 已知限制：事件、ARIA、选区、表单、IME

### 可能影响的文件/模块
- `webui/src/main.tsx`, `webui/src/App.tsx`（试验开关挂载点）
- `webui/src/providers/`（若采用 Provider 包裹）
- `webui/src/hooks/`（新增 `useHtmlInCanvas` 能力探测 hook）
- `webui/vite.config.ts`（按需动态 import 的切分）
- 新增 `webui/src/experimental/html-in-canvas/`（隔离试验代码）

## Feasible approaches (待用户选择)

**Approach A：全局背景/装饰层试验（低风险，推荐 MVP 起点）**
- How：在 App 根节点挂一层 `<canvas>`，用 `drawElement()` 把某个"装饰性 DOM 子树"（如动态 logo、欢迎页插画）合成进画布，做视觉叠加/滤镜。原 DOM 仍负责交互。
- Pros：不破坏现有交互、无障碍、路由；代码隔离彻底；回退等价于"不渲染装饰层"。
- Cons：演示价值偏视觉，不能体现与业务强耦合。

**Approach B：聚焦 `@xyflow/react` 图形画布的节点合成试验（中风险）**
- How：在流程图视图里，把部分 HTML 节点通过 `drawElement()` 绘制进同一 Canvas，实现 HTML 节点与 WebGL/Canvas 边/背景的无缝合成。
- Pros：真实业务场景，展示 HTML-in-Canvas 相对传统 DOM 合成的独特价值。
- Cons：需改造现有 xyflow 使用；交互/选中态需要 DOM 层保留并对齐坐标；调试成本高。

**Approach C：聊天/富文本的离屏截图与导出试验（中低风险）**
- How：用 `drawElement()` 把一段 Markdown/代码块渲染快照到离屏 Canvas，提供"复制为图片/导出为图片"能力。
- Pros：落地为一个可感知的新功能（导出分享），试验与价值都清晰。
- Cons：与"改变前端渲染"相距较远，更像是一个增值特性。

**Approach D：路由级"试验页面"（组合 A+ 其他）**
- How：新增 `/experiments/html-in-canvas` 路由，内部做多个小 demo（背景合成、卡片滤镜、导出图片），统一在一个入口展示。
- Pros：隔离最彻底，试验与主 UI 零耦合；便于后续增加新 demo。
- Cons：不直接改造现有渲染路径，"改前端为 HTML-in-Canvas"的叙事弱一些。

## Decision (ADR-lite)

- **Context**：需要在不破坏现有 Radix/assistant-ui 强交互栈的前提下，真实体验 HTML-in-Canvas 对业务场景的价值；xyflow 画布已是 HTML+SVG+内部虚拟化混合渲染，天然适合做 HTML↔Canvas 合成试验。
- **Decision**：采用 Approach B——在 `@xyflow/react` 画布区域内做 HTML-in-Canvas 合成试验。具体合成切片待 MVP 问题收敛后固定。
- **Consequences**：
  - 必须保留 DOM 层处理交互（拖拽/选中/右键/连线），Canvas 只负责视觉合成，坐标通过 xyflow transform 对齐。
  - 不支持环境（非 Chromium / 未开 flag）自动关闭 Canvas 覆盖层，视觉降级但功能不变。
  - 代码全部隔离在 `webui/src/experimental/html-in-canvas/`，动态 import，不影响默认 bundle。
  - 放弃 Approach A/C/D 的部分演示价值，换取业务贴合度。
