import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react";

import { useSecbotRuntime, type SecbotRuntimeOptions } from "./runtime";
import { SKILL_RENDERERS } from "./tool-ui";
import { ToolCallCard } from "./renderers/tool-call-card";

/**
 * Top-level chat surface for secbot.
 *
 * Wires:
 *   - SecbotChatRuntime → /api/ws (orchestrator + skill streaming)
 *   - assistant-ui v0.10 Thread/Message/Composer primitives (no styled `<Thread>`
 *     export exists in 0.10.x; we own the composition)
 *   - per-skill tool-call renderers from `tool-ui.tsx`, registered via
 *     `MessagePrimitive.Content components.tools.by_name`
 *   - generic <ToolCallCard> as the `Fallback` for any unregistered skill
 *
 * v0.10 API note: tool-call rendering lives on `MessagePrimitive.Content`
 * (the alias of `MessagePrimitive.Parts`), NOT on the (since-removed) styled
 * `<Thread>` component. See `.trellis/tasks/05-07-ocean-tech-frontend/research/
 * assistant-ui-customization.md` §4 for the verified contract.
 */

function UserMessage() {
  return (
    <MessagePrimitive.Root
      data-role="user"
      className="my-3 flex justify-end"
    >
      <div className="max-w-[80%] rounded-md bg-primary/10 px-3 py-2 text-sm text-text-primary">
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root
      data-role="assistant"
      className="my-3 flex justify-start"
    >
      <div className="max-w-[90%] text-sm text-text-primary">
        <MessagePrimitive.Content
          components={{
            tools: {
              by_name: SKILL_RENDERERS,
              Fallback: ToolCallCard,
            },
          }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center px-4 text-sm text-text-secondary">
      开始与 secbot 对话以发起扫描或查询资产。
    </div>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="flex items-end gap-2 border-t border-border bg-card px-4 py-3">
      <ComposerPrimitive.Input
        className="min-h-[2.25rem] flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-primary"
        placeholder="发送指令给 secbot…"
        rows={1}
      />
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel className="rounded-md border border-border px-3 py-2 text-sm text-text-secondary hover:bg-popover">
          停止
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50">
          发送
        </ComposerPrimitive.Send>
      </ThreadPrimitive.If>
    </ComposerPrimitive.Root>
  );
}

export function SecbotThread(props: SecbotRuntimeOptions = {}) {
  const runtime = useSecbotRuntime(props);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col bg-background">
        <ThreadPrimitive.Viewport
          autoScroll
          className="flex-1 min-h-0 overflow-auto px-4 py-3 scrollbar-thin"
        >
          <ThreadPrimitive.Empty>
            <EmptyState />
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages
            components={{
              UserMessage,
              AssistantMessage,
            }}
          />
        </ThreadPrimitive.Viewport>
        <Composer />
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
