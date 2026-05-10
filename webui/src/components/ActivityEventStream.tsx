import { useTranslation } from "react-i18next";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { useActivityStream } from "@/hooks/useActivityStream";
import type {
  ActivityEvent,
  ActivityLevel,
  ActivitySource,
} from "@/lib/types";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const LEVEL_TONE: Record<ActivityLevel, string> = {
  critical: "text-rose-400",
  warning: "text-amber-400",
  info: "text-ocean-400",
  ok: "text-emerald-400",
};

const LEVEL_DOT: Record<ActivityLevel, string> = {
  critical: "bg-rose-500",
  warning: "bg-amber-400",
  info: "bg-ocean-400",
  ok: "bg-emerald-400",
};

function levelIcon(level: ActivityLevel) {
  switch (level) {
    case "critical":
      return ShieldAlert;
    case "warning":
      return AlertTriangle;
    case "ok":
      return CheckCircle2;
    case "info":
    default:
      return Info;
  }
}

/** Render the source chip — uses the i18n ``activity.source.<source>``
 * key; unknown sources fall back to the raw string (F5). */
function sourceLabel(t: ReturnType<typeof useTranslation>["t"], source: ActivitySource | string): string {
  return t(`activity.source.${source}`, { defaultValue: String(source) });
}

export interface ActivityEventStreamProps {
  /** Optional override: defaults to 100 rows (ACTIVITY_STREAM_LIMIT). */
  height?: number | string;
  /** Test seam — inject a pre-built row list and skip the live hook. */
  events?: ActivityEvent[];
  /** Test seam — override state without exercising the hook. */
  state?: "loading" | "ready" | "error";
  errorCode?: string | null;
  onRefresh?: () => void;
}

/** Thin presentational shell — accepts pre-rendered data. Kept pure so
 * it's trivially testable without a ClientProvider. */
function ActivityEventStreamView({
  height = 320,
  events,
  state,
  errorCode,
  onRefresh,
}: {
  height?: number | string;
  events: ActivityEvent[];
  state: "loading" | "ready" | "error";
  errorCode: string | null;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div
      className="gradient-card rounded-2xl border border-border p-5 animate-fade-in-up"
      data-testid="activity-event-stream"
    >
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold">
            <Activity className="h-4 w-4 text-primary" />
            {t("activity.title", { defaultValue: "活动事件流" })}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("activity.subtitle", { defaultValue: "大屏实时智能体行为" })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium",
              state === "error"
                ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
                : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
            )}
            data-testid="activity-live-indicator"
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                state === "error" ? "bg-rose-500" : "bg-emerald-400 animate-pulse",
              )}
            />
            {state === "error"
              ? t("activity.paused", { defaultValue: "已暂停" })
              : t("activity.live", { defaultValue: "实时" })}
          </span>
          <button
            type="button"
            onClick={() => onRefresh()}
            aria-label={t("activity.retry", { defaultValue: "重试" })}
            className="rounded-md border border-border p-1.5 text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {state === "loading" && events.length === 0 && (
        <div className="flex items-center justify-center py-10 text-xs text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {t("activity.loading", { defaultValue: "加载中…" })}
        </div>
      )}

      {state === "error" && events.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 py-10 text-xs text-muted-foreground">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <span>
            {t(`activity.error.${errorCode ?? "network"}`, {
              defaultValue: t("activity.error.network", {
                defaultValue: "加载失败",
              }),
            })}
          </span>
          <button
            type="button"
            onClick={() => onRefresh()}
            className="rounded-md border border-border px-2 py-1 text-xs text-primary hover:bg-primary/10"
          >
            {t("activity.retry", { defaultValue: "重试" })}
          </button>
        </div>
      )}

      {state !== "loading" && state !== "error" && events.length === 0 && (
        <div className="flex items-center justify-center py-10 text-xs text-muted-foreground">
          {t("activity.empty", { defaultValue: "暂无事件" })}
        </div>
      )}

      {events.length > 0 && (
        <ScrollArea style={{ height }}>
          <ul className="space-y-2">
            {events.map((ev) => {
              const Icon = levelIcon(ev.level);
              return (
                <li
                  key={ev.id}
                  className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5 transition-colors hover:border-border"
                  data-testid="activity-event-row"
                  data-level={ev.level}
                  data-source={ev.source}
                >
                  <span className="mt-1 flex-shrink-0">
                    <span
                      className={cn(
                        "block h-2 w-2 rounded-full",
                        LEVEL_DOT[ev.level],
                      )}
                      aria-hidden
                    />
                  </span>
                  <Icon
                    className={cn(
                      "mt-0.5 h-4 w-4 flex-shrink-0",
                      LEVEL_TONE[ev.level],
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-xs">
                      <span
                        className={cn(
                          "rounded-full border px-1.5 py-0.5 font-medium",
                          "border-border/50 bg-background/40 text-muted-foreground",
                        )}
                      >
                        {sourceLabel(t, ev.source)}
                      </span>
                      {ev.category && (
                        <span className="text-[11px] text-muted-foreground/80">
                          {t(`activity.category.${ev.category}`, {
                            defaultValue: ev.category,
                          })}
                        </span>
                      )}
                      <span className="ml-auto font-mono text-[11px] text-muted-foreground/70">
                        {relativeTime(ev.timestamp)}
                      </span>
                    </div>
                    {ev.message && (
                      <p className="mt-0.5 truncate text-sm text-foreground">
                        {ev.message}
                      </p>
                    )}
                    {ev.step && (
                      <p className="mt-0.5 text-[11px] font-mono text-muted-foreground/70">
                        {ev.step}
                        {typeof ev.duration_ms === "number" && (
                          <> · {ev.duration_ms}ms</>
                        )}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </ScrollArea>
      )}
    </div>
  );
}

/** Live wrapper: hosts :func:`useActivityStream` and forwards to the view. */
function ActivityEventStreamLive({ height }: { height?: number | string }) {
  const { events, state, errorCode, refresh } = useActivityStream();
  return (
    <ActivityEventStreamView
      height={height}
      events={events}
      state={state}
      errorCode={errorCode}
      onRefresh={() => void refresh()}
    />
  );
}

/**
 * Renders the live activity stream on the dashboard.
 *
 * Two modes:
 *   - Production: renders :component:`ActivityEventStreamLive`, which
 *     hosts :func:`useActivityStream` itself.
 *   - Test: the harness supplies ``events`` / ``state`` / ``errorCode``
 *     directly, bypassing the hook entirely via the pure view.
 */
export function ActivityEventStream({
  height,
  events,
  state,
  errorCode,
  onRefresh,
}: ActivityEventStreamProps) {
  if (events !== undefined) {
    return (
      <ActivityEventStreamView
        height={height}
        events={events}
        state={state ?? "ready"}
        errorCode={errorCode ?? null}
        onRefresh={onRefresh ?? (() => {})}
      />
    );
  }
  return <ActivityEventStreamLive height={height} />;
}

export default ActivityEventStream;
