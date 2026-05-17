import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bug,
  Globe,
  KeyRound,
  Layers,
  Network,
  PanelRightClose,
  Radio,
  Server,
  Shapes,
  type LucideIcon,
} from "lucide-react";

import { useClient } from "@/providers/ClientProvider";
import { fetchAssetFeed } from "@/lib/api";
import type { AssetEntry, AssetKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_RENDER = 200;

const KIND_META: Record<
  AssetKind,
  { icon: LucideIcon; label: string; color: string }
> = {
  url: { icon: Globe, label: "URL", color: "text-sky-300" },
  port: { icon: Network, label: "PORT", color: "text-amber-300" },
  service: { icon: Server, label: "SERVICE", color: "text-emerald-300" },
  credential: { icon: KeyRound, label: "CREDENTIAL", color: "text-fuchsia-300" },
  vuln: { icon: Bug, label: "VULN", color: "text-rose-300" },
  tech: { icon: Layers, label: "TECH", color: "text-indigo-300" },
};

const KNOWN_KINDS = new Set<string>([
  "url",
  "port",
  "service",
  "credential",
  "vuln",
  "tech",
]);

function formatTime(ts: number | undefined): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString();
}

/** Pick the most informative one-line summary of a payload. We never
 * dump the whole JSON: the panel must stay glanceable. */
function describePayload(entry: AssetEntry): string {
  const p = entry.payload || {};
  const kind = entry.kind;
  const get = (k: string): string | null => {
    const v = p[k];
    return typeof v === "string" || typeof v === "number" ? String(v) : null;
  };

  if (kind === "url") {
    const url = get("url") ?? get("path");
    const status = get("status");
    const title = get("title");
    if (url && status) return title ? `${url} [${status}] ${title}` : `${url} [${status}]`;
    if (url) return title ? `${url} — ${title}` : url;
  }
  if (kind === "port") {
    const host = get("host");
    const port = get("port");
    const service = get("service");
    if (host && port) return service ? `${host}:${port} (${service})` : `${host}:${port}`;
  }
  if (kind === "service") {
    const host = get("host");
    const port = get("port");
    const service = get("service") ?? get("name");
    const version = get("version");
    const head = host && port ? `${host}:${port}` : host || "";
    const svc = service ? (version ? `${service} ${version}` : service) : "";
    const merged = [head, svc].filter(Boolean).join(" — ");
    if (merged) return merged;
  }
  if (kind === "credential") {
    const username = get("username") ?? get("user");
    const host = get("host");
    const service = get("service");
    const parts = [username, service, host].filter(Boolean);
    if (parts.length) return parts.join(" @ ");
  }
  if (kind === "vuln") {
    const cve = get("cve");
    const severity = get("severity");
    const target = get("url") ?? get("host");
    const name = get("name") ?? get("title");
    const head = [cve, severity].filter(Boolean).join(" ");
    const tail = [name, target].filter(Boolean).join(" — ");
    const merged = [head, tail].filter(Boolean).join(": ");
    if (merged) return merged;
  }
  if (kind === "tech") {
    const tech = get("tech") ?? get("name") ?? get("framework");
    const version = get("version");
    const target = get("url") ?? get("host");
    const head = tech ? (version ? `${tech} ${version}` : tech) : "";
    const merged = [head, target].filter(Boolean).join(" @ ");
    if (merged) return merged;
  }
  // Fallback: compact JSON.
  try {
    return JSON.stringify(p);
  } catch {
    return String(p);
  }
}

export interface AssetsPanelProps {
  chatId: string | null;
  className?: string;
  onToggleRightRail?: () => void;
}

/** Right-rail Assets panel — mirrors :class:`BlackboardPanel` but reads
 * the per-chat asset feed (PR-3 of ``05-17-bb-realtime-notify``).
 *
 * Lifecycle:
 *  - Mount / chat switch: ``GET /api/assets?chat_id=<id>`` HTTP replay.
 *  - WS subscription: ``agent_event.asset_pushed`` appends new rows in
 *    real time, deduped by entry id.
 */
