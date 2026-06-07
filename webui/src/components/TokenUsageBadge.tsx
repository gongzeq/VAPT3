import { Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { CumulativeUsage, TurnUsage } from "@/lib/types";

/** Format a token count for compact display (e.g. 1234 → "1.2k", 500 → "500"). */
function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/**
 * Compact inline badge showing per-turn token consumption with cache info.
 * Renders next to the copy button on assistant messages.
 */
export function TurnUsageBadge({ usage }: { usage: TurnUsage }) {
  const { t } = useTranslation();
  const promptTokens = usage.prompt_tokens || 0;
  const completionTokens = usage.completion_tokens || 0;
  const cachedTokens = usage.cached_tokens || 0;

  const cachePercent = promptTokens > 0
    ? Math.round((cachedTokens / promptTokens) * 100)
    : 0;
  const isCacheHit = cachePercent > 50;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
        "font-mono text-[10px] leading-tight",
        "bg-muted/60 text-muted-foreground",
      )}
      title={t("tokenUsage.turnTooltip", {
        defaultValue: `输入: ${promptTokens} tokens, 输出: ${completionTokens} tokens, 缓存: ${cachedTokens} tokens (${cachePercent}%)`,
      })}
    >
      <Zap className="h-2.5 w-2.5" aria-hidden />
      <span>↓{fmtTokens(promptTokens)}</span>
      <span className="text-muted-foreground/50">↑{fmtTokens(completionTokens)}</span>
      {cachedTokens > 0 && (
        <span
          className={cn(
            "ml-0.5 rounded px-1 text-[9px] font-medium",
            isCacheHit
              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
              : "bg-amber-500/15 text-amber-600 dark:text-amber-400",
          )}
        >
          {isCacheHit ? "HIT" : "MISS"} {cachePercent}%
        </span>
      )}
    </span>
  );
}

/**
 * Summary bar showing cumulative token usage across all turns in the
 * current conversation. Rendered as a subtle footer above the composer.
 */
export function CumulativeUsageBar({ usage }: { usage: CumulativeUsage }) {
  const { t } = useTranslation();
  if (usage.turnCount === 0) return null;

  const cachePercent = usage.promptTokens > 0
    ? Math.round((usage.cachedTokens / usage.promptTokens) * 100)
    : 0;
  const totalTokens = usage.promptTokens + usage.completionTokens;

  return (
    <div
      className={cn(
        "flex items-center justify-center gap-3 py-1.5",
        "font-mono text-[11px] text-muted-foreground/70",
      )}
      aria-label={t("tokenUsage.cumulativeAriaLabel", {
        defaultValue: `累计消耗: ${totalTokens} tokens`,
      })}
    >
      <span className="flex items-center gap-1">
        <Zap className="h-3 w-3" aria-hidden />
        {t("tokenUsage.cumulativeLabel", { defaultValue: "本次会话" })}
      </span>
      <span>
        ↓{fmtTokens(usage.promptTokens)} ↑{fmtTokens(usage.completionTokens)}
      </span>
      <span className="text-muted-foreground/50">
        = {fmtTokens(totalTokens)}
      </span>
      {usage.cachedTokens > 0 && (
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-medium",
            cachePercent > 50
              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "bg-amber-500/10 text-amber-600 dark:text-amber-400",
          )}
        >
          Cache {cachePercent > 50 ? "HIT" : "MISS"} {cachePercent}%
        </span>
      )}
      <span className="text-muted-foreground/40">
        {usage.turnCount} {t("tokenUsage.turns", { defaultValue: "轮" })}
      </span>
    </div>
  );
}
