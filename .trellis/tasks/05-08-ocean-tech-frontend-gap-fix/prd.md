# ocean-tech-frontend PRD 遗留缺口修复

## Goal

对 `05-07-ocean-tech-frontend` 任务归档后发现的 PRD 未 100% 落实项执行补齐，使交付状态与
其 Acceptance Criteria 严格对齐。任务已于 `4f0abb22` 归档为 completed，但逐条核验发现
3 处硬缺口 + 1 处文档待补。

## What I already know（核验结果，2026-05-08）

### 已落实（无需动）
- PR0 SecbotThread v0.10 API、R1 主题 token、R3 依赖 + 17 个源文件拷贝、R4 主 Shell 5
  文件海蓝化、R6 AgentThoughtChain、R7 VITE_SECBOT_HUD 开关 + bundle gzip +0.62 KB
  全部有代码/测试证据。

### 硬缺口（PRD 明确列入 Acceptance Criteria，但未交付）

#### Gap-1：R5 xyflow agent 调用图（验收第 5 条，硬性）
- PRD §R5：`Scans 历史含 xyflow agent 调用图`
- 现状：
  - [`src/secbot/views/ScanHistoryView.tsx`](../../../webui/src/secbot/views/ScanHistoryView.tsx)
    L60 处注释自承"deferred to PR4 Phase B"
  - [`src/lib/xyflow-bootstrap.ts`](../../../webui/src/lib/xyflow-bootstrap.ts) 仅准备
    CSS 入口，全仓 0 处 import，全仓 0 处 `<ReactFlow>` 使用
  - `@xyflow/react@^12.10` 依赖已安装但未激活

#### Gap-2：R5 6 个工具卡 Tremor Raw 改造（验收第 5 条，硬性）
- PRD §R5：`6 个卡片统一改用 shadcn Card + Tremor Raw Callout / ProgressBar / DonutChart`
- 现状：`webui/src/secbot/renderers/` 下 `cmdb-query / fscan-asset-discovery /
  fscan-vuln-scan / nmap-port-scan / nuclei-template-scan / report` **0 处**使用
  Tremor Raw 组件（经 `grep -E "tremor|DonutChart|ProgressBar|Callout"` 验证）

#### Gap-3：R7 Lighthouse 实测（验收第 7 条，硬性）
- PRD §R7：`Lighthouse Performance ≥ 90（运行 1 次 baseline + 1 次 after，截图记录）`
- 现状：[`.trellis/.runtime/lighthouse-baseline.md`](../../../.trellis/.runtime/lighthouse-baseline.md)
  仅记录"方法论 + 预期 envelope + bundle 基线"，**未执行实际 Lighthouse 运行**，缺失
  `.html` / `.json` 产物与截图
- 备注：文档明确说明"requires running gateway + built WebUI served on a real port; not
  a headless artifact the CI can produce" —— 现在具备本机环境，可真跑

### 文档待补（非硬缺口，但 DoD 列明）
- `webui/README.md` 需补"MagicUI / Tremor Raw / xyflow / 主题 token" 四件套组件库说明
  （验收 DoD 第 3 条）

### 已确认不缺（无需动）
- **R7 prefers-reduced-motion**：MessageBubble / ConnectionBadge / ThreadShell /
  SecbotShell / App 全部有 `motion-reduce:*` 降级（`lighthouse-baseline.md` audit 章节
  有逐文件清单，已审查）
- **R7 i18n zh-CN/en-US**：`src/i18n/config.ts` 已定义 9 语言 + 有 en/zh-CN locales；
  **新增文案是否全走 react-i18next** 核验留到 Task-C 落地时 sweep 一遍，若发现硬编码
  再补。不单独开 task。

## Requirements

1. **R5-DAG**：新建 `webui/src/secbot/components/AgentCallGraph.tsx`，用 `@xyflow/react`
   渲染 orchestrator → 专家 agent → tool 的调用图；挂入 `ScanHistoryView` 作为新页签
   或子区域；节点视觉走海蓝 token；删除 L60 的 deferred 注释
2. **R5-Tremor**：6 个工具卡 renderer 改造为 shadcn `Card` + Tremor Raw 组合：
   - `fscan-vuln-scan` / `nuclei-template-scan`：严重度分布用 `DonutChart`
   - `cmdb-query` / `fscan-asset-discovery` / `nmap-port-scan`：关键 KPI 用 `ProgressBar`
     或 `Callout`
   - `report`：已有 DonutChart 的话保留，按需补 Callout
3. **R7-Lighthouse**：按 `lighthouse-baseline.md` 协议本机跑 2 次（on/off），
   产出 `lighthouse-on.html` + `lighthouse-off.html` + `lighthouse-on.json`
   + `lighthouse-off.json`；截图保存为 `lighthouse-on.png` + `lighthouse-off.png`；
   更新 `lighthouse-baseline.md` 记录实际得分
4. **Docs**：`webui/README.md` 新增 "Component Library" 章节，说明 MagicUI / Tremor Raw
   / xyflow / 主题 token 来源与扩展方式

## Acceptance Criteria

- [ ] **Task-A (R5-DAG)**：`ScanHistoryView` 有"调用图"页签/子区域，`<ReactFlow>` 实际
      渲染 ≥ 3 节点（orchestrator / 1 agent / 1 tool）的样例数据；节点配色走 CSS
      `var(--brand-deep / --brand-light / --primary)`；`@xyflow/react/dist/style.css`
      被 import；至少 1 个 vitest 渲染快照测试
