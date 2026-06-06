import { useState } from "react";
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
export function AgentEventCard({ payload, agentName, animClass }: AgentEventCardProps) {
  const [open, setOpen] = useState(false);
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
    case "subagent_spawned":
      return (
        <div
          className={cn(
            "flex gap-2 rounded-lg border border-border/30 bg-muted/25 px-3 py-2.5 border-l-[3px] border-l-primary/50",
            animClass,
          )}
        >
          <Bot className="h-4 w-4 shrink-0 text-primary mt-0.5" aria-hidden />
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{lifecycleAgentName}</span>
            <span className="ml-1 text-primary/80">已启动</span>
            {payload.task_description ? (
              <p className="mt-1 line-clamp-2 text-xs leading-relaxed">{payload.task_description}</p>
            ) : null}
          </div>
        </div>
      );
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
    case "subagent_done":
      return (
        <div
          className={cn(
            "flex gap-2 rounded-lg border px-3 py-2.5 border-l-[3px]",
            animClass,
            payload.status === "ok"
              ? "border-alert-success/20 bg-alert-success/5 border-l-alert-success/60"
              : "border-destructive/20 bg-destructive/5 border-l-destructive/60",
          )}
        >
          <Bot
            className={cn(
              "h-4 w-4 shrink-0",
              payload.status === "ok" ? "text-alert-success" : "text-destructive",
            )}
            aria-hidden
          />
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{lifecycleAgentName}</span>
            <span
              className={cn(
                "ml-1",
                payload.status === "ok" ? "text-alert-success" : "text-destructive",
              )}
            >
              {payload.status === "ok" ? "已完成" : "失败"}
            </span>
            {payload.result ? (
              <p className="mt-0.5 line-clamp-3 text-xs">{payload.result}</p>
            ) : null}
          </div>
        </div>
      );
    case "tool_call":
      if (isHiddenFrontendToolName(payload.tool_name)) return null;
      return <ToolCallCard payload={payload} animClass={animClass} />;
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
