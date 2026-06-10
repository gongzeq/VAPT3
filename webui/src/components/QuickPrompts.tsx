import { useTranslation } from "react-i18next";
import { ArrowUpRight, Bug, FileText, Key, Radar, Zap, type LucideIcon } from "lucide-react";
import { dispatchComposerPrefill } from "@/components/PromptSuggestions";

interface PromptDef {
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

export interface QuickPromptsProps {
  className?: string;
}

/**
 * Standalone quick prompts component for the empty chat state.
 * Displays shortcut buttons that prefill the composer when clicked.
 */
export function QuickPrompts({ className }: QuickPromptsProps) {
  const { t } = useTranslation();
  return (
    <section className={className}>
      <header className="mb-4 flex items-center gap-2.5">
        <span className="icon-surface icon-surface-brand h-7 w-7 rounded-lg">
          <Zap className="h-4 w-4" />
        </span>
        <h4 className="text-sm font-semibold tracking-wide text-foreground">
          {t("home.prompts.title", { defaultValue: "快捷指令" })}
        </h4>
        <span
          aria-hidden
          className="ml-1 h-px flex-1 bg-gradient-to-r from-border/70 to-transparent"
        />
      </header>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
              className="prompt-accent group relative w-full overflow-hidden rounded-xl border border-border/60 bg-card p-4 text-left transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_10px_30px_-20px_hsl(var(--primary)/0.32)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
              onClick={() => dispatchComposerPrefill(prefill)}
            >
              <div className="relative flex items-start gap-3">
                <span className="icon-surface icon-surface-brand h-10 w-10 shrink-0 rounded-lg transition-transform duration-300 group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100">
                  <Icon className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                    <span className="truncate">{title}</span>
                    <ArrowUpRight className="h-3.5 w-3.5 shrink-0 -translate-x-1 text-primary opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100 motion-reduce:transition-none" />
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground group-hover:text-muted-foreground/90">
                    {subtitle}
                  </p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default QuickPrompts;