- [ ] **Task-B (R5-Tremor)**：6 个 renderer 文件中**至少**有 4 个新增 Tremor Raw 组件
      import（`@/components/tremor/*`）；严重度相关可视化改为 `DonutChart`；vitest
      原有 snapshot 更新并通过
- [ ] **Task-C (R7-Lighthouse)**：`.trellis/.runtime/` 下生成
      `lighthouse-on.{html,json}` + `lighthouse-off.{html,json}`；两次 Performance 得分
      均 ≥ 90 或 delta ≤ 5 分；`lighthouse-baseline.md` 补写"Actual run" 章节含
      时间戳、得分表
- [ ] **Task-D (Docs)**：`webui/README.md` 含"Component Library"章节引用 MagicUI /
      Tremor Raw / xyflow / theme token 路径
- [ ] `bun run build` / `bun run test` / `bun run tsc --noEmit` 全绿
- [ ] 文件新增处与 `.trellis/spec/frontend/component-patterns.md` 的 motion / token
      规范一致

## Definition of Done

- 所有新增/改造组件有 vitest 渲染测试
- ESLint + tsc + bun test + CI 全绿
- `webui/README.md` 更新
- Lighthouse 实测产物提交到 `.trellis/.runtime/`
- 每个 Task 单独一个 PR，可独立回滚
- 原 `05-07-ocean-tech-frontend` 任务目录不改动；本任务归档后在 journal 指明
  "验收缺口 100% 补齐"

## Technical Approach

### 实现顺序（4 个小 PR）

| PR | 范围 | 估时 | 风险 |
|----|------|------|------|
| **PR-A** | R5-DAG：xyflow AgentCallGraph + ScanHistoryView 挂载 + snapshot | 0.5 天 | 中（xyflow CSS 隔离已在 bootstrap.ts 预备） |
| **PR-B** | R5-Tremor：6 个 renderer 改造 + snapshot 更新 | 0.5 天 | 低（Tremor Raw 源文件已就位） |
| **PR-C** | R7-Lighthouse 实测 + baseline 文档更新 | 0.25 天 | 低（纯执行，环境已备） |
| **PR-D** | README.md 组件库章节 | 0.25 天 | 低 |

**总估时：~1.5 天**

### 关键技术细节

- **xyflow 数据契约**：先用前端 **mock 数据**（不等后端 `/api/agent-graph` REST）绘制
  样例 DAG；节点类型 = `orchestrator | agent | tool`；边按触发顺序连接。后端契约留作
  未来单独 task。这与原 PRD `research/agent-graph-contract.md`（未产出）决策一致。
- **xyflow 节点海蓝化**：wrap 为自定义 React 节点组件，`style={{ background:
  'hsl(var(--brand-deep))', color: 'hsl(var(--foreground))' }}`；禁用默认白色
  MiniMap，或 MiniMap 也走 token。
- **Tremor Raw DonutChart**：严重度 critical/high/medium/low/info 五色走 CSS
  `--severity-*` token（已在 globals.css 定义）。
- **Lighthouse 跑法**：按现有 `lighthouse-baseline.md` Protocol 跑；gateway 已在 8765
  端口运行，`bun run build` 产物写入 `nanobot/web/dist/`。

## Decision (ADR-lite)

**Context**：原 PRD 验收条目 R5 / R7 有部分未落实项被注释为"deferred to PR4 Phase B"
但未创建 follow-up，导致归档为 completed 状态与验收清单不一致。

**Decision**：不回退原任务的 archive 状态；开一个独立 follow-up 任务 `05-08-ocean-
tech-frontend-gap-fix`，只补齐 3 处硬缺口 + 1 处文档。每个缺口 1 个 PR，增量可回滚。

**Consequences**：
- ✅ 保留原任务 commit history 的清晰度
- ✅ 本任务完成后原 PRD 100% 落地
- ⚠️ `.trellis/.runtime/` 文档体系会有"baseline（方法论）" + "actual（实测）" 两层

## Out of Scope (explicit)

- 不改后端 REST/WebSocket 协议（不新增 `/api/agent-graph` 契约）
- 不升级 `@xyflow/react` / Tremor / MagicUI 版本
- 不做 S3 重度 HUD（保持 S2 中度科技感）
- 不做 i18n 全量 sweep（除非 Task-B 过程中发现硬编码再点对点修）
- 不做 Lighthouse CI 集成（仅本机一次性实测）

## Research References

- [`.trellis/tasks/archive/2026-05/05-07-ocean-tech-frontend/prd.md`](../../../.trellis/tasks/archive/2026-05/05-07-ocean-tech-frontend/prd.md)
  — 原任务 PRD + ADR
- [`.trellis/.runtime/lighthouse-baseline.md`](../../../.trellis/.runtime/lighthouse-baseline.md)
  — Lighthouse 方法论 + bundle 基线 + motion-reduce audit
- [`.trellis/spec/frontend/component-patterns.md`](../../../.trellis/spec/frontend/component-patterns.md)
  — token / motion 规范（Task-B 改造时遵守）

## Technical Notes

- `@xyflow/react@^12.10` + `framer-motion@^11` 已在 `webui/package.json`
- `webui/src/components/tremor/` 已就位 7 个组件（`donut-chart.tsx` /
  `progress-bar.tsx` / `callout.tsx` 等）
- `webui/src/lib/xyflow-bootstrap.ts` 已存在但无人引用 —— Task-A 需 import
- gateway 已在 ws://127.0.0.1:8765 运行（本会话前置），Task-C 可直接跑 Lighthouse
- `src/secbot/renderers/__tests__/` 下有已有快照，Task-B 改造后需 `bun run test -u`
