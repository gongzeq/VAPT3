import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { PanelRightOpen } from "lucide-react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { SettingsView } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { useSessions } from "@/hooks/useSessions";
import { displaySessionTitle } from "@/lib/session-title";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

const RIGHT_RAIL_STORAGE_KEY = "secbot-webui.right-rail";
const RIGHT_RAIL_WIDTH = 320;
type ShellView = "chat" | "settings";

export interface ShellProps {
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
  /**
   * When set, intercepts the in-app "open settings" action and delegates to
   * the caller (e.g. router-mode App routes settings to a dedicated page).
   * If omitted, Shell falls back to the legacy in-place settings view.
   */
  onOpenSettingsExternal?: () => void;
  /**
   * Optional right rail rendered next to ThreadShell when view === "chat".
   * Hidden below xl: to avoid crushing the chat surface on narrow viewports;
   * the rail itself is purely presentational so dropping it on small screens
   * never breaks core chat UX. Includes a collapse toggle button.
   */
  rightRail?: (props: {
    onToggleSidebar: () => void;
    onToggleRightRail: () => void;
    /** Active chat session (null when no chat is selected). The right rail
     * uses this to scope per-chat data such as the Blackboard panel. */
    session: ChatSummary | null;
  }) => React.ReactNode;
}

function readRightRailOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(RIGHT_RAIL_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

/**
 * Two-column chat shell (main + optional right rail). The legacy left
 * Sidebar with the historical conversation list has been promoted to a
 * top-level `/sessions` page, so the chat surface here only ever shows
 * the *current* conversation.
 *
 * The active session can be deep-linked via the `?session=<key>` query
 * param so the Sessions page can hand the user back into a specific
 * thread without losing in-page context.
 */
export function Shell({
  onModelNameChange,
  onLogout,
  onOpenSettingsExternal,
  rightRail,
}: ShellProps) {
  const { t, i18n } = useTranslation();
  const { sessions, refresh, createChat } = useSessions();
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionParam = searchParams.get("session");
  const [activeKey, setActiveKey] = useState<string | null>(sessionParam);
  const [view, setView] = useState<ShellView>("chat");
  const [rightRailOpen, setRightRailOpen] = useState<boolean>(readRightRailOpen);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        RIGHT_RAIL_STORAGE_KEY,
        rightRailOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors
    }
  }, [rightRailOpen]);

  // Keep activeKey in sync with the URL query param. Allows
  // `/sessions` → `打开会话` to deep-link back to a specific thread.
  useEffect(() => {
    if (sessionParam !== activeKey) {
      setActiveKey(sessionParam);
      setView("chat");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionParam]);


  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);

  const onCreateChat = useCallback(async () => {
    try {
      const chatId = await createChat();
      const newKey = `websocket:${chatId}`;
      setActiveKey(newKey);
      setView("chat");
      // Reflect the new session in the URL so refresh / share keeps state.
      const next = new URLSearchParams(searchParams);
      next.set("session", newKey);
      setSearchParams(next, { replace: true });
      return chatId;
    } catch {
      return null;
    }
  }, [createChat, searchParams, setSearchParams]);

  const onNewChat = useCallback(() => {
    setActiveKey(null);
    setView("chat");
    if (searchParams.has("session")) {
      const next = new URLSearchParams(searchParams);
      next.delete("session");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const onOpenSettings = useCallback(() => {
    if (onOpenSettingsExternal) {
      onOpenSettingsExternal();
      return;
    }
    setView("settings");
  }, [onOpenSettingsExternal]);

  const onTurnEnd = useCallback(() => {
    void refresh();
  }, [refresh]);

  // Sidebar has been removed. Keep a stable no-op so ThreadShell's
  // `onToggleSidebar` prop remains satisfied without consumers needing a
  // refactor.
  const noopToggleSidebar = useCallback(() => {}, []);

  const headerTitle = activeSession
    ? displaySessionTitle(
        activeSession,
        t("chat.fallbackTitle", { id: activeSession.chatId.slice(0, 6) }),
      )
    : t("app.brand");

  useEffect(() => {
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, t]);

  return (
    <div className="relative flex h-full w-full gap-6 overflow-hidden p-6">
      {/* Main chat area */}
      <main className="relative flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border gradient-card">
        <ErrorBoundary>
          {view === "settings" ? (
            <SettingsView
              onBackToChat={() => setView("chat")}
              onModelNameChange={onModelNameChange}
              onLogout={onLogout}
            />
          ) : (
            <ThreadShell
              session={activeSession}
              title={headerTitle}
              onToggleSidebar={noopToggleSidebar}
              onNewChat={onNewChat}
              onCreateChat={onCreateChat}
              onTurnEnd={onTurnEnd}
              onOpenSettings={onOpenSettings}
              hideSidebarToggleOnDesktop
              onToggleRightRail={() => setRightRailOpen((v) => !v)}
              rightRailOpen={rightRailOpen}
            />
          )}
        </ErrorBoundary>

        {/* Expand right-rail floating button (visible only when collapsed) */}
        {rightRail && !rightRailOpen && view === "chat" && (
          <button
            type="button"
            onClick={() => setRightRailOpen(true)}
            className={cn(
              "absolute right-3 top-3 z-20 hidden h-9 w-9 items-center justify-center",
              "rounded-full border border-border bg-background/80 text-muted-foreground shadow-sm backdrop-blur-sm",
              "transition-colors hover:bg-accent/40 hover:text-foreground",
              "xl:flex",
            )}
            aria-label={t("thread.header.toggleRightRail", { defaultValue: "展开工作台" })}
            title={t("thread.header.toggleRightRail", { defaultValue: "展开工作台" })}
          >
            <PanelRightOpen className="h-4 w-4" />
          </button>
        )}
      </main>

      {/* Right Rail */}
      {rightRail && (
        <aside
          className={cn(
            "relative z-10 hidden shrink-0 overflow-hidden rounded-2xl border border-border gradient-card xl:block",
            "transition-[width] duration-300 ease-out",
          )}
          style={{ width: rightRailOpen ? RIGHT_RAIL_WIDTH : 0 }}
        >
          <div
            className={cn(
              "absolute inset-y-0 right-0 h-full overflow-hidden",
              "transition-transform duration-300 ease-out",
              rightRailOpen ? "translate-x-0" : "translate-x-full",
            )}
            style={{ width: RIGHT_RAIL_WIDTH }}
          >
            {rightRail?.({
              onToggleSidebar: noopToggleSidebar,
              onToggleRightRail: () => setRightRailOpen((v) => !v),
              session: activeSession,
            })}
          </div>
        </aside>
      )}
    </div>
  );
}

export default Shell;
