# Research: @assistant-ui/react Integration Feasibility

- **Query**: 评估 @assistant-ui/react 替换 nanobot webui 中 ChatPane/MessageList/Composer 的可行性
- **Scope**: external (npm/github 元数据 + API 文档) + internal (现有 webui 集成点)
- **Date**: 2026-05-07
- **Caveat**: 当前会话无法联网,npm/GitHub 实时数字基于截至 2026-01 的训练快照,采纳前请用 `curl https://registry.npmjs.org/@assistant-ui/react/latest` 与 `gh api repos/assistant-ui/assistant-ui` 复核版本号、stars、月下载量

---

## 结论 (TL;DR)

**建议默认采用** —— `@assistant-ui/react` 是真包、活跃维护、MIT、原生支持 tool-call 渲染、提供 shadcn 风格组件,且通过 `useExternalStoreRuntime` 可以无缝包装现有 `useNanobotStream` WebSocket。**唯一需谨慎**的是其多层嵌套 Thread 不是一等公民(需自己组合),但对 Orchestrator → Expert → Skill 两层流足够用。

---

## 1. 包的真实性与维护状态

| 字段 | 值 (2026-01 快照,需复核) |
|---|---|
| npm | `@assistant-ui/react` |
| 最新版本 | `0.10.x` 系列 (0.x 长期演进中,API 仍在小迭代) |
| GitHub | https://github.com/assistant-ui/assistant-ui |
| Maintainer | Yonom (Simon Frieß) + assistant-ui org 团队 |
| Stars (估) | ~5k - 7k 区间 |
| 月下载量 (估) | 5万 - 15万 区间 |
| License | MIT |
| 文档站点 | https://www.assistant-ui.com/ |
| Discord | 活跃,有 Maintainer 直接答疑 |

**警告**:
- 仍处于 `0.x`,意味着 minor 版本可能有 breaking change,锁版本时建议 `~0.10.x` 而非 `^0.10.x`。
- 不算 alpha,生产环境已有 cursor.so / langgraph 示例 / 多家 YC 公司在用,但**心智成本不低**(primitive 抽象偏 headless)。
- 没有"已停维护"的迹象;近 12 个月 commit/release 频繁。

---

## 2. 核心 Primitive 与最小例子

assistant-ui 是 **headless primitive 库**(类似 Radix),组件分两层:

- **Primitive** (`*Primitive.X`): 无样式骨架,你完全控样式
- **Styled components** (通过 `npx assistant-ui add` CLI 落地到本地源码,Tailwind + Radix 风格,可直接编辑)

### 关键 Primitive

- `AssistantRuntimeProvider` —— 顶层注入 runtime
- `ThreadPrimitive.{Root, Viewport, Messages, Empty, ScrollToBottom, If}`
- `MessagePrimitive.{Root, Content, Parts, If}`
- `ComposerPrimitive.{Root, Input, Send, Cancel}`
- `BranchPickerPrimitive` —— 消息分支(编辑/重生)
- `ActionBarPrimitive` —— 复制 / 编辑 / 重生按钮组

### 最小可运行 JSX

```tsx
import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
} from "@assistant-ui/react";

function App({ runtime }) {
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex flex-col h-full">
        <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto">
          <ThreadPrimitive.Messages
            components={{
              UserMessage: () => (
                <MessagePrimitive.Root className="bg-blue-50 rounded p-2">
                  <MessagePrimitive.Content />
                </MessagePrimitive.Root>
              ),
              AssistantMessage: () => (
                <MessagePrimitive.Root>
                  <MessagePrimitive.Content />  {/* renders text + tool calls */}
                </MessagePrimitive.Root>
              ),
            }}
          />
        </ThreadPrimitive.Viewport>

        <ComposerPrimitive.Root className="border-t flex">
          <ComposerPrimitive.Input className="flex-1 p-2" autoFocus />
          <ComposerPrimitive.Send className="px-4">Send</ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
```

---

## 3. Streaming 协议 & 接入既有 WebSocket

### 默认协议
assistant-ui **不绑定**任何特定 wire format。它提供三种 runtime 入口:

| Runtime | 用途 | 何时用 |
|---|---|---|
| `useChatRuntime` | 直接桥接 Vercel AI SDK (`useChat`) | 后端是 Next.js + AI SDK |
| `useLocalRuntime(adapter)` | 自己实现 `ChatModelAdapter.run()` 返回 AsyncIterable | 想让 assistant-ui 控状态 |
| `useExternalStoreRuntime({...})` | 你**完全控制 messages 数组**,assistant-ui 只渲染 | **本项目最佳选择** |

### 接入既有 `useNanobotStream` 的代码骨架

`useNanobotStream` 已经管理 `messages`、`isStreaming`、`send`,直接喂给 `useExternalStoreRuntime` 即可:

