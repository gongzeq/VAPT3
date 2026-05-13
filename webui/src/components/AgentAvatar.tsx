import {
  type LucideIcon,
  Sparkles,
  Globe,
  ScanLine,
  ShieldAlert,
  Lock,
  FileText,
  Bot,
} from "lucide-react";

import { cn } from "@/lib/utils";

export interface AgentInfo {
  /** Registry key (snake_case). */
  key: string;
  /** Human-readable label. */
  label: string;
  /** Two-letter abbreviation for the avatar badge. */
  abbr: string;
  /** "orchestrator" | "subagent" — drives the meta tag. */
  type: "orchestrator" | "subagent";
  /** CSS gradient string for the avatar background. */
  gradient: string;
  /** Icon component to render inside the avatar. */
  Icon: LucideIcon;
  /** Accent colour (HSL string) used for borders / tags. */
  accent: string;
}

const AGENT_REGISTRY: Record<string, AgentInfo> = {
  orchestrator: {
    key: "orchestrator",
    label: "Orchestrator",
    abbr: "OR",
    type: "orchestrator",
    gradient: "linear-gradient(135deg, hsl(210 100% 56%), hsl(195 100% 60%))",
    Icon: Sparkles,
    accent: "hsl(210 100% 56%)",
  },
  asset_discovery: {
    key: "asset_discovery",
    label: "Asset Discovery",
    abbr: "AD",
    type: "subagent",
    gradient: "linear-gradient(135deg, hsl(152 70% 45%), hsl(152 60% 30%))",
    Icon: Globe,
    accent: "hsl(152 70% 45%)",
  },
  port_scan: {
    key: "port_scan",
    label: "Port Scan",
    abbr: "PS",
    type: "subagent",
    gradient: "linear-gradient(135deg, hsl(260 70% 62%), hsl(260 60% 40%))",
    Icon: ScanLine,
    accent: "hsl(260 70% 62%)",
  },
  vuln_scan: {
    key: "vuln_scan",
    label: "Vuln Scan",
    abbr: "VS",
    type: "subagent",
    gradient: "linear-gradient(135deg, hsl(22 100% 62%), hsl(22 90% 42%))",
    Icon: ShieldAlert,
    accent: "hsl(22 100% 62%)",
  },
  weak_password: {
    key: "weak_password",
    label: "Weak Password",
    abbr: "WP",
    type: "subagent",
    gradient: "linear-gradient(135deg, hsl(48 96% 53%), hsl(35 90% 40%))",
    Icon: Lock,
    accent: "hsl(48 96% 53%)",
  },
  report: {
    key: "report",
    label: "Report",
    abbr: "RP",
    type: "subagent",
    gradient: "linear-gradient(135deg, hsl(203 100% 62%), hsl(210 92% 38%))",
    Icon: FileText,
    accent: "hsl(203 100% 62%)",
  },
};

/** Resolve an agent key (snake_case) to its display metadata. Falls back to
 * a generic subagent stub when the key is unknown. */
export function resolveAgent(agentName?: string): AgentInfo {
  if (!agentName) return AGENT_REGISTRY.orchestrator;
  const key = agentName.toLowerCase().trim();
  if (AGENT_REGISTRY[key]) return AGENT_REGISTRY[key];
  // Heuristic: if the key contains "orchestrator", treat as orchestrator.
  if (key.includes("orchestrator")) return AGENT_REGISTRY.orchestrator;
  // Generic fallback — mint a stub so the UI never crashes.
  return {
    key,
    label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    abbr: key.slice(0, 2).toUpperCase(),
    type: "subagent",
    gradient: AGENT_REGISTRY.orchestrator.gradient,
    Icon: Bot,
    accent: AGENT_REGISTRY.orchestrator.accent,
  };
}

interface AgentAvatarProps {
  agentName?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/** Compact avatar badge for an agent. Renders a coloured square with an icon
 * or abbreviation, following the multi-agent prototype colour scheme. */
export function AgentAvatar({ agentName, size = "md", className }: AgentAvatarProps) {
  const info = resolveAgent(agentName);
  const sizeClasses = {
    sm: "h-7 w-7 rounded-[7px] text-[11px]",
    md: "h-8 w-8 rounded-lg text-xs",
    lg: "h-9 w-9 rounded-[9px] text-sm",
  };
  const iconSizes = {
    sm: "h-3.5 w-3.5",
    md: "h-4 w-4",
    lg: "h-[18px] w-[18px]",
  };

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center font-bold text-white shadow-sm",
        sizeClasses[size],
        className,
      )}
      style={{ background: info.gradient }}
      title={`${info.label} · ${info.type === "orchestrator" ? "主编排" : "子智能体"}`}
    >
      <info.Icon className={cn(iconSizes[size])} aria-hidden />
    </div>
  );
}

/** Meta label line rendered above a message bubble. Shows the agent name
 * plus an orchestrator / subagent chip. */
export function AgentMeta({ agentName, timestamp }: { agentName?: string; timestamp?: string }) {
  const info = resolveAgent(agentName);
  const typeLabel = info.type === "orchestrator" ? "主编排" : "subagent";
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span className="font-semibold text-foreground" style={{ color: info.accent }}>
        {info.label}
      </span>
      <span className="opacity-50">·</span>
      <span>{typeLabel}</span>
      {timestamp ? (
        <>
          <span className="opacity-50">·</span>
          <span>{timestamp}</span>
        </>
      ) : null}
    </div>
  );
}
