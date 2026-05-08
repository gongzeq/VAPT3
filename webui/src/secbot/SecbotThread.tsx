import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react";

import { AnimatedShinyText } from "@/components/magicui/animated-shiny-text";
import { BorderBeam } from "@/components/magicui/border-beam";
import { cn } from "@/lib/utils";

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
 *
 * Ocean-tech styling (PR4-R5):
 *   - Root wraps a `<BorderBeam>` (brand-deep → primary sweep) around the
 *     whole chat surface. Beam is hidden under `motion-reduce` via its
 *     container class.
 *   - User bubble: brand-light tint (0.14) with 0.22 ring — mirrors main
 *     Shell `<MessageBubble>` (PR3-R4) so secbot chat feels unified.
 *   - Empty state: `<AnimatedShinyText>` streak on the prompt (motion-safe
 *     only; falls back to muted text under motion-reduce).
 *   - Composer: brand-deep top border + primary-glow send button.
 */

function UserMessage() {
  return (
    <MessagePrimitive.Root data-role="user" className="my-3 flex justify-end">
      <div
        className={cn(
          "max-w-[80%] rounded-[18px] px-3 py-2 text-sm text-text-primary",
          "bg-[hsl(var(--brand-light)/0.14)] ring-1 ring-[hsl(var(--brand-light)/0.22)]",
        )}
      >
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
    <div className="flex h-full items-center justify-center px-4">
      <AnimatedShinyText className="text-sm text-text-secondary motion-reduce:animate-none">
        开始与 secbot 对话以发起扫描或查询资产。
      </AnimatedShinyText>
    </div>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root
      className={cn(
        "flex items-end gap-2 border-t px-4 py-3",
        "border-[hsl(var(--brand-deep)/0.25)] bg-card",
      )}
    >
      <ComposerPrimitive.Input
        className={cn(
          "min-h-[2.25rem] flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm",
          "border-[hsl(var(--brand-deep)/0.20)] text-text-primary placeholder:text-text-secondary",
          "focus:outline-none focus:ring-1 focus:ring-[hsl(var(--primary))]",
        )}
        placeholder="发送指令给 secbot…"
        rows={1}
      />
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel
          className={cn(
            "rounded-md border px-3 py-2 text-sm",
            "border-[hsl(var(--brand-deep)/0.25)] text-text-secondary hover:bg-[hsl(var(--brand-light)/0.08)]",
          )}
        >
          停止
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send
          className={cn(
            "rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground",
            "shadow-[0_0_10px_hsl(var(--primary)/0.35)] hover:opacity-90",
            "disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none",
          )}
        >
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
      <ThreadPrimitive.Root className="relative flex h-full min-h-0 flex-col overflow-hidden bg-background">
        {/* Ambient beam sweep across the chat surface */}
        <BorderBeam
          size={140}
          duration={22}
          className="motion-reduce:hidden"
        />
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
