import { cn } from "@/lib/utils";
import type { TaskStatus } from "@/data/mock/task-detail";

/**
 * Semantic badge for task status — 7 states per R7.1 state machine.
 * Includes a ping dot for "running" to convey liveness.
 */

const STATUS_STYLES: Record<TaskStatus, { bg: string; text: string; dot?: string }> = {
  queued: { bg: "bg-muted/60", text: "text-muted-foreground" },
  running: { bg: "bg-ocean-500/20", text: "text-ocean-300", dot: "bg-ocean-500" },
  awaiting_user: { bg: "bg-alert-warning/15", text: "text-alert-warning", dot: "bg-alert-warning" },
  completed: { bg: "bg-alert-success/15", text: "text-alert-success" },
  failed: { bg: "bg-destructive/15", text: "text-destructive" },
  cancelled: { bg: "bg-muted/40", text: "text-muted-foreground/70" },
  paused: { bg: "bg-severity-low/15", text: "text-severity-low" },
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  queued: "排队中",
  running: "运行中",
  awaiting_user: "等待确认",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  paused: "暂停",
};

export interface TaskStatusBadgeProps {
  status: TaskStatus;
  className?: string;
}

export function TaskStatusBadge({ status, className }: TaskStatusBadgeProps) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold",
        s.bg,
        s.text,
        className,
      )}
    >
      {s.dot && (
        <span className="relative flex h-2 w-2">
          <span
            className={cn(
              "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75",
              s.dot,
            )}
          />
          <span
            className={cn("relative inline-flex h-2 w-2 rounded-full", s.dot)}
          />
        </span>
      )}
      {STATUS_LABEL[status]}
    </span>
  );
}
