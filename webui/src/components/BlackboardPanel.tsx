import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertOctagon,
  Flag,
  Lightbulb,
  PanelRightClose,
  Radio,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { useClient } from "@/providers/ClientProvider";
import { fetchBlackboard } from "@/lib/api";
import type { BlackboardEntry, BlackboardKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_RENDER = 100;

/** Regex fallback for free-form entries whose backend ``kind`` is null.
 * Mirrors :func:`secbot.agent.blackboard._extract_kind` so the UI degrades
 * gracefully even when an agent forgets the prefix. */
const KIND_REGEX = /^\s*\[(milestone|blocker|finding|progress)\]/i;

/** Visual contract per spec ``frontend/component-patterns.md`` §1: colours
 * are pulled from the ``--bb-*`` token aliases, never raw hex. */
const KIND_STYLES: Record<
  BlackboardKind,
  { stripe: string; bg: string; iconColor: string; icon: LucideIcon; label: string }
> = {
  milestone: {
    stripe: "border-l-blackboard-milestone",
    bg: "bg-blackboard-milestone/10",
    iconColor: "text-blackboard-milestone",
    icon: Flag,
    label: "milestone",
  },
  blocker: {
    stripe: "border-l-blackboard-blocker",
    bg: "bg-blackboard-blocker/10",
    iconColor: "text-blackboard-blocker",
    icon: AlertOctagon,
    label: "blocker",
  },
  finding: {
    stripe: "border-l-blackboard-finding",
    bg: "bg-blackboard-finding/10",
    iconColor: "text-blackboard-finding",
    icon: Lightbulb,
    label: "finding",
  },
  progress: {
    stripe: "border-l-blackboard-progress",
    bg: "bg-blackboard-progress/10",
    iconColor: "text-blackboard-progress",
    icon: TrendingUp,
    label: "progress",
  },
};

function deriveKind(entry: BlackboardEntry): BlackboardKind | null {
  if (entry.kind) return entry.kind;
  const m = (entry.text ?? "").match(KIND_REGEX);
  if (!m) return null;
  return m[1].toLowerCase() as BlackboardKind;
}

function formatTime(ts: number | undefined): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString();
}

export interface BlackboardPanelProps {
  /** Active chat id; when ``null`` the panel renders an empty state. */
  chatId: string | null;
  className?: string;
  onToggleRightRail?: () => void;
}

/**
 * Right-rail Blackboard panel — F8 of ``05-12-multi-agent-obs-blackboard``.
 *
 * Lifecycle:
 *  - On mount / chatId change: ``GET /api/blackboard?chat_id=<id>`` for the
 *    full historical replay so reloading the page does not lose entries.
 *  - WebSocket subscription via ``client.onChat`` filters
 *    ``agent_event.blackboard_entry`` frames and appends them by ``id`` (or
 *    timestamp+text fallback) to keep state in sync without refetching.
 *
 * Render contract:
 *  - Show only the most recent ``MAX_RENDER`` (=100) entries to keep the DOM
 *    cheap; the header surfaces ``显示最近 100 / 共 N 条`` when N exceeds the
 *    cap (PRD D6).
 *  - Each row colour-coded by ``entry.kind`` (regex fallback when null).
 *  - ``blocker`` rows pulse with ``animate-breath`` to draw attention.
 */
