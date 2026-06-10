import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell, History, LayoutDashboard, Menu, MessageSquare, Settings, Workflow } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { NotificationPanel } from "@/components/NotificationPanel";
import { useClient, useUnread } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import { WORKFLOW_BUILDER_ENABLED } from "@/lib/workflow-client";
import type { ConnectionStatus } from "@/lib/types";

const NAV_ITEMS: Array<{
  to: string;
  labelKey: string;
  fallback: string;
  icon: typeof MessageSquare;
  enabled?: boolean;
}> = [
  { to: "/", labelKey: "nav.home", fallback: "智能助手", icon: MessageSquare },
  { to: "/sessions", labelKey: "nav.sessions", fallback: "历史会话", icon: History },
  { to: "/dashboard", labelKey: "nav.dashboard", fallback: "大屏分析", icon: LayoutDashboard },
  {
    to: "/workflows",
    labelKey: "nav.workflows",
    fallback: "工作流",
    icon: Workflow,
    enabled: WORKFLOW_BUILDER_ENABLED,
  },
  { to: "/settings", labelKey: "nav.settings", fallback: "设置", icon: Settings },
];

export interface NavbarProps {
  /** Kept for backward compat; no longer rendered in the new global nav. */
  title?: React.ReactNode;
  /** Kept for backward compat. */
  trailing?: React.ReactNode;
  /** Kept for backward compat. */
  hideRouteMenu?: boolean;
}

export function Navbar(_props: NavbarProps) {
  const { t } = useTranslation();
  const { client, token } = useClient();
  const unread = useUnread();
  const location = useLocation();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);
  const [panelOpen, setPanelOpen] = useState(false);

  useEffect(() => client.onStatus(setStatus), [client]);

  const isOpen = status === "open";
  const statusLabel = isOpen ? "WS · 已连接" : t(`connection.${status}`, { defaultValue: status });

  // Badge caps at ``99+`` so a runaway backend never blows the pill layout.
  const unreadDisplay = unread.unreadCount > 99 ? "99+" : String(unread.unreadCount);

  return (
    <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-6 px-6">
        {/* Mobile hamburger */}
        <button
          type="button"
          className="text-muted-foreground hover:text-primary lg:hidden"
          aria-label={t("thread.header.toggleSidebar")}
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Logo */}
        <div className="flex items-center gap-2.5">
          <img
            src="/brand/logo.png"
            alt=""
            className="h-9 w-9 rounded-lg ring-1 ring-primary/20 shadow-[0_0_12px_hsl(var(--primary)/0.25)]"
            draggable={false}
          />
        </div>

        {/* Nav links */}
        <nav className="ml-4 hidden items-center gap-1 md:flex">
          {NAV_ITEMS.filter((item) => item.enabled !== false).map((item) => {
            const Icon = item.icon;
            const active =
              item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to);
            const label = t(item.labelKey, { defaultValue: item.fallback });
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-all duration-200",
                  active
                    ? "gradient-primary font-medium text-primary-foreground shadow-[0_2px_12px_hsl(var(--primary)/0.35)]"
                    : "text-muted-foreground hover:bg-primary/8 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Right section */}
        <div className="hidden items-center gap-2 md:flex">
          {/* WS status */}
          <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-card/60 px-3 py-1.5 text-xs backdrop-blur-sm">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                isOpen
                  ? "bg-alert-success shadow-[0_0_6px_hsl(var(--alert-success)/0.6)]"
                  : "bg-muted-foreground/60",
              )}
            />
            <span className="font-mono text-muted-foreground/80">{statusLabel}</span>
          </div>

          {/* Bell + notification panel */}
          <DropdownMenu open={panelOpen} onOpenChange={setPanelOpen}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="icon-surface icon-surface-muted relative h-9 w-9 rounded-lg transition-all duration-200 hover:border-primary/30 hover:text-primary hover:shadow-[0_0_12px_hsl(var(--primary)/0.12)]"
                aria-label={t("nav.notifications", { defaultValue: "通知" })}
                data-testid="notification-bell"
              >
                <Bell className="h-4 w-4" />
                {unread.unreadCount > 0 && (
                  <span
                    className={cn(
                      "pointer-events-none absolute -right-1 -top-1 inline-flex min-w-[18px] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-destructive-foreground shadow-md",
                      unreadDisplay.length > 2 ? "h-[18px]" : "h-[18px]",
                    )}
                    data-testid="notification-badge"
                    aria-label={t("notifications.badgeAria", {
                      count: unread.unreadCount,
                      defaultValue: `${unread.unreadCount} 条未读通知`,
                    })}
                  >
                    {unreadDisplay}
                  </span>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" sideOffset={8} className="p-0">
              <NotificationPanel
                token={token}
                open={panelOpen}
                onClose={() => setPanelOpen(false)}
                onDecrementUnread={unread.decrement}
                onResetUnread={unread.reset}
              />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}

export default Navbar;
