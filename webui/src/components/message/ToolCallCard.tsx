import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AgentEventPayload, ToolCallStatus } from "@/lib/types";

/** Reason strings that map ``status=error`` onto the neutral info palette.
 * Backend emits ``user_denied`` on explicit deny and ``timeout`` on the 120s
 * auto-deny path (see subagent._classify_terminal). */
const DENIED_REASONS = new Set(["user_denied", "timeout"]);

type ToolCardVariant = ToolCallStatus | "denied";

const TOOL_STATUS_STYLE: Record<
  ToolCardVariant,
  { border: string; bg: string; icon: string; text: string }
> = {
  running: {
    border: "border-primary/30",
    bg: "bg-primary/5",
    icon: "text-primary",
    text: "text-primary",
  },
  critical: {
    border: "border-alert-warning/40",
    bg: "bg-alert-warning/5",
    icon: "text-alert-warning",
    text: "text-alert-warning",
  },
  ok: {
    border: "border-alert-success/30",
    bg: "bg-alert-success/5",
    icon: "text-alert-success",
    text: "text-alert-success",
  },
  error: {
    border: "border-destructive/30",
    bg: "bg-destructive/5",
    icon: "text-destructive",
    text: "text-destructive/90",
  },
  denied: {
    border: "border-[hsl(var(--sev-info)/0.35)]",
    bg: "bg-[hsl(var(--sev-info)/0.08)]",
    icon: "text-[hsl(var(--sev-info))]",
    text: "text-[hsl(var(--sev-info))]",
  },
};

function recordArgs(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function toolCallArgs(payload: AgentEventPayload): Record<string, unknown> | undefined {
  const toolArgs = recordArgs(payload.tool_args);
  if (toolArgs && Object.keys(toolArgs).length > 0) return toolArgs;
  const args = recordArgs(payload.args);
  if (args && Object.keys(args).length > 0) return args;
  return toolArgs ?? args;
}

/** Compact status badge label for a tool call. */
function toolStatusLabel(variant: ToolCardVariant, durationMs?: number): string {
  const dur =
    durationMs == null
      ? ""
      : durationMs < 1000
        ? ` ${durationMs}ms`
        : ` ${(durationMs / 1000).toFixed(1)}s`;
  switch (variant) {
    case "running":
      return "运行中";
    case "critical":
      return "待审批";
    case "ok":
      return `✓ 成功${dur}`;
    case "denied":
      return "✕ 已拒绝";
    case "error":
      return "✕ 失败";
  }
}

/** @description Collapsible tool-call card rendered inside an assistant bubble. */
export function ToolCallCard({
  payload,
  animClass,
  defaultExpanded = false,
}: {
  payload: AgentEventPayload;
  animClass?: string;
  defaultExpanded?: boolean;
}) {
  const status = (payload.tool_status ?? payload.status ?? "running") as ToolCallStatus;
  const variant: ToolCardVariant =
    status === "error" && payload.reason && DENIED_REASONS.has(payload.reason)
      ? "denied"
      : status;
  const style = TOOL_STATUS_STYLE[variant];
  const [open, setOpen] = useState(defaultExpanded);
  useEffect(() => { if (defaultExpanded) setOpen(true); }, [defaultExpanded]);
  const args = toolCallArgs(payload);
  const hasArgs = args && Object.keys(args).length > 0;
  const argsSummary = hasArgs ? JSON.stringify(args).slice(0, 90) : "";

  return (
    <div
      className={cn(
        "rounded-lg border bg-popover text-xs leading-snug overflow-hidden",
        style.border,
        animClass,
      )}
    >
      {/* Foldable head */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2.5 px-3 py-2 text-left",
          "transition-colors hover:bg-accent/40",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-90",
          )}
          aria-hidden
        />
        <span className="shrink-0 font-mono font-semibold text-ocean-300">
          {payload.tool_name ?? "tool"}
        </span>
        {argsSummary ? (
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground/80">
            {argsSummary}
          </span>
        ) : (
          <span className="flex-1" />
        )}
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold",
            variant === "ok" && "bg-alert-success/15 text-alert-success",
            variant === "running" && "bg-primary/15 text-primary",
            variant === "critical" && "bg-alert-warning/15 text-alert-warning",
            variant === "error" && "bg-destructive/15 text-destructive",
            variant === "denied" &&
              "bg-[hsl(var(--sev-info)/0.12)] text-[hsl(var(--sev-info))]",
          )}
        >
          {toolStatusLabel(variant, payload.duration_ms)}
        </span>
      </button>

      {/* Body */}
      {open && (
        <div className="border-t border-border-subtle/60 bg-background/50 px-3 py-2.5 font-mono text-xs leading-relaxed">
          {payload.reason && (variant === "error" || variant === "denied") ? (
            <p className={cn("mb-2 whitespace-pre-wrap break-words", style.text)}>
              {payload.reason}
            </p>
          ) : null}
          {hasArgs ? (
            <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words text-muted-foreground/90">
              {JSON.stringify(args, null, 2)}
            </pre>
          ) : (
            <span className="text-muted-foreground/60">无参数</span>
          )}
        </div>
      )}
    </div>
  );
}
