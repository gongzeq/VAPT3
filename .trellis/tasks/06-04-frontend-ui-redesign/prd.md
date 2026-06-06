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

* R1: 统一间距 token 系统
* R2: 统一字体层级（正文/标题/标签/代码）
* R3: 思维链/工具调用/事件卡片默认折叠
* R4: 对话 turn 间有明确视觉分隔
* R5: 助手回复更抓眼球（品牌色/动效/层次）

## Open Questions

* Q1: 对话 turn 间的分隔方式偏好

## Out of Scope

* 不改后端 API
* 不改 Dashboard/Settings 等非对话页面
* 不引入新 CSS 框架

## Technical Notes

* 核心文件: MessageBubble.tsx, ThreadMessages.tsx, ThreadViewport.tsx, globals.css, tailwind.config.js
