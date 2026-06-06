import { Bot } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAgents } from "@/hooks/useAgents";
import { cn } from "@/lib/utils";
import type { AgentRegistryRow, AgentRuntimeStatus } from "@/lib/types";

/** Status chip class map.  Tokens come from ``--status-*`` aliases declared
 * in ``globals.css`` (component-patterns.md §1: no raw hex). */
const STATUS_STYLE: Record<
  AgentRuntimeStatus,
  { dot: string; label: string; text: string }
> = {
  running: { dot: "bg-status-run", label: "运行中", text: "text-status-run" },
  queued: { dot: "bg-status-wait", label: "排队", text: "text-status-wait" },
  idle: { dot: "bg-status-idle", label: "空闲", text: "text-status-idle" },
  offline: { dot: "bg-status-off", label: "离线", text: "text-status-off" },
  completed: { dot: "bg-alert-success", label: "已完成", text: "text-alert-success" },
  error: { dot: "bg-destructive", label: "失败", text: "text-destructive" },
};

function AgentRow({ agent }: { agent: AgentRegistryRow }) {
  const { t } = useTranslation();
  const status: AgentRuntimeStatus = agent.status ?? "offline";
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.offline;
  const display = agent.display_name || agent.name;
  const i18nLabel = t(`sidebar.agents.status.${status}`, {
    defaultValue: style.label,
  });
  return (
    <li className="flex items-center justify-between gap-2 rounded-md bg-muted/30 px-2 py-1.5">
      <span className="flex min-w-0 items-center gap-2 text-foreground">
        <Bot className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate text-xs">{display}</span>
      </span>
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px]",
          status === "running" && "animate-pulse",
        )}
        title={i18nLabel}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
        <span className={cn("font-mono", style.text)}>{i18nLabel}</span>
      </span>
    </li>
  );
}

export interface AgentStatusPanelProps {
  /** Active chat id used to scope WS ``agent_status`` updates. */
  chatId?: string | null;
  className?: string;
}

/**
 * Expert-agent status panel — moved from Sidebar into the RightRail
 * (工作台) so it lives alongside the Blackboard / Assets / Prompts tabs.
 */
export function AgentStatusPanel({ chatId, className }: AgentStatusPanelProps) {
  const { t } = useTranslation();
  const { agents } = useAgents({ chatId: chatId ?? null });

  if (agents.length === 0) {
    return (
      <div className={cn("flex flex-1 items-center justify-center text-xs text-muted-foreground", className)}>
        {t("agents.empty", { defaultValue: "暂无注册的专家智能体" })}
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center justify-between text-xs uppercase tracking-wider text-muted-foreground">
        <span>
          {t("sidebar.agents.title", {
            defaultValue: "专家智能体 ({{count}})",
            count: agents.length,
          })}
        </span>
      </div>
      <ul className="flex-1 space-y-1 overflow-y-auto scroll-hide">
        {agents.map((agent) => (
          <AgentRow key={agent.name} agent={agent} />
        ))}
      </ul>
    </div>
  );
}

export default AgentStatusPanel;