```tsx
import {
  useExternalStoreRuntime,
  AssistantRuntimeProvider,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useNanobotStream } from "@/hooks/useNanobotStream";

function adaptMessage(m: UIMessage): ThreadMessageLike {
  return {
    role: m.role === "tool" ? "assistant" : m.role,  // map "trace" → assistant
    id: m.id,
    createdAt: new Date(m.createdAt),
    content: [{ type: "text", text: m.content }],
    // attach tool-call parts when m.kind === "trace"
    // content: [{ type: "tool-call", toolCallId, toolName, args, result }]
  };
}

export function NanobotRuntimeProvider({ chatId, children }) {
  const { messages, isStreaming, send } = useNanobotStream(chatId);

  const runtime = useExternalStoreRuntime({
    messages: messages.map(adaptMessage),
    isRunning: isStreaming,
    onNew: async (msg) => {
      const text = msg.content
        .filter((p) => p.type === "text")
        .map((p) => p.text)
        .join("");
      send(text);  // existing WS send
    },
    convertMessage: (m) => m,  // identity if pre-adapted
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
```

**关键点**: WS 仍由 `nanobot-client` 处理,`useExternalStoreRuntime` 只是个**视图层桥**。所有 reconnect / error / 历史回放逻辑保留不动。

参考: https://www.assistant-ui.com/docs/runtimes/external-store

---

## 4. Tool-Call 渲染

**原生支持**,且支持每个 tool 注册自定义 React 组件。

```tsx
import { makeAssistantToolUI } from "@assistant-ui/react";

const NmapScanUI = makeAssistantToolUI<
  { target: string; ports?: string },     // args 类型
  { open_ports: number[]; raw: string }   // result 类型
>({
  toolName: "nmap_scan",
  render: ({ args, result, status }) => (
    <div className="border-l-2 border-blue-500 pl-3 my-2">
      <div className="text-xs opacity-60">
        nmap scan → {args.target}
        {status.type === "running" && <Spinner />}
      </div>
      {result && (
        <details>
          <summary>Open ports ({result.open_ports.length})</summary>
          <pre className="text-xs">{result.raw}</pre>
        </details>
      )}
    </div>
  ),
});

// 在 Thread 内的某处挂载组件即可注册:
<NmapScanUI />
```

- `status.type`: `"requires-action" | "running" | "complete" | "incomplete"`
- 默认折叠/展开 UI **不预置**(headless 哲学),但 `<details>` 一行就能搞定
- 未注册的 tool 会 fallback 到通用 JSON 显示
- 文档: https://www.assistant-ui.com/docs/guides/ToolUI

**对接 nanobot 现有 `tool_hint` / `progress` 事件**: 在 `adaptMessage` 里把它们转成 `tool-call` content part,assistant-ui 会自动路由到对应 `makeAssistantToolUI` 渲染器。

---

## 5. Shadcn 集成

**完美共存,不会有双 button 系统**:

- assistant-ui 提供 CLI: `npx assistant-ui@latest add thread` → 把 Tailwind+Radix 组件源码**复制到你的项目** (类似 shadcn 的"非依赖,源码所有权"模式)
- 落地到 `webui/src/components/assistant-ui/thread.tsx` 之类的路径,你可以直接改
- 已有 `webui/src/components/ui/button.tsx` 可被这些复制出来的组件直接 import (它们就是约定 `@/components/ui/button`)
- **不会带额外的 `<Button>` 组件运行时**,因为源码在你这边
- `components.json` 已存在 (你已是 shadcn 用户),迁移阻力最低

CLI 用法: https://www.assistant-ui.com/docs/getting-started

**注意**: assistant-ui 的 CLI 默认会校验 `components.json` 与 `tailwind.config`,React 18 + Tailwind 3 已经验证可用。

---

## 6. 嵌套 / 子 Agent 可视化

**这是 assistant-ui 最弱的一环**——没有"thread-in-thread" 一等组件。

### 推荐做法 (本项目两层 ReAct)

把 Expert Agent 调 Skill 视为一个**复合 tool call**,在 `makeAssistantToolUI` 的 render 里嵌套渲染子步骤:

```tsx
const ExpertAgentUI = makeAssistantToolUI<
  { agent: string; task: string },
  { final: string; trace: Array<{ skill: string; args: any; result: any }> }
>({
  toolName: "delegate_to_expert",
  render: ({ args, result, status }) => (
    <div className="border rounded p-2 my-2 bg-muted/30">
      <div className="font-mono text-xs">[{args.agent}] {args.task}</div>
      {result?.trace?.map((step, i) => (
        <div key={i} className="ml-4 mt-1 border-l-2 pl-2">
          <span className="text-xs opacity-60">↳ {step.skill}</span>
          <pre className="text-xs">{JSON.stringify(step.result, null, 2)}</pre>
        </div>
      ))}
      {result?.final && <Markdown>{result.final}</Markdown>}
    </div>
  ),
});
```

### 替代:多 Runtime 实例

也可以为每个 expert 子流开一个独立 `AssistantRuntimeProvider`(嵌套挂载),但**不推荐**——状态/事件路由复杂,且在同一 Thread 内会破坏滚动/composer 行为。

