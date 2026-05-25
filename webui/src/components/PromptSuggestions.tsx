import { useTranslation } from "react-i18next";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  PanelRightClose,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Custom DOM event broadcast when a chip is clicked. ThreadComposer listens
 * and prefills its textarea + focuses, without forcing the prompt rail and
 * the composer to share React state across the entire Shell tree.
 *
 * Keeping the contract here (vs inside Composer) so any future surface that
 * wants to inject text — e.g. a /command quick-pick or a scheduled-task
 * wizard — can dispatch the same event without round-tripping through
 * <Shell> props.
 */
export const COMPOSER_PREFILL_EVENT = "secbot:composer-prefill";

export interface ComposerPrefillDetail {
  text: string;
  /** When true, also focus the textarea after prefill. Default true. */
  focus?: boolean;
}

/**
 * Dispatches a composer prefill request. Exposed so other modules (tests,
 * future quick-action menus) can replay the same UX without instantiating
 * the suggestions panel.
 */
export function dispatchComposerPrefill(text: string, focus = true): void {
  if (typeof window === "undefined") return;
  const evt = new CustomEvent<ComposerPrefillDetail>(COMPOSER_PREFILL_EVENT, {
    detail: { text, focus },
  });
  window.dispatchEvent(evt);
}

interface QuickStat {
  /** i18n key under `home.stats.<key>`. */
  key: string;
  defaultLabel: string;
  value: string;
  trend: "up" | "down" | "flat";
  icon: LucideIcon;
  /** Tailwind text color token used on the icon + accent stripe. */
  tone: "primary" | "warning" | "success";
}

const QUICK_STATS: QuickStat[] = [
  {
    key: "activeTasks",
    defaultLabel: "进行中任务",
    value: "3",
    trend: "up",
    icon: Activity,
    tone: "primary",
  },
  {
    key: "openFindings",
    defaultLabel: "今日新增告警",
    value: "12",
    trend: "down",
    icon: AlertTriangle,
    tone: "warning",
  },
  {
    key: "passRate",
    defaultLabel: "本周扫描通过率",
    value: "86%",
    trend: "up",
    icon: CheckCircle2,
    tone: "success",
  },
];

const TONE_CLASSES: Record<QuickStat["tone"], { stripe: string; icon: string }> = {
  primary: { stripe: "border-l-primary", icon: "text-primary" },
  warning: { stripe: "border-l-alert-warning", icon: "text-alert-warning" },
  success: { stripe: "border-l-alert-success", icon: "text-alert-success" },
};

export interface PromptSuggestionsProps {
  className?: string;
  onToggleSidebar?: () => void;
  onToggleRightRail?: () => void;
}

/**
 * Right rail used by the HomePage chat surface. Combines:
 *   1. Quick stats card        — three KPI rows with mock values for now.
 *
 * The rail is purely presentational — no data fetching, no navigation. It
 * never owns selection state, so it stays cheap to mount/unmount inside the
 * router shell.
 *
 * NOTE: Quick prompts (快捷指令) have been moved to the empty chat state
 * (QuickPrompts component) and are no longer part of this rail.
 */
export function PromptSuggestions({
  className,
  onToggleRightRail,
}: PromptSuggestionsProps) {
  const { t } = useTranslation();
  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-full flex-col gap-4 overflow-y-auto scroll-hide",
        className,
      )}
      aria-label={t("home.leftRail.aria", { defaultValue: "建议与快捷指标" })}
    >
      {/* KPI 速览 — G1/G2  layout & content kept as-is */}
      <section className="gradient-card rounded-2xl border border-border p-5 space-y-3">
        <header className="flex items-center justify-between text-xs uppercase tracking-wider text-muted-foreground">
          <span>{t("home.stats.title", { defaultValue: "工作台速览" })}</span>
          {onToggleRightRail && (
            <button
              type="button"
              onClick={onToggleRightRail}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-white/5 hover:text-foreground"
              aria-label={t("thread.header.toggleRightRail", { defaultValue: "折叠工作台" })}
              title={t("thread.header.toggleRightRail", { defaultValue: "折叠工作台" })}
            >
              <PanelRightClose className="h-3.5 w-3.5" />
            </button>
          )}
        </header>
        <ul className="flex flex-col gap-2">
          {QUICK_STATS.map((s) => {
            const Icon = s.icon;
            const tone = TONE_CLASSES[s.tone];
            return (
              <li
                key={s.key}
                className={cn(
                  "flex items-center justify-between gap-3 rounded-lg border-l-4 bg-background/40 p-3",
                  tone.stripe,
                )}
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <Icon className={cn("h-4 w-4 shrink-0", tone.icon)} />
                  <span className="truncate text-sm text-muted-foreground">
                    {t(`home.stats.${s.key}`, { defaultValue: s.defaultLabel })}
                  </span>
                </div>
                <span className="font-mono text-base font-semibold tabular-nums text-foreground">
                  {s.value}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      {/* 在线智能体已迁出 — 现由 Sidebar 底部 sidebar.agents 分组（F6）
          基于 GET /api/agents?include_status=true + WS agent_status 事件
          实时驱动。这里保留注释以便后续做 Trace Tab 时知道哪个 section 已迁。 */}
    </aside>
  );
}

export default PromptSuggestions;
