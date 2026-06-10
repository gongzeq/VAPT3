import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowUpRight,
  Bug,
  Crosshair,
  Key,
  Radar,
  ShieldCheck,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ScanType } from "@/lib/types";

interface ScenarioDef {
  key: ScanType;
  titleKey: string;
  titleFallback: string;
  descKey: string;
  descFallback: string;
  templateKey: string;
  /** `{target}` is replaced with the user's input. */
  templateFallback: string;
  icon: LucideIcon;
  iconBgClass: string;
}

const SCENARIOS: ScenarioDef[] = [
  {
    key: "full",
    titleKey: "home.scan.full.label",
    titleFallback: "全量扫描",
    descKey: "home.scan.full.desc",
    descFallback: "资产 + 端口 + 漏洞 + 弱口令 + 报告",
    templateKey: "home.scan.full.template",
    templateFallback:
      "请对目标 {target} 执行全量安全扫描，包含资产探测、端口与服务识别、漏洞检测、弱口令爆破，并在最后生成 HTML 报告。",
    icon: Crosshair,
    iconBgClass: "bg-primary/15 text-primary",
  },
  {
    key: "vuln",
    titleKey: "home.scan.vuln.label",
    titleFallback: "漏洞扫描",
    descKey: "home.scan.vuln.desc",
    descFallback: "OWASP Top 10 + 已知 CVE 检测",
    templateKey: "home.scan.vuln.template",
    templateFallback:
      "请对目标 {target} 执行漏洞扫描（OWASP Top 10 与已知 CVE 检测），完成后生成 HTML 报告。",
    icon: Bug,
    iconBgClass: "bg-destructive/15 text-destructive",
  },
  {
    key: "weakpwd",
    titleKey: "home.scan.weakpwd.label",
    titleFallback: "弱口令检测",
    descKey: "home.scan.weakpwd.desc",
    descFallback: "SSH / RDP / SMB / HTTP 字典爆破",
    templateKey: "home.scan.weakpwd.template",
    templateFallback:
      "请对目标 {target} 执行弱口令检测，覆盖 SSH、RDP、SMB、HTTP 等常见服务的字典爆破。",
    icon: Key,
    iconBgClass: "bg-amber-500/15 text-amber-500 dark:text-amber-400",
  },
  {
    key: "asset",
    titleKey: "home.scan.asset.label",
    titleFallback: "仅资产探测",
    descKey: "home.scan.asset.desc",
    descFallback: "存活主机 + 端口指纹，结果落 CMDB",
    templateKey: "home.scan.asset.template",
    templateFallback:
      "请对目标 {target} 仅做资产与端口探测，结果写入 CMDB，不进行漏洞验证。",
    icon: Radar,
    iconBgClass: "bg-emerald-500/15 text-emerald-500 dark:text-emerald-400",
  },
];

export interface ScanQuickStartProps {
  /**
   * Submit the assembled prompt. Parent decides whether to call
   * `onCreateChat` then `send`, or `send` directly when a chat already
   * exists. Component becomes input-disabled while a submit is in-flight.
   */
  onSubmit: (prompt: string) => void;
  busy?: boolean;
  className?: string;
  /** Optional slot rendered next to the target input (e.g. asset management toggle). */
  assetSlot?: React.ReactNode;
}

/**
 * Hero quick-start: target input + 4 scenario buttons. Replaces the
 * original `<QuickPrompts />` static cards. Click → expand template →
 * dispatch directly to the chat.
 */
export function ScanQuickStart({
  onSubmit,
  busy = false,
  className,
  assetSlot,
}: ScanQuickStartProps) {
  const { t } = useTranslation();
  const [target, setTarget] = useState("");
  const trimmed = target.trim();
  const ready = trimmed.length > 0 && !busy;

  const handleScenario = useCallback(
    (scenario: ScenarioDef) => {
      if (!ready) return;
      const template = t(scenario.templateKey, {
        defaultValue: scenario.templateFallback,
      });
      const prompt = template.replace("{target}", trimmed);
      onSubmit(prompt);
    },
    [onSubmit, ready, t, trimmed],
  );

  return (
    <section className={cn("w-full", className)}>
      <header className="mb-3 flex items-center gap-2.5">
        <span className="icon-surface icon-surface-brand h-7 w-7 rounded-lg">
          <Zap className="h-4 w-4" />
        </span>
        <h4 className="text-sm font-semibold tracking-wide text-foreground">
          {t("home.scan.title", { defaultValue: "快捷指令" })}
        </h4>
        <span
          aria-hidden
          className="ml-1 h-px flex-1 bg-gradient-to-r from-border/70 to-transparent"
        />
      </header>

      {/* Target input + asset slot */}
      <div className="mb-4">
        <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5 text-primary" />
          {t("home.scan.target.label", { defaultValue: "扫描目标" })}
        </label>
        <div className="flex items-center gap-2">
          <Input
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            placeholder={t("home.scan.target.placeholder", {
              defaultValue: "192.168.1.10:8080  /  https://example.com",
            })}
            aria-label={t("home.scan.target.label", { defaultValue: "扫描目标" })}
            className="h-11 min-w-0 flex-1 bg-background/60 text-base placeholder:text-muted-foreground/60"
            disabled={busy}
            autoFocus
          />
          {assetSlot ? (
            <div className="shrink-0">{assetSlot}</div>
          ) : null}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground/80">
          {t("home.scan.target.hint", {
            defaultValue: "输入 IP+端口、域名或 CIDR，再点击下方场景按钮即可发起扫描",
          })}
        </p>
      </div>

      {/* 4 scenario buttons */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {SCENARIOS.map((scenario) => {
          const Icon = scenario.icon;
          const title = t(scenario.titleKey, {
            defaultValue: scenario.titleFallback,
          });
          const desc = t(scenario.descKey, {
            defaultValue: scenario.descFallback,
          });
          return (
            <button
              key={scenario.key}
              type="button"
              disabled={!ready}
              onClick={() => handleScenario(scenario)}
              data-scan-scenario={scenario.key}
              className={cn(
                "prompt-accent group relative w-full overflow-hidden rounded-xl border border-border/60 bg-card p-4 text-left transition-all duration-300",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
                ready
                  ? "hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_10px_30px_-20px_hsl(var(--primary)/0.32)] motion-reduce:transition-none motion-reduce:hover:translate-y-0"
                  : "cursor-not-allowed opacity-50",
              )}
            >
              <div className="relative flex items-start gap-3">
                <span
                  className={cn(
                    "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-transform duration-300",
                    scenario.iconBgClass,
                    ready &&
                      "group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100",
                  )}
                >
                  <Icon className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                    <span className="truncate">{title}</span>
                    <ArrowUpRight className="h-3.5 w-3.5 shrink-0 -translate-x-1 text-primary opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100 motion-reduce:transition-none" />
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground group-hover:text-muted-foreground/90">
                    {desc}
                  </p>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {!ready && (
        <p className="mt-3 text-center text-xs text-muted-foreground/60">
          {t("home.scan.target.required", {
            defaultValue: "请先输入扫描目标，再选择场景",
          })}
        </p>
      )}
    </section>
  );
}

export default ScanQuickStart;
