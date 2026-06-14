import { useEffect, useState } from "react";
import { Bot, ChevronRight, ClipboardList, Lightbulb, ListChecks } from "lucide-react";

import { resolveAgent } from "@/components/AgentAvatar";
import { ToolCallCard } from "@/components/message/ToolCallCard";
import { isHiddenFrontendToolName } from "@/lib/tool-visibility";
import { cn } from "@/lib/utils";
import type { AgentEventPayload } from "@/lib/types";

interface AgentEventCardProps {
  payload: AgentEventPayload;
  agentName?: string;
  animClass?: string;
  /** When true, collapsible sections start expanded (e.g. category filter active). */
  defaultExpanded?: boolean;
}

/** @description Determine whether an agent event should be visible in the UI. */
export function isVisibleAgentEvent(payload: AgentEventPayload): boolean {
  switch (payload.type) {
    case "thought":
    case "orchestrator_plan":
    case "subagent_spawned":
    case "subagent_done":
    case "blackboard_entry":
      return true;
    case "tool_call":
      return !isHiddenFrontendToolName(payload.tool_name);
    case "agent_status":
    case "asset_pushed":
    case "high_risk_confirm":
    case "subagent_status":
    default:
      return false;
  }
}

function agentEventDisplayName(payload: AgentEventPayload, fallbackAgentName?: string): string {
  return resolveAgent(
    payload.agent_name ?? payload.agent ?? fallbackAgentName ?? payload.task_id ?? "subagent",
  ).label;
}

