import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Bell,
  LayoutDashboard,
  ListChecks,
  Menu,
  MessageSquare,
  Settings,
} from "lucide-react";

import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import type { ConnectionStatus } from "@/lib/types";

const NAV_ITEMS = [
  { to: "/", label: "智能助手", icon: MessageSquare },
  { to: "/dashboard", label: "大屏分析", icon: LayoutDashboard },
  { to: "/tasks", label: "任务详情", icon: ListChecks },
  { to: "/settings", label: "设置", icon: Settings },
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
  const { client } = useClient();
  const location = useLocation();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);

  useEffect(() => client.onStatus(setStatus), [client]);

  const isOpen = status === "open";
  const statusLabel = isOpen
    ? "WS · 已连接"
    : t(`connection.${status}`, { defaultValue: status });

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
            className="h-9 w-9 rounded-lg ring-1 ring-primary/30"
            draggable={false}
          />
          <img
            src="/brand/text-logo.png"
            alt="海盾"
            className="hidden h-7 md:block"
            draggable={false}
          />
        </div>

        {/* Nav links */}
        <nav className="ml-4 hidden items-center gap-1 md:flex">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active =
              item.to === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(item.to);
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "gradient-primary font-medium text-white shadow-md"
                    : "text-muted-foreground hover:bg-white/5 hover:text-white",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Right section */}
        <div className="hidden items-center gap-2 md:flex">
          {/* WS status */}
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 text-xs">
            <span
              className={cn(
                "h-2 w-2 rounded-full animate-pulse",
                isOpen ? "bg-emerald-500" : "bg-muted-foreground",
              )}
            />
            <span className="font-mono text-muted-foreground">
              {statusLabel}
            </span>
          </div>

          {/* Bell */}
          <button
            type="button"
            className="rounded-lg border border-border bg-muted/40 p-2 transition hover:border-primary/40"
            aria-label={t("nav.notifications", { defaultValue: "通知" })}
          >
            <Bell className="h-4 w-4 text-muted-foreground" />
          </button>


        </div>
      </div>
    </header>
  );
}

export default Navbar;
