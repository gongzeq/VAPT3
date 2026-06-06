import { useTranslation } from "react-i18next";
import {
  Bug,
  FileText,
  Key,
  Radar,
  Zap,
  type LucideIcon,
} from "lucide-react";
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
      <header className="mb-3 flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-lg bg-primary/10">
          <Zap className="h-3.5 w-3.5 text-primary" />
        </span>
        <h4 className="text-sm font-semibold">
          {t("home.prompts.title", { defaultValue: "快捷指令" })}
        </h4>
      </header>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
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
              className="prompt-accent card-hover-glow group w-full rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5 pl-4 text-left text-sm"
              onClick={() => dispatchComposerPrefill(prefill)}
            >
              <div className="flex items-center gap-2.5 font-medium text-foreground">
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-primary/10">
                  <Icon className="h-3.5 w-3.5 text-primary" />
                </span>
                {title}
              </div>
              <p className="mt-0.5 pl-[2.125rem] text-xs text-muted-foreground group-hover:text-muted-foreground/90">
                {subtitle}
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default QuickPrompts;
