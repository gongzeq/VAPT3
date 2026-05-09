import { useTranslation } from "react-i18next";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Search,
  ShieldAlert,
  Sparkles,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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

interface PromptDef {
  /** i18n key under `home.prompts.<key>` (with defaultValue fallback). */
  key: string;
  defaultText: string;
  icon: LucideIcon;
}

const PROMPTS: PromptDef[] = [
  {
    key: "scanAsset",
    defaultText: "对资产 192.168.1.0/24 发起一次轻量端口扫描，重点看 Web 服务",
    icon: Search,
  },
  {
    key: "weakPwd",
    defaultText: "对最近一周新增的资产做一轮弱口令探测，结果按高危聚合",
    icon: ShieldAlert,
  },
  {
    key: "summarize",
    defaultText: "把今天的扫描发现按业务系统聚合，生成一份执行摘要",
    icon: Sparkles,
  },
  {
    key: "drill",
    defaultText: "针对最近一条高危漏洞，给我一个验证 PoC 与修复建议",
    icon: Wand2,
  },
];

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

export interface PromptSuggestionsProps {
  className?: string;
}

/**
 * Left rail used by the HomePage chat surface. Combines:
 *   1. PromptSuggestions chips — onClick prefills the composer textarea.
 *   2. Quick stats card        — three KPI rows with mock values for now;
 *      PR5 (Dashboard) will hoist real data into a shared hook so this rail
 *      can subscribe rather than hard-code.
 *
 * The rail is purely presentational — no data fetching, no navigation. It
 * never owns selection state, so it stays cheap to mount/unmount inside the
 * router shell.
 */
export function PromptSuggestions({ className }: PromptSuggestionsProps) {
  const { t } = useTranslation();
  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-full flex-col gap-4 overflow-y-auto p-4",
        className,
      )}
      aria-label={t("home.leftRail.aria", { defaultValue: "建议与快捷指标" })}
    >
      <section className="rounded-xl border border-border/40 bg-card/50 p-4 backdrop-blur">
        <header className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span>
            {t("home.prompts.title", { defaultValue: "试试这些任务" })}
          </span>
        </header>
        <ul className="flex flex-col gap-2">
          {PROMPTS.map((p) => {
            const Icon = p.icon;
            const label = t(`home.prompts.${p.key}`, {
              defaultValue: p.defaultText,
            });
            return (
              <li key={p.key}>
                <Button
                  type="button"
                  variant="ghost"
                  className={cn(
                    "h-auto w-full justify-start gap-2 whitespace-normal rounded-lg",
                    "border border-border/40 bg-background/40 px-3 py-2 text-left text-sm font-normal",
                    "hover:border-primary/40 hover:bg-primary/5 hover:text-foreground",
                    "transition-smooth",
                  )}
                  onClick={() => dispatchComposerPrefill(label)}
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span className="leading-snug">{label}</span>
                </Button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="rounded-xl border border-border/40 bg-card/50 p-4 backdrop-blur">
        <header className="mb-3 flex items-center justify-between text-xs uppercase tracking-wider text-muted-foreground">
          <span>{t("home.stats.title", { defaultValue: "工作台速览" })}</span>
          <span className="text-[10px] normal-case text-muted-foreground/70">
            {t("home.stats.mockBadge", { defaultValue: "样例数据" })}
          </span>
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

      <p className="px-1 text-[10px] leading-relaxed text-muted-foreground/70">
        {t("home.leftRail.footer", {
          defaultValue:
            "样例数据将在 Dashboard 上线后接入真实指标（PRD R4.3 / PR5）。",
        })}
      </p>
    </aside>
  );
}

export default PromptSuggestions;