export function AssetsPanel({
  chatId,
  className,
  onToggleRightRail,
}: AssetsPanelProps) {
  const { t } = useTranslation();
  const { client, token } = useClient();
  const [entries, setEntries] = useState<AssetEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<string | null>(null);
  const seenIds = useRef<Set<number>>(new Set());

  // Reset state on chat switch.
  useEffect(() => {
    setEntries([]);
    seenIds.current = new Set();
  }, [chatId]);

  // HTTP replay.
  useEffect(() => {
    if (!chatId || !token) return;
    let cancelled = false;
    setLoading(true);
    fetchAssetFeed(token, chatId)
      .then((snap) => {
        if (cancelled) return;
        const seen = new Set<number>();
        for (const row of snap.entries) {
          if (typeof row.id === "number") seen.add(row.id);
        }
        seenIds.current = seen;
        setEntries(snap.entries);
      })
      .catch((err) => {
        console.warn("fetchAssetFeed failed", err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chatId, token]);

  // WS subscription.
  useEffect(() => {
    if (!chatId) return;
    const off = client.onChat(chatId, (ev) => {
      if (ev.event !== "agent_event") return;
      if (ev.type !== "asset_pushed") return;
      const p = ev.payload as unknown as AssetEntry;
      const id = typeof p.id === "number" ? p.id : Number(p.id);
      if (!id || seenIds.current.has(id)) return;
      seenIds.current.add(id);
      const next: AssetEntry = {
        id,
        kind: String(p.kind ?? "unknown"),
        agent_name: String(p.agent_name ?? "agent"),
        payload: (p.payload as Record<string, unknown>) ?? {},
        created_at: typeof p.created_at === "number" ? p.created_at : Date.now() / 1000,
      };
      setEntries((prev) => [...prev, next]);
    });
    return () => off();
  }, [chatId, client]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of entries) c[e.kind] = (c[e.kind] ?? 0) + 1;
    return c;
  }, [entries]);

  const filtered = useMemo(() => {
    if (!filter) return entries;
    return entries.filter((e) => e.kind === filter);
  }, [entries, filter]);

  const visible = useMemo(() => filtered.slice(-MAX_RENDER), [filtered]);
  const total = filtered.length;
  const overCap = total > MAX_RENDER;

  const kindKeys = useMemo(() => {
    const set = new Set<string>(Object.keys(counts));
    return Array.from(set).sort();
  }, [counts]);

  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-full flex-col gap-3 overflow-hidden",
        className,
      )}
      aria-label={t("home.assets.aria", { defaultValue: "资产清单面板" })}
    >
      <header className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold text-foreground">
            {t("home.assets.title", { defaultValue: "资产清单" })}
          </h4>
          <span
            className="inline-flex items-center gap-1 rounded-full border border-status-run/30 bg-status-run/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-status-run"
            aria-label={t("home.assets.live", { defaultValue: "实时" })}
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

      {/* Kind filter chips */}
      {kindKeys.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-1">
          <button
            type="button"
            onClick={() => setFilter(null)}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider",
              filter === null
                ? "border-foreground/40 bg-foreground/10 text-foreground"
                : "border-border bg-muted/30 text-muted-foreground hover:text-foreground",
            )}
          >
            {t("home.assets.all", { defaultValue: "全部" })} · {entries.length}
          </button>
          {kindKeys.map((k) => {
            const meta = KNOWN_KINDS.has(k)
              ? KIND_META[k as AssetKind]
              : { icon: Shapes, label: k.toUpperCase(), color: "text-muted-foreground" };
            const Icon = meta.icon;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setFilter(k === filter ? null : k)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider",
                  filter === k
                    ? "border-foreground/40 bg-foreground/10 text-foreground"
                    : "border-border bg-muted/30 text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className={cn("h-3 w-3", meta.color)} />
                {meta.label} · {counts[k]}
              </button>
            );
          })}
        </div>
      )}

      {/* Count line */}
      <div className="px-1 text-xs text-muted-foreground">
        {overCap
          ? t("home.assets.countOver", {
              defaultValue: "显示最近 {{shown}} / 共 {{total}} 条",
              shown: MAX_RENDER,
              total,
            })
          : t("home.assets.count", {
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
                ? t("home.assets.loading", { defaultValue: "加载中…" })
                : t("home.assets.empty", {
                    defaultValue: "尚未发现资产",
                  })
              : t("home.assets.noChat", {
                  defaultValue: "选择会话后查看资产清单",
                })}
          </div>
        ) : (
          visible.map((entry) => {
            const meta = KNOWN_KINDS.has(entry.kind)
              ? KIND_META[entry.kind as AssetKind]
              : {
                  icon: Shapes,
                  label: entry.kind.toUpperCase(),
                  color: "text-muted-foreground",
                };
            const Icon = meta.icon;
            return (
              <article
                key={entry.id}
                className="rounded-lg border border-border/60 bg-muted/20 p-3 transition-colors hover:border-border"
              >
                <div className="mb-1 flex items-center gap-2">
                  <Icon className={cn("h-3.5 w-3.5 shrink-0", meta.color)} />
                  <span
                    className={cn(
                      "rounded bg-background/40 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider",
                      meta.color,
                    )}
                  >
                    {meta.label}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {entry.agent_name}
                  </span>
                  <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
                    #{entry.id} · {formatTime(entry.created_at)}
                  </span>
                </div>
                <p className="break-all text-xs leading-relaxed text-foreground">
                  {describePayload(entry)}
                </p>
              </article>
            );
          })
        )}
      </div>
    </aside>
  );
}

export default AssetsPanel;
