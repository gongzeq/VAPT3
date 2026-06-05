import { AlertTriangle, WifiOff, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { StreamError } from "@/lib/secbot-client";

interface StreamErrorNoticeProps {
  error: StreamError;
  onDismiss: () => void;
}

/**
 * Dismissible banner that surfaces transport-level faults the user needs to
 * know about. Rendered above the composer so the message the fault referred
 * to remains in view just above. ``role="alert"`` + ``aria-live="assertive"``
 * ensures screen readers announce the failure.
 */
export function StreamErrorNotice({ error, onDismiss }: StreamErrorNoticeProps) {
  const { t } = useTranslation();

  const { title, body, Icon } = resolveCopy(error, t);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "mb-2 flex items-start gap-2 rounded-lg border",
        error.kind === "llm_retry"
          ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
          : "border-destructive/30 bg-destructive/10 text-destructive",
        "px-3 py-2 text-[12px] leading-5",
        "animate-in fade-in-0 slide-in-from-bottom-1",
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 h-4 w-4 shrink-0",
          error.kind === "llm_retry" ? "text-amber-400" : "",
        )}
        aria-hidden
      />
      <div className="flex-1">
        <p className="font-medium">{title}</p>
        <p className={cn(
          "mt-0.5",
          error.kind === "llm_retry" ? "text-amber-300/80" : "text-destructive/80",
        )}>{body}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onDismiss}
        aria-label={t("common.dismiss")}
        className={cn(
          "h-6 w-6 shrink-0 hover:bg-destructive/15",
          error.kind === "llm_retry"
            ? "text-amber-400 hover:text-amber-300 hover:bg-amber-500/15"
            : "text-destructive hover:text-destructive",
        )}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function resolveCopy(
  error: StreamError,
  t: (key: string) => string,
): { title: string; body: string; Icon: typeof AlertTriangle } {
  switch (error.kind) {
    case "message_too_big":
      return {
        title: t("errors.messageTooBig.title"),
        body: t("errors.messageTooBig.body"),
        Icon: AlertTriangle,
      };
    case "llm_retry": {
      const attempt = error.attempt;
      const delaySec = error.delaySec;
      const delayLabel = delaySec != null
        ? (delaySec >= 60 ? `${Math.round(delaySec / 60)} 分钟` : `${delaySec} 秒`)
        : null;
      return {
        title: "模型连接中断，正在重试…",
        body: attempt != null && delayLabel
          ? `第 ${attempt} 次重试，将在 ${delayLabel} 后重新连接`
          : attempt != null
            ? `第 ${attempt} 次重试中…`
            : "正在尝试重新连接模型服务…",
        Icon: WifiOff,
      };
    }
    default: {
      // Exhaustiveness guard: if a new StreamError kind is added, TS will
      // complain here until we add a corresponding i18n branch.
      const _exhaustive: never = error;
      return { title: String(_exhaustive), body: "", Icon: AlertTriangle };
    }
  }
}
