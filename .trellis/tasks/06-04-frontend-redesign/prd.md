# brainstorm: 前端对话界面统一设计与视觉增强

## Goal

重新设计前端对话界面，解决间距/字体不统一、信息过载、视觉平淡三大问题，打造专业且抓眼球的对话体验。

## What I already know

* **间距不统一**: ThreadMessages `gap-5`、MessageBubble 内 `space-y-1.5`/`gap-3`/`px-4 py-3`/`px-4 py-2.5` 混用
* **字体不统一**: 用户消息 `text-sm`、助手消息 `text-sm leading-relaxed`、TraceGroup `text-[11.5px]`、ToolCallCard `text-[12.5px]`/`text-[11px]`/`text-[10px]` 混用、AgentMeta `text-[11px]`
* **折叠行为**: TraceGroup/thought 已默认折叠 ✓；ToolCallCard 非 running 时默认展开（需改为折叠）
* **视觉层次**: 用户消息 gradient-primary 右对齐气泡；助手消息 border 左对齐；但 turn 间无明显区分
* **技术栈**: React + TS + Tailwind + shadcn/ui，secbot 暗色主题

## Requirements (evolving)

* R1: 统一间距 token 系统（消息间 gap-6、卡片内 px-5 py-4）
* R2: 统一字体层级（正文 text-sm、标题 text-base font-semibold、标签 text-xs、代码 text-xs font-mono）
* R3: 思维链/工具调用/智能体事件全部默认折叠，仅显示摘要行
* R4: 每轮对话包裹在卡片中（微妙边框 + 圆角），卡片间 gap-6
* R5: 助手回复无边框铺展在卡片内，用户消息保持海蓝渐变气泡右对齐
* R6: AgentMeta 信息统一 text-xs，ToolCallCard 统一 text-xs

## Acceptance Criteria

* [ ] 所有消息按 turn 分组在卡片中，卡片有 border + rounded-xl
* [ ] 字体尺寸收敛到 3 级：text-xs（标签/元信息）、text-sm（正文）、text-base（标题）
* [ ] ToolCallCard 默认折叠（含已完成和失败状态）
* [ ] thought/orchestrator_plan/subagent_spawned/subagent_done 默认折叠
* [ ] 用户消息保持 gradient-primary 气泡
* [ ] 助手消息无边框，直接铺展在卡片内
* [ ] 间距统一：消息间 gap-6、卡片内边距 px-5 py-4
* [ ] lint/typecheck 通过，不破坏现有功能

## Decision (ADR-lite)

**Context**: 前端对话界面间距/字体不统一，信息过载，视觉平淡
**Decision**: 卡片式分组 + 助手无边框铺展 + 全部折叠 + 用户海蓝渐变气泡
**Consequences**: 改动集中在 MessageBubble.tsx 和 ThreadMessages.tsx，风险低

## Out of Scope

* 不改后端 API
* 不改 Dashboard/Settings 等非对话页面
* 不引入新 CSS 框架
* 不做主题切换功能
* 长对话性能优化（50+ turn 虚拟滚动）

## Technical Notes

* 核心文件: MessageBubble.tsx, ThreadMessages.tsx, ThreadViewport.tsx, globals.css, tailwind.config.js
