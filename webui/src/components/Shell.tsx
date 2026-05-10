import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelLeftOpen, PanelRightOpen } from "lucide-react";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Sidebar } from "@/components/Sidebar";
import { SettingsView } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useSessions } from "@/hooks/useSessions";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

const SIDEBAR_STORAGE_KEY = "secbot-webui.sidebar";
const RIGHT_RAIL_STORAGE_KEY = "secbot-webui.right-rail";
const SIDEBAR_WIDTH = 272;
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
  }) => React.ReactNode;
}

function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
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
 * Chat + sidebar shell. Extracted from App.tsx in PR3 so HomePage can mount
 * it under the new router. The internal `view` toggle (chat ↔ settings) is
 * preserved for the legacy code path; when `onOpenSettingsExternal` is
 * provided, settings interactions are delegated to the caller and the
 * internal toggle is short-circuited.
 */
export function Shell({
  onModelNameChange,
  onLogout,
  onOpenSettingsExternal,
  rightRail,
}: ShellProps) {
  const { t, i18n } = useTranslation();
  const { sessions, loading, refresh, createChat, deleteChat } = useSessions();
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [view, setView] = useState<ShellView>("chat");
  const [desktopSidebarOpen, setDesktopSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [rightRailOpen, setRightRailOpen] = useState<boolean>(readRightRailOpen);
  const [pendingDelete, setPendingDelete] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const lastSessionsLen = useRef(0);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        desktopSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }, [desktopSidebarOpen]);

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

  useEffect(() => {
    if (activeKey) return;
    if (sessions.length > 0 && lastSessionsLen.current === 0) {
      setActiveKey(sessions[0].key);
    }
    lastSessionsLen.current = sessions.length;
  }, [sessions, activeKey]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);

  const closeDesktopSidebar = useCallback(() => {
    setDesktopSidebarOpen(false);
  }, []);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isDesktop =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isDesktop) {
      setDesktopSidebarOpen((v) => !v);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, []);

  const onCreateChat = useCallback(async () => {
    try {
      const chatId = await createChat();
      setActiveKey(`websocket:${chatId}`);
      setView("chat");
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      return null;
    }
  }, [createChat]);

  const onNewChat = useCallback(() => {
    setActiveKey(null);
    setView("chat");
    setMobileSidebarOpen(false);
  }, []);

  const onSelectChat = useCallback((key: string) => {
    setActiveKey(key);
    setView("chat");
    setMobileSidebarOpen(false);
  }, []);

  const onOpenSettings = useCallback(() => {
    if (onOpenSettingsExternal) {
      onOpenSettingsExternal();
      setMobileSidebarOpen(false);
      return;
    }
    setView("settings");
    setMobileSidebarOpen(false);
  }, [onOpenSettingsExternal]);

  const onTurnEnd = useCallback(() => {
    void refresh();
  }, [refresh]);

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ??
          sessions[currentIndex - 1]?.key ??
          null)
      : activeKey;
    setPendingDelete(null);
    if (deletingActive) setActiveKey(fallbackKey);
    try {
      await deleteChat(key);
    } catch (e) {
      if (deletingActive) setActiveKey(key);
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, sessions]);

  const headerTitle = activeSession
    ? activeSession.title ||
      activeSession.preview ||
      t("chat.fallbackTitle", { id: activeSession.chatId.slice(0, 6) })
    : t("app.brand");

  useEffect(() => {
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, t]);

  const sidebarProps = {
    sessions,
    activeKey,
    loading,
    onNewChat,
    onSelect: onSelectChat,
    onRequestDelete: (key: string, label: string) =>
      setPendingDelete({ key, label }),
  };

  return (
    <div className="relative flex h-full w-full gap-6 overflow-hidden p-6">
      {/* Desktop Sidebar */}
      <aside
        className={cn(
          "relative z-20 hidden shrink-0 overflow-hidden rounded-2xl border border-border gradient-card lg:block",
          "transition-[width] duration-300 ease-out",
        )}
        style={{ width: desktopSidebarOpen ? SIDEBAR_WIDTH : 0 }}
      >
        <div
          className={cn(
            "absolute inset-y-0 left-0 h-full overflow-hidden",
            "transition-transform duration-300 ease-out",
            desktopSidebarOpen ? "translate-x-0" : "-translate-x-full",
          )}
          style={{ width: SIDEBAR_WIDTH }}
        >
          <Sidebar {...sidebarProps} onCollapse={closeDesktopSidebar} />
        </div>
      </aside>

      <Sheet
        open={mobileSidebarOpen}
        onOpenChange={(open) => setMobileSidebarOpen(open)}
      >
        <SheetContent
          side="left"
          showCloseButton={false}
          className="p-0 lg:hidden"
          style={{ width: SIDEBAR_WIDTH, maxWidth: SIDEBAR_WIDTH }}
        >
          <Sidebar {...sidebarProps} onCollapse={closeMobileSidebar} />
        </SheetContent>
      </Sheet>

      {/* Main chat area */}
      <main className="relative flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border gradient-card">
        <ErrorBoundary>
          {view === "settings" ? (
            <SettingsView
              onBackToChat={() => setView("chat")}
              onModelNameChange={onModelNameChange}
              onLogout={onLogout}
            />
          ) : rightRail ? (
            <div className="flex h-full min-h-0 flex-1">
              <div className="flex h-full min-w-0 flex-1 flex-col">
                <ThreadShell
                  session={activeSession}
                  title={headerTitle}
                  onToggleSidebar={toggleSidebar}
                  onNewChat={onNewChat}
                  onCreateChat={onCreateChat}
                  onTurnEnd={onTurnEnd}
                  onOpenSettings={onOpenSettings}
                  hideSidebarToggleOnDesktop={desktopSidebarOpen}
                  onToggleRightRail={() => setRightRailOpen((v) => !v)}
                  rightRailOpen={rightRailOpen}
                />
              </div>
            </div>
          ) : (
            <ThreadShell
              session={activeSession}
              title={headerTitle}
              onToggleSidebar={toggleSidebar}
              onNewChat={onNewChat}
              onCreateChat={onCreateChat}
              onTurnEnd={onTurnEnd}
              onOpenSettings={onOpenSettings}
              hideSidebarToggleOnDesktop={desktopSidebarOpen}
            />
          )}
        </ErrorBoundary>

        {/* Expand sidebar floating button (visible only when collapsed) */}
        {!desktopSidebarOpen && (
          <button
            type="button"
            onClick={() => setDesktopSidebarOpen(true)}
            className={cn(
              "absolute left-3 top-3 z-20 hidden h-9 w-9 items-center justify-center",
              "rounded-full border border-border bg-background/80 text-muted-foreground shadow-sm backdrop-blur-sm",
              "transition-colors hover:bg-accent/40 hover:text-foreground",
              "lg:flex",
            )}
            aria-label={t("thread.header.toggleSidebar", { defaultValue: "展开对话栏" })}
            title={t("thread.header.toggleSidebar", { defaultValue: "展开对话栏" })}
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}

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
              onToggleSidebar: toggleSidebar,
              onToggleRightRail: () => setRightRailOpen((v) => !v),
            })}
          </div>
        </aside>
      )}

      <DeleteConfirm
        open={!!pendingDelete}
        title={pendingDelete?.label ?? ""}
        onCancel={() => setPendingDelete(null)}
        onConfirm={onConfirmDelete}
      />
    </div>
  );
}

export default Shell;
