import { useTranslation } from "react-i18next";
import { Link, NavLink, useLocation } from "react-router-dom";
import { LayoutDashboard, ListChecks, Settings as SettingsIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Sticky top navigation shared by secondary pages (Dashboard / TaskDetail /
 * Settings). The chat HomePage continues to use ThreadShell's own header so
 * the conversation surface keeps its tight, app-like chrome.
 *
 * Layout follows UI/UI-UX建设模版.md §6.1: sticky h-16 + backdrop-blur, with
 * a Shield-style logo tile on the left and a route menu + settings entry on
 * the right. Brand text logo uses the asset committed in PR1.
 */

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

export interface NavbarProps {
  /** Optional page-specific title/badge slotted next to the brand. */
  title?: React.ReactNode;
  /** Optional trailing slot (e.g. action buttons) rendered before the settings entry. */
  trailing?: React.ReactNode;
  /** Hide the route menu (used on minimal pages such as TaskDetail headers). */
  hideRouteMenu?: boolean;
}

export function Navbar({ title, trailing, hideRouteMenu = false }: NavbarProps) {
  const { t } = useTranslation();
  const location = useLocation();

  const items: NavItem[] = [
    { to: "/", label: t("nav.home", { defaultValue: "对话" }), icon: ListChecks },
    {
      to: "/dashboard",
      label: t("nav.dashboard", { defaultValue: "大屏" }),
      icon: LayoutDashboard,
    },
  ];

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/50 bg-background/80 backdrop-blur-md">
      <div className="container flex h-16 items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <img
                src="/brand/logo.png"
                alt=""
                aria-hidden
                className="h-5 w-5 object-contain"
                draggable={false}
              />
            </span>
            <picture className="hidden md:block">
              <img
                src="/brand/text-logo.png"
                alt={t("app.brand", { defaultValue: "海盾智能体管控台" })}
                className="h-5 w-auto select-none object-contain opacity-95"
                draggable={false}
              />
            </picture>
          </Link>
          {title ? (
            <div className="ml-2 flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
              <span className="text-border/70">/</span>
              <div className="truncate text-foreground">{title}</div>
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          {!hideRouteMenu && (
            <nav className="hidden items-center gap-1 md:flex">
              {items.map((item) => {
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
                      "inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm transition-colors",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {item.label}
                  </NavLink>
                );
              })}
            </nav>
          )}
          {trailing}
          <Link to="/settings" aria-label={t("nav.settings", { defaultValue: "设置" })}>
            <Button variant="ghost" size="icon" className="h-9 w-9">
              <SettingsIcon className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </div>
    </header>
  );
}

export default Navbar;