export function BlackboardPanel({
  chatId,
  className,
  onToggleRightRail,
}: BlackboardPanelProps) {
  const { t } = useTranslation();
  const { client, token } = useClient();
  const [entries, setEntries] = useState<BlackboardEntry[]>([]);
  const [loading, setLoading] = useState(false);
  // Track ids that have already been appended so WS frames arriving after
  // the HTTP replay don't double-render the same entry.
  const seenIds = useRef<Set<string>>(new Set());

  // Reset state on chat switch.
  useEffect(() => {
    setEntries([]);
    seenIds.current = new Set();
  }, [chatId]);

  // HTTP replay: pull historical entries for this chat.
  useEffect(() => {
    if (!chatId || !token) return;
    let cancelled = false;
    setLoading(true);
    fetchBlackboard(token, chatId)
      .then((rows) => {
        if (cancelled) return;
        const seen = new Set<string>();
        for (const row of rows) {
          if (row.id) seen.add(row.id);
        }
        seenIds.current = seen;
        setEntries(rows);
      })
      .catch((err) => {
        // Network / 4xx — degrade-don't-crash: leave entries empty so the
        // WS feed can still populate the panel.
        console.warn("fetchBlackboard failed", err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chatId, token]);

  // WS subscription: incremental append on agent_event.blackboard_entry.
  useEffect(() => {
    if (!chatId) return;
    const off = client.onChat(chatId, (ev) => {
      if (ev.event !== "agent_event") return;
      if (ev.type !== "blackboard_entry") return;
      const p = ev.payload;
      const id = p.id ?? `${p.timestamp ?? Date.now()}|${p.text ?? ""}`;
      if (seenIds.current.has(id)) return;
      seenIds.current.add(id);
      const next: BlackboardEntry = {
        id,
        agent_name: p.agent_name,
        text: p.text,
        timestamp: p.timestamp,
        kind: p.kind ?? null,
      };
      setEntries((prev) => [...prev, next]);
    });
    return () => off();
  }, [chatId, client]);

  const visible = useMemo(() => entries.slice(-MAX_RENDER), [entries]);
  const total = entries.length;
  const overCap = total > MAX_RENDER;

  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-full flex-col gap-3 overflow-hidden",
        className,
      )}
      aria-label={t("home.blackboard.aria", { defaultValue: "黑板面板" })}
    >
      {/* Header: title + LIVE chip + collapse button + count */}
      <header className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold text-foreground">
            {t("home.blackboard.title", { defaultValue: "黑板" })}
          </h4>
          <span
            className="inline-flex items-center gap-1 rounded-full border border-status-run/30 bg-status-run/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-status-run"
            aria-label={t("home.blackboard.live", { defaultValue: "实时" })}
          >
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-run opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-status-run" />
            </span>
            <Radio className="h-3 w-3" />
            LIVE
          </span>
        </div>
        {onToggleRightRail && (
          <button
            type="button"
            onClick={onToggleRightRail}
            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-white/5 hover:text-foreground"
            aria-label={t("thread.header.toggleRightRail", {
              defaultValue: "折叠工作台",
            })}
            title={t("thread.header.toggleRightRail", {
              defaultValue: "折叠工作台",
            })}
          >
            <PanelRightClose className="h-3.5 w-3.5" />
          </button>
        )}
      </header>

      {/* Count line */}
      <div className="px-1 text-xs text-muted-foreground">
        {overCap
          ? t("home.blackboard.countOver", {
              defaultValue: "显示最近 {{shown}} / 共 {{total}} 条",
              shown: MAX_RENDER,
              total,
            })
          : t("home.blackboard.count", {
              defaultValue: "共 {{total}} 条",
              total,
            })}
      </div>

      {/* Entries */}
      <div className="flex-1 min-h-0 space-y-2 overflow-y-auto scroll-hide pr-1">
        {visible.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/30 px-3 py-6 text-center text-xs text-muted-foreground">
            {chatId
              ? loading
                ? t("home.blackboard.loading", { defaultValue: "加载中…" })
                : t("home.blackboard.empty", {
                    defaultValue: "智能体尚未在此会话写入条目",
                  })
              : t("home.blackboard.noChat", {
                  defaultValue: "选择会话后查看黑板",
                })}
          </div>
        ) : (
          visible.map((entry) => {
            const kind = deriveKind(entry);
            const style = kind ? KIND_STYLES[kind] : null;
            const Icon = style?.icon ?? Lightbulb;
            const isBlocker = kind === "blocker";
            return (
              <article
                key={entry.id ?? `${entry.timestamp}-${entry.text}`}
                className={cn(
                  "rounded-lg border-l-4 p-3 transition-colors",
                  style?.stripe ?? "border-l-border",
                  style?.bg ?? "bg-muted/30",
                  isBlocker && "animate-breath",
                )}
              >
                <div className="mb-1 flex items-center gap-2">
                  <Icon
                    className={cn(
                      "h-3.5 w-3.5 shrink-0",
                      style?.iconColor ?? "text-muted-foreground",
                    )}
                  />
                  <span
                    className={cn(
                      "text-xs font-semibold",
                      style?.iconColor ?? "text-foreground",
                    )}
                  >
                    {entry.agent_name ?? "agent"}
                  </span>
                  {style?.label && (
                    <span className="rounded bg-background/40 px-1.5 py-px text-[10px] uppercase tracking-wider text-muted-foreground">
                      {style.label}
                    </span>
                  )}
                  <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
                    {formatTime(entry.timestamp)}
                  </span>
                </div>
                <p className="text-sm leading-relaxed text-foreground">
                  {entry.text}
                </p>
              </article>
            );
          })
        )}
      </div>
    </aside>
  );
}

export default BlackboardPanel;