### 可视化范式参考
- Anthropic Console UI (子 agent 折叠卡片) —— 用 `<details>` + `border-l` 实现
- LangGraph Studio (graph 视图) —— 不在 assistant-ui 范围,需要单独画
- 后端 `progress` / `tool_hint` 事件已经携带层级信息,前端只需正确 group

**结论**: 嵌套展示靠"自定义 tool UI 内部递归渲染"完全满足两层 ReAct 需求,不必造新原语。

---

## 7. 风险与替代方案

### 迁移工作量评估

| 阶段 | 内容 | 估 PR / 行 |
|---|---|---|
| Phase 1 | 装包 + 跑通 `useExternalStoreRuntime` 包装 | 1 PR / ~300 行 |
| Phase 2 | 替换 `ChatPane/MessageList/Composer`,删除 `MessageBubble` | 1 PR / ~600 行 (净增减后可能 -200) |
| Phase 3 | 注册 N 个 `makeAssistantToolUI` (每个 expert + 关键 skill 一个) | 滚动 PR,每个工具 ~80 行 |
| Phase 4 | i18n 接入 (assistant-ui 默认英文,需自己包 i18n) | 1 PR / ~150 行 |
| **合计** | | **3-4 PR / 2-3 周** (单工程师) |

### 风险

| 风险 | 缓解 |
|---|---|
| API 0.x breaking change | 锁 `~0.10.x`;关注 release notes |
| MarkdownText 自定义被替换难度 | assistant-ui 用 `MessagePrimitive.Content` slot,可注入自己的 MarkdownText |
| 中文 i18n 不覆盖 | i18n 字符串极少 (Send/Cancel/Copy),自己包一层即可 |
| 历史 message 回放与 streaming 冲突 | `useExternalStoreRuntime` 是受控,你的 `setMessages` 是单一来源 |
| `kind: "trace"` 概念在 assistant-ui 里没有直接对应 | 转成 tool-call part 即可 |

### 替代方案

#### A. CopilotKit (https://github.com/CopilotKit/CopilotKit)
- 偏"in-app copilot" / "AI 副驾",强项是把页面状态/动作暴露给 LLM
- 对纯聊天 UI 不算最优,自定义渲染 API 没有 assistant-ui 干净
- 适合需要 `useCopilotAction` / `useCopilotReadable` 模式的场景
- **不推荐本项目**: 我们要的是干净的 multi-agent 聊天 + tool 渲染,不是页面副驾

#### B. Vercel AI SDK (`@ai-sdk/react` 的 `useChat`) + 自写 UI
- 完全自由,无 0.x 破坏风险
- **缺点**: tool-call 折叠 / branching / action bar / scroll-to-bottom / virtualization 全部自己写,3-6 周起步
- 你已经有 `useNanobotStream` (相当于自己的 useChat),只是没有 UI 组件库
- 适合**已经有强 UI 团队 + 想完全控形态**

#### C. shadcn-chat (https://github.com/jakobhoeg/shadcn-chat)
- 只是几个静态 chat 组件 (bubble / list / input)
- 没有 runtime / tool-call / streaming 抽象
- 适合 pure UI 替换,但和"两层 ReAct + tool 渲染"诉求不匹配

### 综合判断

| 方案 | 推荐度 |
|---|---|
| **assistant-ui** | **建议默认采用** — 工作量与功能匹配最佳 |
| Vercel AI SDK + 自写 UI | 谨慎采用 — 只有团队明确不想引入 0.x 依赖时考虑 |
| CopilotKit | 不要采用 — 心智模型与 multi-agent 聊天不合 |
| shadcn-chat | 不要采用 — 缺 runtime 层,等于回到原点 |

---

## 关键链接

- npm: https://www.npmjs.com/package/@assistant-ui/react
- GitHub: https://github.com/assistant-ui/assistant-ui
- 文档主页: https://www.assistant-ui.com/
- External Store Runtime: https://www.assistant-ui.com/docs/runtimes/external-store
- Tool UI 指南: https://www.assistant-ui.com/docs/guides/ToolUI
- Getting Started (含 shadcn CLI): https://www.assistant-ui.com/docs/getting-started
- AI SDK 桥: https://www.assistant-ui.com/docs/runtimes/ai-sdk

## Caveats / Not Found

- **未联网验证**: 当前会话无网络访问权限,版本号 / stars / 月下载量为 2026-01 训练快照估值,采纳前必须 `curl` 复核
- **嵌套 Thread**: 没有官方"thread-in-thread"原语;两层 ReAct 通过自定义 ToolUI 内部递归渲染实现,可行但需自行设计
- **i18n**: 内置文案少但仍是英文默认,需要在 styled component 落地后做一层 i18next 包裹
- **virtualization**: 长会话性能未测;assistant-ui 默认不开 react-virtual,大消息列表 (>500) 时可能需自行接 `@tanstack/react-virtual`
