import { useTranslation } from "react-i18next";
import {
  Activity,
  AlertTriangle,
  Bug,
  CheckCircle2,
  FileText,
  Key,
  Loader,
  PanelLeftClose,
  Radar,
  Zap,
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

interface PromptDef {
  /** i18n key under `home.prompts.<key>` (with defaultValue fallback). */
  key: string;
  title: string;
  subtitle: string;
  prefill: string;
  icon: LucideIcon;
}

const PROMPTS: PromptDef[] = [
  {
    key: "scanAsset",
    title: "全网资产发现",
    subtitle: "扫描内网所有存活主机并入库 CMDB",
    prefill: "对资产 192.168.1.0/24 发起一次轻量端口扫描，重点看 Web 服务",
    icon: Radar,
  },
  {
    key: "weakPwd",
    title: "弱口令检测",
    subtitle: "SSH/RDP/SMB 常见服务字典爆破",
    prefill: "对最近一周新增的资产做一轮弱口令探测，结果按高危聚合",
    icon: Key,
  },
  {
    key: "summarize",
    title: "月度合规报告",
    subtitle: "汇总当月扫描数据导出 PDF",
    prefill: "把今天的扫描发现按业务系统聚合，生成一份执行摘要",
    icon: FileText,
  },
  {
    key: "drill",
    title: "CVE 影响排查",
    subtitle: "输入 CVE 编号，自动定位受影响资产",
    prefill: "针对最近一条高危漏洞，给我一个验证 PoC 与修复建议",
    icon: Bug,
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

interface AgentDef {
  key: string;
  name: string;
  icon: LucideIcon;
  status: "idle" | "running" | "queued";
}

const AGENTS: AgentDef[] = [
  { key: "asset_discovery", name: "asset_discovery", icon: Radar, status: "idle" },
  { key: "port_scan", name: "port_scan", icon: Loader, status: "running" },
  { key: "vuln_scan", name: "vuln_scan", icon: Bug, status: "queued" },
  { key: "weak_password", name: "weak_password", icon: Key, status: "idle" },
];

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
  onToggleSidebar?: () => void;
}

/**
 * Right rail used by the HomePage chat surface. Combines:
 *   1. Quick stats card        — three KPI rows with mock values for now.
 *   2. PromptSuggestions chips — onClick prefills the composer textarea.
 *   3. Online agents card      — list of active expert agents.
 *
 * The rail is purely presentational — no data fetching, no navigation. It
 * never owns selection state, so it stays cheap to mount/unmount inside the
 * router shell.
 */
export function PromptSuggestions({
  className,
  onToggleSidebar,
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
      {/* Top: sidebar collapse toggle */}
      {onToggleSidebar && (
        <div className="flex items-center justify-end px-1 pt-1">
          <button
            type="button"
            onClick={onToggleSidebar}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
            aria-label={t("thread.header.toggleSidebar")}
            title={t("thread.header.toggleSidebar")}
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* KPI 速览 — G1/G2  layout & content kept as-is */}
      <section className="gradient-card rounded-2xl border border-border p-5 space-y-3">
        <header className="flex items-center justify-between text-xs uppercase tracking-wider text-muted-foreground">
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

      {/* 快捷指令 */}
      <section className="gradient-card rounded-2xl border border-border p-5 space-y-3">
        <header className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-primary" />
          <h4 className="text-sm font-semibold">
            {t("home.prompts.title", { defaultValue: "快捷指令" })}
          </h4>
        </header>
        <div className="space-y-2">
          {PROMPTS.map((p) => {
            const Icon = p.icon;
            const title = t(`home.prompts.${p.key}.title`, {
              defaultValue: p.title,
            });
            const subtitle = t(`home.prompts.${p.key}.subtitle`, {
              defaultValue: p.subtitle,
            });
            const prefill = t(`home.prompts.${p.key}.prefill`, {
              defaultValue: p.prefill,
            });
            return (
              <button
                key={p.key}
                type="button"
                className="hover-lift group w-full rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-left text-sm hover:border-primary/40 hover:bg-primary/5"
                onClick={() => dispatchComposerPrefill(prefill)}
              >
                <div className="flex items-center gap-2 font-medium text-foreground">
                  <Icon className="h-3.5 w-3.5 text-primary" />
                  {title}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground group-hover:text-white/70">
                  {subtitle}
                </p>
              </button>
            );
          })}
        </div>
      </section>

      {/* 在线智能体 */}
      <section className="gradient-card rounded-2xl border border-border p-5 space-y-3">
        <header className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">
            {t("home.agents.title", { defaultValue: "专家智能体 (4)" })}
          </h4>
          <span className="text-xs text-emerald-500">
            {t("home.agents.status", { defaultValue: "● 全部在线" })}
          </span>
        </header>
        <ul className="space-y-2 text-xs">
          {AGENTS.map((agent) => {
            const Icon = agent.icon;
            const isRunning = agent.status === "running";
            return (
              <li
                key={agent.key}
                className={cn(
                  "flex items-center justify-between rounded-md px-2.5 py-1.5",
                  isRunning
                    ? "border border-primary/30 bg-primary/10"
                    : "bg-muted/40",
                )}
              >
                <span className="flex items-center gap-2 text-foreground">
                  <Icon
                    className={cn(
                      "h-3.5 w-3.5 text-primary",
                      isRunning && "animate-spin",
                    )}
                  />
                  {agent.name}
                </span>
                <span
                  className={cn(
                    "font-mono",
                    isRunning ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {agent.status}
                </span>
              </li>
            );
          })}
        </ul>
      </section>
    </aside>
  );
}

export default PromptSuggestions;
