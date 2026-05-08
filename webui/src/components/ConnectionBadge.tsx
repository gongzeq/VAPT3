import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { ConnectionStatus } from "@/lib/types";

// PR3-R4 (05-07-ocean-tech-frontend): map status → semantic state tokens
// defined in theme-tokens.md §3.5. `open` borrows --success with a brand-
// light glow halo; `error` borrows --error. Keeping the palette as CSS
// vars keeps light/dark modes honest.
const COPY: Record<ConnectionStatus, { color: string; glow: string }> = {
  idle: { color: "text-muted-foreground", glow: "" },
  connecting: {
    color: "text-[hsl(var(--warning))]",
    glow: "shadow-[0_0_6px_hsl(var(--warning)/0.35)]",
  },
  open: {
    color: "text-[hsl(var(--success))]",
    glow: "shadow-[0_0_8px_hsl(var(--success)/0.45)]",
  },
  reconnecting: {
    color: "text-[hsl(var(--warning))]",
    glow: "shadow-[0_0_6px_hsl(var(--warning)/0.35)]",
  },
  closed: {
    color: "text-muted-foreground",
    glow: "",
  },
  error: {
    color: "text-[hsl(var(--error))]",
    glow: "shadow-[0_0_8px_hsl(var(--error)/0.45)]",
  },
};

export function ConnectionBadge() {
  const { t } = useTranslation();
  const { client } = useClient();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);

  useEffect(() => client.onStatus(setStatus), [client]);

  const meta = COPY[status];
  const pulsing =
    status === "connecting" ||
    status === "reconnecting" ||
    status === "error";
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-[11px] font-medium transition-colors",
        meta.color,
      )}
      aria-live="polite"
    >
      <span className="relative flex h-1.5 w-1.5" aria-hidden>
        {pulsing && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75 motion-reduce:hidden" />
        )}
        <span
          className={cn(
            "relative inline-flex h-1.5 w-1.5 rounded-full bg-current",
            // Brand-aware glow halo for active states (PR3-R4); falls back
            // to no-op when `glow` is empty so idle/closed stay neutral.
            meta.glow,
          )}
        />
      </span>
      {t(`connection.${status}`)}
    </span>
  );
}
