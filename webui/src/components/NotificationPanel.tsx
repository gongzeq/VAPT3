import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bell, CheckCheck, Info, Loader2, ShieldAlert } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Notification } from "@/lib/types";
import {
  NOTIFICATION_PANEL_LIMIT,
  useNotifications,
  type UseNotificationsResult,
} from "@/hooks/useNotifications";

export interface NotificationPanelProps {
  token: string | null;
  /** ``true`` while the dropdown is open — used as a trigger to refetch.
   * We refetch on every open so the list is fresh even if the 30s badge
   * poll hasn't rolled around yet. */
  open: boolean;
  /** Called when the user clicks a notification or mark-all — the caller
   * closes the dropdown. */
  onClose?: () => void;
  onDecrementUnread?: (by: number) => void;
  onResetUnread?: () => void;
  /** Dependency injection seam for tests. Production never overrides. */
  controller?: UseNotificationsResult;
}

/** Map ``Notification.kind`` to a decorative icon + tone. Unknown kinds
 * fall through to the neutral "info" visual so the row still renders
 * (F5: degrade-don't-crash). */
function iconFor(kind: string): {
  Icon: typeof Bell;
  tone: string;
} {
  switch (kind) {
    case "critical_vuln":
      return { Icon: ShieldAlert, tone: "text-rose-400" };
    case "scan_failed":
      return { Icon: AlertTriangle, tone: "text-amber-400" };
    case "high_risk_confirm":
      return { Icon: ShieldAlert, tone: "text-orange-400" };
    case "scan_completed":
      return { Icon: CheckCheck, tone: "text-emerald-400" };
    default:
      return { Icon: Info, tone: "text-muted-foreground" };
  }
}

export function NotificationPanel({
  token,
  open,
  onClose,
  onDecrementUnread,
  onResetUnread,
  controller,
}: NotificationPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const internal = useNotifications(token, {
    onDecrement: onDecrementUnread,
    onReset: onResetUnread,
    // When a controller is injected, disable auto-fetch: the harness
    // is in charge of shape and lifecycle.
    autoFetch: controller === undefined,
  });
  const { items, state, errorCode, refresh, markRead, markAllRead } =
    controller ?? internal;

  // Refetch every time the panel opens so we don't show a stale list
  // between badge-poll cycles. We intentionally do NOT refetch on close.
  const prevOpenRef = useRef(open);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      void refresh();
    }
    prevOpenRef.current = open;
  }, [open, refresh]);

  const unreadCount = items.reduce((n, item) => (item.read ? n : n + 1), 0);

  async function handleClick(row: Notification) {
    // Fire-and-forget: optimistic UI flips immediately; the server sync
    // runs in the background.
    void markRead(row.id);
    if (row.link) {
      navigate(row.link);
    }
    onClose?.();
  }

  async function handleMarkAll() {
    await markAllRead();
  }

  return (
    <div
      className="flex w-[360px] max-w-[calc(100vw-1rem)] flex-col overflow-hidden"
      data-testid="notification-panel"
    >
      <div className="flex items-center justify-between border-b border-border/50 px-4 py-3">
        <div className="text-sm font-semibold">
          {t("notifications.title", { defaultValue: "通知" })}
        </div>
        <button
          type="button"
          onClick={handleMarkAll}
          disabled={unreadCount === 0}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors",
            unreadCount === 0
              ? "cursor-not-allowed text-muted-foreground/60"
              : "text-primary hover:bg-primary/10",
          )}
          data-testid="notification-mark-all"
        >
          <CheckCheck className="h-3.5 w-3.5" />
          {t("notifications.markAllRead", { defaultValue: "全部标记已读" })}
        </button>
      </div>

      {state === "loading" && items.length === 0 && (
        <div className="flex items-center justify-center px-4 py-10 text-xs text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {t("notifications.loading", { defaultValue: "加载中…" })}
        </div>
      )}

      {state === "error" && (
        <div className="flex flex-col items-center justify-center gap-2 px-4 py-8 text-xs text-muted-foreground">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <span>
            {t(`notifications.error.${errorCode ?? "network"}`, {
              defaultValue: t("notifications.error.network", {
                defaultValue: "加载失败",
              }),
            })}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-md border border-border px-2 py-1 text-xs text-primary hover:bg-primary/10"
          >
            {t("notifications.retry", { defaultValue: "重试" })}
          </button>
        </div>
      )}

      {state !== "error" && items.length === 0 && state !== "loading" && (
        <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-xs text-muted-foreground">
          <Bell className="h-5 w-5 opacity-60" />
          <span>{t("notifications.empty", { defaultValue: "暂无通知" })}</span>
        </div>
      )}

      {items.length > 0 && (
        <ScrollArea className="max-h-[360px]">
          <ul className="divide-y divide-border/40">
            {items.slice(0, NOTIFICATION_PANEL_LIMIT).map((row) => {
              const { Icon, tone } = iconFor(row.kind);
              return (
                <li key={row.id}>
                  <button
                    type="button"
                    onClick={() => void handleClick(row)}
                    className={cn(
                      "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-white/5",
                      !row.read && "bg-primary/5",
                    )}
                    data-testid="notification-item"
                    data-read={row.read ? "true" : "false"}
                  >
                    <Icon className={cn("mt-0.5 h-4 w-4 flex-shrink-0", tone)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "truncate text-sm",
                            row.read ? "text-muted-foreground" : "font-semibold text-foreground",
                          )}
                        >
                          {row.title}
                        </span>
                        {!row.read && (
                          <span
                            className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary"
                            aria-hidden
                          />
                        )}
                      </div>
                      {row.body && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                          {row.body}
                        </p>
                      )}
                      <div className="mt-1 text-[11px] text-muted-foreground/70">
                        {relativeTime(row.created_at)}
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </ScrollArea>
      )}
    </div>
  );
}

export default NotificationPanel;
