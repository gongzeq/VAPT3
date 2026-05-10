import { useMemo, useState } from "react";
import { Archive, PanelLeftClose, Plus, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ChatList } from "@/components/ChatList";

import type { ChatSummary } from "@/lib/types";

interface SidebarProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  onNewChat: () => void;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onCollapse: () => void;
}

export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredSessions = useMemo(() => {
    if (!normalizedQuery) return props.sessions;
    return props.sessions.filter((session) => {
      const haystack = [
        session.preview,
        session.chatId,
        session.channel,
        session.key,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [normalizedQuery, props.sessions]);

  return (
    <nav
      aria-label={t("sidebar.navigation")}
      className="flex h-full w-full flex-col text-foreground"
    >
      {/* Header: title + collapse */}
      <div className="flex items-center justify-between px-4 pt-4">
        <span className="text-xs font-medium text-muted-foreground">
          {t("sidebar.title", { defaultValue: "会话" })}
        </span>
        <button
          type="button"
          onClick={props.onCollapse}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
          aria-label={t("sidebar.collapse", { defaultValue: "收起侧边栏" })}
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* 新建会话 */}
      <div className="px-4 pt-3">
        <button
          type="button"
          onClick={props.onNewChat}
          className="hover-lift inline-flex w-full items-center justify-center gap-2 rounded-lg gradient-primary px-3 py-2 text-sm font-semibold text-white shadow-md"
        >
          <Plus className="h-4 w-4" />
          {t("sidebar.newChat", { defaultValue: "新建会话" })}
        </button>
      </div>

      {/* 搜索 */}
      <div className="relative mt-4 px-4">
        <Search className="pointer-events-none absolute left-7 top-2.5 h-4 w-4 text-muted-foreground" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("sidebar.searchPlaceholder", { defaultValue: "搜索历史会话…" })}
          className="w-full rounded-lg border border-border bg-muted/40 py-2 pl-9 pr-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-primary"
        />
      </div>

      {/* 会话列表 */}
      <div className="flex-1 overflow-hidden">
        <ChatList
          sessions={filteredSessions}
          activeKey={props.activeKey}
          loading={props.loading}
          emptyLabel={
            normalizedQuery ? t("sidebar.noSearchResults") : t("chat.noSessions")
          }
          onSelect={props.onSelect}
          onRequestDelete={props.onRequestDelete}
        />
      </div>

      {/* 底部 */}
      <div className="mt-auto border-t border-border px-4 py-3">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {t("sidebar.sessionCount", { defaultValue: "共 {{count}} 个会话", count: props.sessions.length })}
          </span>
          <button
            type="button"
            disabled={!props.activeKey}
            onClick={() => {
              if (!props.activeKey) return;
              const s = props.sessions.find((sess) => sess.key === props.activeKey);
              if (!s) return;
              const label = s.title || s.preview || s.chatId.slice(0, 6);
              props.onRequestDelete(props.activeKey, label);
            }}
            className="inline-flex items-center gap-1 hover:text-primary disabled:opacity-40"
          >
            <Archive className="h-3.5 w-3.5" />
            {t("sidebar.archive", { defaultValue: "归档" })}
          </button>
        </div>
      </div>
    </nav>
  );
}
