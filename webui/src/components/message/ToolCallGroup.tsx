import { useState } from "react";
import { ChevronRight, Terminal } from "lucide-react";

import { ToolCallCard } from "@/components/message/ToolCallCard";
import { cn } from "@/lib/utils";
import type { AgentEventPayload, ToolCallStatus } from "@/lib/types";

/** Aggregate status of a tool-call group, ranked by signal priority. */
type GroupVariant = "running" | "critical" | "ok" | "error";

/** Props for {@link ToolCallGroup}. */
export interface ToolCallGroupProps {
  /** Every tool call executed by a single subagent in this turn. */
  calls: AgentEventPayload[];
  /** Optional enter animation class forwarded from the host bubble. */
  animClass?: string;
  children?: never;
}

/** Resolve the effective status of a single tool-call payload. */
function payloadStatus(payload: AgentEventPayload): ToolCallStatus {
  return payload.tool_status ?? payload.status ?? "running";
}

/**
 * Pick the highest-signal status across a group so the collapsed header
 * reflects the worst/most-actionable state: error > critical > running > ok.
 */
function aggregateVariant(calls: AgentEventPayload[]): GroupVariant {
  let hasCritical = false;
  let hasRunning = false;
  for (const call of calls) {
    const status = payloadStatus(call);
    if (status === "error") return "error";
    if (status === "critical") hasCritical = true;
    if (status === "running") hasRunning = true;
  }
  if (hasCritical) return "critical";
  if (hasRunning) return "running";
  return "ok";
}

const GROUP_STYLE: Record<
  GroupVariant,
  { border: string; badge: string; label: string }
> = {
  running: {
    border: "border-primary/30",
    badge: "bg-primary/15 text-primary",
    label: "执行中",
  },
  critical: {
    border: "border-alert-warning/40",
    badge: "bg-alert-warning/15 text-alert-warning",
    label: "待审批",
  },
  ok: {
    border: "border-alert-success/30",
    badge: "bg-alert-success/15 text-alert-success",
    label: "已完成",
  },
  error: {
    border: "border-destructive/30",
    badge: "bg-destructive/15 text-destructive",
    label: "有失败",
  },
};

/**
 * @description Collapsible container that aggregates every command (tool call)
 * executed by a single subagent into one bubble. Collapsed by default so a
 * busy subagent never floods the thread; expanding reveals each individual
 * {@link ToolCallCard}. The header surfaces the command count, completed
 * progress, and the highest-signal aggregate status.
 */
export function ToolCallGroup({ calls, animClass }: ToolCallGroupProps) {
  const [open, setOpen] = useState(false);
  if (calls.length === 0) return null;

  const variant = aggregateVariant(calls);
  const style = GROUP_STYLE[variant];
  const doneCount = calls.filter((call) => {
    const status = payloadStatus(call);
    return status === "ok" || status === "error";
  }).length;

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border bg-popover text-xs leading-snug",
        style.border,
        animClass,
      )}
    >
      {/* Foldable head — single click toggles the whole subagent group. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2.5 px-3 py-2 text-left",
          "transition-colors hover:bg-accent/40",
        )}
        aria-expanded={open}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-90",
          )}
          aria-hidden
        />
        <Terminal className="h-3.5 w-3.5 shrink-0 text-ocean-300" aria-hidden />
        <span className="shrink-0 font-medium text-foreground">执行命令</span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground/80">
          {doneCount}/{calls.length}
        </span>
        <span className="flex-1" />
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold",
            style.badge,
          )}
        >
          {style.label}
        </span>
      </button>

      {/* Body — every command rendered as its own ToolCallCard. */}
      {open && (
        <div
          className={cn(
            "space-y-2 border-t border-border-subtle/60 bg-background/40 px-2.5 py-2.5",
            "animate-in fade-in-0 slide-in-from-top-1 duration-200",
          )}
        >
          {calls.map((tc, i) => (
            <ToolCallCard key={`${tc.tool_call_id ?? i}-${i}`} payload={tc} />
          ))}
        </div>
      )}
    </div>
  );
}
