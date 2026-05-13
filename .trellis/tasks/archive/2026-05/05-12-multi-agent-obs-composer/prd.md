# P2: Composer 工具白名单提示行

## Goal

在 [`ThreadComposer.tsx`](../../src/components/thread/ThreadComposer.tsx) 输入框上方加一行 meta 文案，明示 orchestrator 只能用 4 个工具（`delegate_task` / `read_blackboard` / `write_plan` / `request_approval`），让用户对编排能力边界有预期。来源 [`webui/src/gap/assistant-multi-agent.md`](../../../webui/src/gap/assistant-multi-agent.md) Task 4（P2，约 0.25d）。

## What I already know

- orchestrator 4 工具白名单已在 `05-12-orchestrator-tool-whitelist` 任务交付（已归档）
- `ThreadComposer.tsx` 已有 slash commands 下拉，无 meta 描述行
- 4 个工具名固定，前端写死即可，不需要后端 API
- 原型 [`UI/prototype-assistant-multi-agent.html`](../../../UI/prototype-assistant-multi-agent.html) 在 composer 上方有类似 hint 行（小字 + muted 色）

## Decision Log

- **D1 不读后端配置**：4 工具名前端硬编码常量，避免为这 4 个名字新增 API
- **D2 文案**：`可用工具：delegate_task / read_blackboard / write_plan / request_approval`，使用 `text-xs text-muted-foreground` 样式
- **D3 显示位置**：composer 输入框正上方、附件按钮右侧；空闲时常显，输入时不隐藏（不抢焦点）

## Requirements

- 在 [`ThreadComposer.tsx`](../../src/components/thread/ThreadComposer.tsx) 输入框上方添加一行 hint：
  - 文案：`可用工具：delegate_task · read_blackboard · write_plan · request_approval`
  - 样式：`text-xs text-muted-foreground`，左侧加 `Wrench` / `Sparkles` 类小图标
  - 可选：4 个工具名带 `<code>` 包裹用 mono 字体
- 不影响现有 slash commands 下拉、附件按钮、Send 按钮交互

## Acceptance Criteria

1. 进入任意 chat 看到 composer 顶部有该 hint 行
2. 输入文本时 hint 不消失也不抖动
3. 移动端窄屏（< 640px）hint 可省略 1-2 个工具名（用 `…` 兜底）或换行不破版
4. 不引入新依赖、不调后端

## Open Questions

- _(交付时如有再补充)_

## Out of Scope

- 把 4 工具名做成可点击的 slash command 快捷入口（后续迭代）
- 后端读取动态白名单（orchestrator 配置当前固定 4 个，不需要动态化）

## Technical Notes

### 关键文件
- `webui/src/components/thread/ThreadComposer.tsx`
- `UI/prototype-assistant-multi-agent.html` —— composer hint 视觉基线