/** @description Renders agent lifecycle events (thought, subagent, plan, etc.). */
export function AgentEventCard({ payload, agentName, animClass, defaultExpanded = false }: AgentEventCardProps) {
  const [open, setOpen] = useState(defaultExpanded);
  useEffect(() => { if (defaultExpanded) setOpen(true); }, [defaultExpanded]);
  const lifecycleAgentName = agentEventDisplayName(payload, agentName);

  switch (payload.type) {
    case "thought": {
      const lines = payload.content?.split("\n") ?? [];
      return (
        <div className={cn("w-full", animClass)}>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "group flex w-full items-center gap-2 rounded-lg px-2 py-1.5",
              "text-xs text-muted-foreground transition-all duration-150 hover:bg-primary/6",
            )}
            aria-expanded={open}
          >
            <Lightbulb className="h-3.5 w-3.5 text-alert-warning" aria-hidden />
            <span className="font-medium">{lines[0] ?? "思考中..."}</span>
            <ChevronRight
              aria-hidden
              className={cn(
                "ml-auto h-3.5 w-3.5 transition-transform duration-200",
                open && "rotate-90",
              )}
            />
          </button>
          {open && (
            <ul
              className={cn(
                "mt-1 space-y-0.5 border-l-2 border-alert-warning/25 pl-3",
                "animate-in fade-in-0 slide-in-from-top-1 duration-200",
              )}
            >
              {lines.map((line, i) => (
                <li
                  key={`trace-${i}-${line.slice(0, 20)}`}
                  className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-muted-foreground/90"
                >
                  {line}
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case "subagent_spawned": {
      const hasDetail = Boolean(payload.task_description || payload.task_id);
      return (
        <div
          className={cn(
            "rounded-lg border border-border/30 bg-muted/25 border-l-[3px] border-l-primary/50",
            animClass,
          )}
        >
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "group flex w-full items-center gap-2 px-3 py-2.5",
              "text-xs transition-all duration-150 hover:bg-primary/6",
              hasDetail && "cursor-pointer",
            )}
            aria-expanded={open}
          >
            <Bot className="h-4 w-4 shrink-0 text-primary" aria-hidden />
            <span className="font-medium text-foreground">{lifecycleAgentName}</span>
            <span className="text-primary/80">已启动</span>
            {hasDetail && (
              <ChevronRight
                aria-hidden
                className={cn(
                  "ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200",
                  open && "rotate-90",
                )}
              />
            )}
          </button>
          {open && hasDetail && (
            <div
              className={cn(
                "border-t border-border/20 px-3 py-2 space-y-1",
                "animate-in fade-in-0 slide-in-from-top-1 duration-200",
              )}
            >
              {payload.task_description ? (
                <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
                  {payload.task_description}
                </p>
              ) : null}
              {payload.task_id ? (
                <p className="font-mono text-xs text-muted-foreground/60">
                  Task ID: {payload.task_id}
                </p>
              ) : null}
            </div>
          )}
        </div>
      );
    }
    case "orchestrator_plan":
      return (
        <div
          className={cn(
            "flex gap-2 rounded-lg border border-primary/25 bg-primary/5 px-3 py-2",
            animClass,
          )}
        >
          <ListChecks className="h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">编排计划</span>
            <ol className="mt-1 space-y-1">
              {(payload.steps ?? []).map((step, index) => (
                <li
                  key={`${step.title}-${index}`}
                  className="grid grid-cols-[1.25rem_1fr] gap-1"
                >
                  <span className="font-medium text-primary">{index + 1}.</span>
                  <span className="min-w-0">
                    <span className="block break-words font-medium text-foreground">
                      {step.title}
                    </span>
                    {step.detail ? (
                      <span className="mt-0.5 block break-words text-xs leading-5">
                        {step.detail}
                      </span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      );
    case "subagent_status":
      // 子智能体中间状态（工具调用过程）不在前端展示
      return null;
    case "subagent_done": {
      const doneOk = payload.status === "ok";
      const doneIncomplete = payload.status === "incomplete" || payload.status === "interrupted";
      const hasResult = Boolean(payload.result);
      const doneToneClass = doneOk
        ? "border-alert-success/20 bg-alert-success/5 border-l-alert-success/60"
        : doneIncomplete
          ? "border-alert-warning/20 bg-alert-warning/5 border-l-alert-warning/60"
          : "border-destructive/20 bg-destructive/5 border-l-destructive/60";
      const doneIconClass = doneOk
        ? "text-alert-success"
        : doneIncomplete
          ? "text-alert-warning"
          : "text-destructive";
      const doneLabel = doneOk ? "已完成" : doneIncomplete ? "未完成" : "失败";
      return (
        <div
          className={cn(
            "rounded-lg border border-l-[3px]",
            animClass,
            doneToneClass,
          )}
        >
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "group flex w-full items-center gap-2 px-3 py-2.5",
              "text-xs transition-all duration-150 hover:bg-primary/6",
              hasResult && "cursor-pointer",
            )}
            aria-expanded={open}
          >
            <Bot
              className={cn(
                "h-4 w-4 shrink-0",
                doneIconClass,
              )}
              aria-hidden
            />
            <span className="font-medium text-foreground">{lifecycleAgentName}</span>
            <span className={cn(doneIconClass)}>{doneLabel}</span>
            {hasResult && (
              <ChevronRight
                aria-hidden
                className={cn(
                  "ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200",
                  open && "rotate-90",
                )}
              />
            )}
          </button>
          {open && hasResult && (
            <div
              className={cn(
                "border-t border-border/20 px-3 py-2",
                "animate-in fade-in-0 slide-in-from-top-1 duration-200",
              )}
            >
              <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
                {payload.result}
              </p>
            </div>
          )}
        </div>
      );
    }
    case "tool_call":
      if (isHiddenFrontendToolName(payload.tool_name)) return null;
      return <ToolCallCard payload={payload} animClass={animClass} defaultExpanded={defaultExpanded} />;
    case "blackboard_entry":
      return (
        <div
          className={cn(
            "flex gap-2 rounded-lg border border-border/40 bg-muted/30 px-3 py-2",
            animClass,
          )}
        >
          <ClipboardList className="h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">[{payload.agent_name}]</span>
            <p className="mt-0.5 whitespace-pre-wrap break-words text-xs">{payload.text}</p>
          </div>
        </div>
      );
    default:
      return null;
  }
}
