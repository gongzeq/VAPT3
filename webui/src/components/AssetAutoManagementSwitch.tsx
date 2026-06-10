import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Database } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import {
  fetchAssetAutoManagement,
  setAssetAutoManagement,
} from "@/lib/api";

const LOCAL_DEFAULT_KEY = "secbot-webui.asset-auto-management-default";

function readLocalDefault(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(LOCAL_DEFAULT_KEY) === "1";
  } catch {
    return false;
  }
}

function writeLocalDefault(value: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LOCAL_DEFAULT_KEY, value ? "1" : "0");
  } catch {
    // ignore storage errors (private mode, quota, etc.)
  }
}

interface AssetAutoManagementSwitchProps {
  /** Backend session key to sync against. `null` means no session yet —
   * the toggle is then a *preview* default persisted in localStorage and
   * applied to whichever chat the user creates next. */
  historyKey: string | null;
  token: string;
  className?: string;
  /** Compact variant: renders inline without full-width container. */
  compact?: boolean;
}

/**
 * Small toggle deciding whether sub-agents auto-ingest discovered assets
 * into CMDB for the active chat. In the new UX it only renders inside the
 * Hero (`messages.length === 0`) because once the conversation is rolling
 * the value cannot be changed mid-flight (per backend contract).
 */
export function AssetAutoManagementSwitch({
  historyKey,
  token,
  className,
  compact = false,
}: AssetAutoManagementSwitchProps) {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState<boolean>(() => readLocalDefault());
  const [busy, setBusy] = useState(false);

  // When a chat key arrives (either user opened an existing session, or a
  // brand-new chat just got created), reconcile the live API state with the
  // local default. If the API has not been initialised yet, push the local
  // default up so the new chat starts with the user's preferred setting.
  useEffect(() => {
    if (!historyKey) return;
    let cancelled = false;
    const localDefault = readLocalDefault();
    fetchAssetAutoManagement(token, historyKey)
      .then((state) => {
        if (cancelled) return;
        const remote = Boolean(state.asset_auto_management);
        if (remote === localDefault) {
          setEnabled(remote);
          return;
        }
        // Remote state disagrees with the saved default — push local up
        // so the brand-new session inherits the user's choice.
        return setAssetAutoManagement(token, historyKey, localDefault).then(
          (synced) => {
            if (!cancelled) {
              setEnabled(Boolean(synced.asset_auto_management));
            }
          },
        );
      })
      .catch(() => {
        if (!cancelled) setEnabled(localDefault);
      });
    return () => {
      cancelled = true;
    };
  }, [historyKey, token]);

  const handleChange = useCallback(
    (next: boolean) => {
      if (busy) return;
      const previous = enabled;
      setEnabled(next);
      writeLocalDefault(next);
      if (!historyKey) {
        // No session yet — local-only persistence; will be applied via the
        // effect above as soon as `onCreateChat` resolves.
        return;
      }
      setBusy(true);
      setAssetAutoManagement(token, historyKey, next)
        .then((state) => {
          setEnabled(Boolean(state.asset_auto_management));
        })
        .catch(() => {
          setEnabled(previous);
          writeLocalDefault(previous);
        })
        .finally(() => setBusy(false));
    },
    [busy, enabled, historyKey, token],
  );

  const stateLabel = enabled
    ? t("home.assetAutoManagement.on", { defaultValue: "开启" })
    : t("home.assetAutoManagement.off", { defaultValue: "关闭" });

  return (
    <div
      className={
        compact
          ? `flex items-center gap-2 rounded-lg border border-border/70 bg-card/55 px-2.5 py-1.5 text-sm ${className ?? ""}`
          : `mx-auto flex w-full max-w-2xl items-center justify-between rounded-lg border border-border/70 bg-card/55 px-3 py-2 text-sm ${className ?? ""}`
      }
    >
      <div className="flex min-w-0 items-center gap-2">
        <Database className="h-4 w-4 shrink-0 text-primary" />
        <span className="truncate text-foreground">
          {t("home.assetAutoManagement.label", { defaultValue: "纳管资产" })}
        </span>
        <span className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
          {stateLabel}
        </span>
      </div>
      <Switch
        checked={enabled}
        disabled={busy}
        onCheckedChange={handleChange}
        aria-label={t("home.assetAutoManagement.label", { defaultValue: "纳管资产" })}
      />
    </div>
  );
}

export default AssetAutoManagementSwitch;
