import { MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { displaySessionTitle, sessionSubtitle } from "@/lib/session-title";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

interface ChatListProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  loading?: boolean;
  emptyLabel?: string;
}

function formatTimeLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (d >= startOfToday) {
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  const startOfYesterday = new Date(startOfToday.getTime() - 24 * 60 * 60 * 1000);
  if (d >= startOfYesterday) {
    return "昨天";
  }
  return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export function ChatList({
  sessions,
  activeKey,
  onSelect,
  onRequestDelete,
  loading,
  emptyLabel,
}: ChatListProps) {
  const { t } = useTranslation();
  if (loading && sessions.length === 0) {
    return (
      <div className="px-3 py-6 text-xs text-muted-foreground">
        {t("chat.loading")}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="px-3 py-6 text-xs leading-5 text-muted-foreground/80">
        {emptyLabel ?? t("chat.noSessions")}
      </div>
    );
  }

  const groups = groupSessions(sessions, {
    today: t("chat.groups.today"),
    yesterday: t("chat.groups.yesterday"),
    earlier: t("chat.groups.earlier"),
  });

  return (
    <ScrollArea className="h-full">
      <div className="px-2 py-1.5">
        {groups.map((group) => (
          <section key={group.label} aria-label={group.label}>
            <div className="mt-5 px-2 text-xs font-medium uppercase tracking-wider text-muted-foreground/70">
              {group.label}
            </div>
            <ul className="mt-1 space-y-1">
              {group.sessions.map((s) => {
                const active = s.key === activeKey;
                const title = displaySessionTitle(
                  s,
                  t("chat.newChat", { defaultValue: "新对话" }),
                );
                const subtitle = sessionSubtitle(s);
                const timeLabel = formatTimeLabel(s.updatedAt ?? s.createdAt);
                return (
                  <li key={s.key}>
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => onSelect(s.key)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSelect(s.key);
                        }
                      }}
                      className={cn(
                        "group relative w-full cursor-pointer rounded-lg px-3 py-2.5 text-left transition-all duration-150",
                        active
                          ? "sidebar-active-bar border border-primary/20 bg-primary/8"
                          : "hover:bg-primary/5",
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className={cn(
                            "truncate text-sm font-medium",
                            active ? "text-primary" : "text-foreground",
                          )}
                        >
                          {title}
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground/70">
                          {timeLabel}
                        </span>
                      </div>
                      {subtitle && (
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">
                          {subtitle}
                        </p>
                      )}
                      <DropdownMenu modal={false}>
                        <DropdownMenuTrigger
                          className={cn(
                            "absolute right-2 top-2 inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/75 opacity-0 transition-opacity",
                            "hover:bg-white/5 hover:text-foreground group-hover:opacity-100",
                            "focus-visible:opacity-100",
                            active && "opacity-100",
                          )}
                          aria-label={t("chat.actions", { title })}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="end"
                          onCloseAutoFocus={(event) => event.preventDefault()}
                        >
                          <DropdownMenuItem
                            onSelect={() => {
                              window.setTimeout(() => onRequestDelete(s.key, title), 0);
                            }}
                            className="text-destructive focus:text-destructive"
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            {t("chat.delete")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </ScrollArea>
  );
}

function groupSessions(
  sessions: ChatSummary[],
  labels: { today: string; yesterday: string; earlier: string },
): Array<{ label: string; sessions: ChatSummary[] }> {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
  const buckets = new Map<string, ChatSummary[]>();

  for (const session of sessions) {
    const timestamp = Date.parse(session.updatedAt ?? session.createdAt ?? "");
    const label = Number.isFinite(timestamp) && timestamp >= startOfToday
      ? labels.today
      : Number.isFinite(timestamp) && timestamp >= startOfYesterday
        ? labels.yesterday
        : labels.earlier;
    const bucket = buckets.get(label) ?? [];
    bucket.push(session);
    buckets.set(label, bucket);
  }

  return [labels.today, labels.yesterday, labels.earlier]
    .map((label) => ({ label, sessions: buckets.get(label) ?? [] }))
    .filter((group) => group.sessions.length > 0);
}
