import {
  Bot,
  LayoutDashboard,
  Menu,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ThreadHeaderProps {
  title: string;
  onToggleSidebar: () => void;
  onOpenSettings: () => void;
  hideSidebarToggleOnDesktop?: boolean;
  minimal?: boolean;
  onToggleRightRail?: () => void;
  rightRailOpen?: boolean;
  onOpenDashboard?: () => void;
}

export function ThreadHeader({
  title,
  onToggleSidebar,
  hideSidebarToggleOnDesktop = false,
  minimal = false,
  onToggleRightRail,
  rightRailOpen = true,
  onOpenDashboard,
}: ThreadHeaderProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const handleDashboard = onOpenDashboard ?? (() => navigate("/dashboard"));

  if (minimal) {
    return (
      <div className="relative z-10 flex h-11 items-center justify-between gap-3 border-b border-border px-3 py-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          onClick={onToggleSidebar}
          className={cn(
            "h-7 w-7 rounded-md text-muted-foreground hover:bg-accent/35 hover:text-foreground",
            hideSidebarToggleOnDesktop && "lg:pointer-events-none lg:opacity-0",
          )}
        >
          <Menu className="h-3.5 w-3.5" />
        </Button>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("nav.dashboard", { defaultValue: "大屏" })}
            onClick={handleDashboard}
            className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
          >
            <LayoutDashboard className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative z-10 flex items-center justify-between gap-3 border-b border-border px-6 py-4">
      {/* Left: bot avatar + title */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl gradient-primary animate-pulse-glow">
          <Bot className="h-5 w-5 text-white" />
        </div>
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="text-xs text-muted-foreground">
            orchestrator · 4 个专家智能体在线
          </p>
        </div>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-0.5 text-xs text-emerald-500">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          Streaming
        </span>
        {onToggleRightRail && (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Toggle right panel"
            onClick={onToggleRightRail}
            className="hidden h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground xl:inline-flex"
          >
            {rightRailOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
