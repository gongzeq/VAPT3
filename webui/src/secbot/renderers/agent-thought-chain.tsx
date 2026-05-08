import type { ToolCallContentPartComponent } from "@assistant-ui/react";
import {
  Brain,
  ChevronDown,
  FileText,
  Loader2,
  Search,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { AnimatedShinyText } from "@/components/magicui/animated-shiny-text";
import { BorderBeam } from "@/components/magicui/border-beam";
import { Card } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import { StatusPill } from "./_shared";

/**
 * AgentThoughtChain — orchestrator reasoning renderer.
 *
 * Registered under the reserved tool name `__thought__` in
 * `secbot/tool-ui.tsx::SKILL_RENDERERS`. Consumed by
 * `MessagePrimitive.Content components.tools.by_name["__thought__"]` so
 * reasoning tokens get their own visual treatment without introducing a
 * fourth top-level MessageBubble sub-component.
 *
 * Contract: `.trellis/spec/frontend/component-patterns.md` §1.3
 * Wire: `.trellis/spec/backend/websocket-protocol.md` §3.1
 *
 * Motion: the BorderBeam + AnimatedShinyText only engage while
 * `status === "running"` AND the user has NOT opted out of motion. We rely on
 * the Tailwind `motion-reduce:*` variants — the beam overlay is hidden and
 * the shimmer degrades to plain text — so PRD R7's reduced-motion requirement
 * is honoured without a runtime prefers-reduced-motion hook.
 */

type ThoughtIcon = "brain" | "wrench" | "search" | "filetext";

interface ThoughtArgs {
  step_id?: string;
  title?: string;
  icon?: ThoughtIcon;
  parent_step_id?: string;
}

interface ThoughtResult {
  status?: "running" | "ok" | "error";
  tokens?: string;
  duration_ms?: number;
  next_action?: string;
}

const ICON_MAP: Record<ThoughtIcon, LucideIcon> = {
  brain: Brain,
  wrench: Wrench,
  search: Search,
  filetext: FileText,
};

function resolveIcon(icon: ThoughtIcon | undefined): LucideIcon {
  if (!icon) return Brain;
  return ICON_MAP[icon] ?? Brain;
}

function formatDuration(ms: number | undefined): string | null {
  if (typeof ms !== "number" || Number.isNaN(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export const AgentThoughtChainRenderer: ToolCallContentPartComponent = ({
  args,
  result,
}) => {
  const a = (args ?? {}) as ThoughtArgs;
  const r = (result ?? {}) as ThoughtResult;

  // Derive the active status. assistant-ui does not always populate `result`
  // until the server emits tool.result; treat "undefined result" as running
  // so the streaming affordances show up on tool.call / tool.progress.
  const status: "running" | "ok" | "error" = r.status ?? "running";
  const isRunning = status === "running";
  const isError = status === "error";

  const Icon = resolveIcon(a.icon);
  const tokens = r.tokens ?? "";
  const duration = formatDuration(r.duration_ms);

  return (
    <div
      className="relative my-2"
      data-testid="agent-thought-chain"
      data-status={status}
      data-step-id={a.step_id}
    >
      {/* Default-open so operators see the full reasoning without an extra
          click; batching/collapsing of historical chains is the responsibility
          of the outer MessageBubble timeline, not this renderer. */}
      <Collapsible defaultOpen>
        <Card
          className={cn(
            "relative overflow-hidden border-border/60 bg-card/80 p-0 shadow-none",
            "backdrop-blur-[2px]",
            isError && "border-[hsl(var(--sev-critical))]/50",
          )}
        >
          {/* BorderBeam only while running + motion is allowed. `motion-reduce:hidden`
              is the documented Tailwind escape hatch for prefers-reduced-motion. */}
          {isRunning && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 motion-reduce:hidden"
              data-testid="agent-thought-chain-beam"
            >
              <BorderBeam
                size={60}
                duration={8}
                colorFrom="hsl(var(--brand-deep))"
                colorTo="hsl(var(--primary))"
              />
            </div>
          )}

          <CollapsibleTrigger
            className={cn(
              "group flex w-full items-center gap-2 px-3 py-2 text-left text-sm",
              "outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary))]",
            )}
            aria-label={a.title ? `思考：${a.title}` : "思考链步骤"}
          >
            <Icon
              className={cn(
                "h-4 w-4 shrink-0",
                isRunning
                  ? "text-[hsl(var(--primary))]"
                  : isError
                    ? "text-[hsl(var(--sev-critical))]"
                    : "text-[hsl(var(--brand-deep))]",
              )}
              aria-hidden
            />
            <span className="flex-1 truncate font-medium text-text-primary">
              {isRunning ? (
                <AnimatedShinyText
                  className="mx-0 inline-block max-w-full text-text-primary motion-reduce:animate-none motion-reduce:bg-none motion-reduce:[background-image:none]"
                  shimmerWidth={120}
                >
                  {a.title ?? "思考中…"}
                </AnimatedShinyText>
              ) : (
                <span>{a.title ?? "思考步骤"}</span>
              )}
            </span>
            {duration && !isRunning && (
              <span
                className="shrink-0 font-mono text-xs text-text-secondary"
                data-testid="agent-thought-chain-duration"
              >
                {duration}
              </span>
            )}
            {isRunning && (
              <Loader2
                className="h-3.5 w-3.5 shrink-0 animate-spin text-[hsl(var(--primary))] motion-reduce:animate-none"
                aria-hidden
              />
            )}
            <StatusPill status={status} />
            <ChevronDown
              className="h-4 w-4 shrink-0 text-text-secondary transition-transform duration-200 group-data-[state=open]:rotate-180 motion-reduce:transition-none"
              aria-hidden
            />
          </CollapsibleTrigger>

          <CollapsibleContent className="border-t border-border-subtle/70 px-3 py-2 text-xs text-text-secondary">
            {tokens ? (
              <pre
                className={cn(
                  "whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed text-text-primary/90",
                  isRunning &&
                    "after:ml-0.5 after:inline-block after:w-1.5 after:animate-pulse after:content-['▍'] motion-reduce:after:animate-none",
                )}
                data-testid="agent-thought-chain-tokens"
              >
                {tokens}
              </pre>
            ) : (
              <span className="italic">
                {isRunning ? "(正在推理…)" : "(无推理细节)"}
              </span>
            )}
            {r.next_action && !isRunning && (
              <div className="mt-2 flex items-center gap-1.5 text-text-secondary">
                <span className="font-medium">下一步：</span>
                <span className="truncate">{r.next_action}</span>
              </div>
            )}
            {a.parent_step_id && (
              <div className="mt-1.5 font-mono text-[10.5px] text-text-secondary/70">
                ← 承接 {a.parent_step_id}
              </div>
            )}
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  );
};
