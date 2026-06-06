/**
 * Settings form sub-components rendered inside `SettingsView`.
 *
 * Exports:
 * - `SettingsSection` — the full form layout (AI / endpoint / interface / account)
 * - `SettingsGroup` — card wrapper with vertical dividers
 * - `SettingsRow` — label + control row
 * - `SettingsFooter` — dirty-state hint + Save button
 * - `SettingsForm` — local form state interface
 */

import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { SettingsPayload } from "@/lib/types";

/** @description Local form state interface for the settings page. */
export interface SettingsForm {
  model: string;
  provider: string;
  api_base: string;
}

/** @description Full settings form layout with AI, endpoint, interface, and account sections. */
export function SettingsSection({
  form,
  setForm,
  settings,
  currentProviderCfg,
  onProviderChange,
  dirty,
  saving,
  canSave,
  apiKeyInput,
  apiKeyDirty,
  showApiKey,
  onApiKeyChange,
  onToggleShowApiKey,
  onSave,
  onLogout,
  availableModels,
  fetchingModels,
  onFetchModels,
}: {
  form: SettingsForm;
  setForm: React.Dispatch<React.SetStateAction<SettingsForm>>;
  settings: SettingsPayload;
  /** Snapshot of the provider the dropdown currently points at. */
  currentProviderCfg: {
    api_base: string;
    api_key_masked: string;
    has_api_key: boolean;
  } | null;
  /** Dropdown-change handler that swaps Base URL + resets api-key draft. */
  onProviderChange: (newProvider: string) => void;
  dirty: boolean;
  saving: boolean;
  /** Whether all required fields (model / api_base / api_key) are filled. */
  canSave: boolean;
  apiKeyInput: string;
  apiKeyDirty: boolean;
  showApiKey: boolean;
  onApiKeyChange: (value: string) => void;
  onToggleShowApiKey: () => void;
  onSave: () => void;
  onLogout?: () => void;
  availableModels: string[] | null;
  fetchingModels: boolean;
  onFetchModels: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-7">
      <section>
        <h2 className="mb-2 px-2 text-xs font-medium text-muted-foreground">AI</h2>
        <SettingsGroup>
          <SettingsRow title="Provider">
            <select
              value={form.provider}
              onChange={(event) => onProviderChange(event.target.value)}
              className={cn(
                "h-8 w-[210px] rounded-md border border-input bg-background px-2 text-sm",
                "outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
              )}
            >
              {settings.providers.map((provider) => (
                <option key={provider.name} value={provider.name}>
                  {provider.label}
                </option>
              ))}
            </select>
          </SettingsRow>

          <SettingsRow title="Model">
            <div className="flex flex-col items-end gap-1.5">
              <div className="flex items-center gap-1.5">
                <Input
                  value={form.model}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, model: event.target.value }))
                  }
                  className="h-8 w-[280px]"
                  list="settings-model-suggestions"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={onFetchModels}
                  disabled={fetchingModels}
                  className="h-8"
                >
                  {fetchingModels ? (
                    <span className="inline-flex items-center gap-1">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Fetching
                    </span>
                  ) : (
                    "Fetch models"
                  )}
                </Button>
              </div>
              {availableModels && availableModels.length > 0 ? (
                <>
                  <datalist id="settings-model-suggestions">
                    {availableModels.map((mid) => (
                      <option key={mid} value={mid} />
                    ))}
                  </datalist>
                  <div className="flex max-w-[420px] flex-wrap justify-end gap-1">
                    {availableModels.slice(0, 12).map((mid) => (
                      <button
                        key={mid}
                        type="button"
                        onClick={() => setForm((prev) => ({ ...prev, model: mid }))}
                        className={cn(
                          "rounded border border-border/60 bg-muted/40 px-1.5 py-0.5 text-xs text-muted-foreground",
                          "hover:bg-accent hover:text-foreground",
                          form.model === mid && "border-primary text-foreground",
                        )}
                      >
                        {mid}
                      </button>
                    ))}
                  </div>
                </>
              ) : null}
            </div>
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <h2 className="mb-2 px-2 text-xs font-medium text-muted-foreground">
          OpenAI-compatible endpoint
        </h2>
        <SettingsGroup>
          <SettingsRow title="Base URL">
            <Input
              value={form.api_base}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, api_base: event.target.value }))
              }
              placeholder="https://api.openai.com/v1"
              className="h-8 w-[320px]"
              spellCheck={false}
              autoComplete="off"
            />
          </SettingsRow>

          <SettingsRow title="API Key">
            <div className="flex items-center gap-1.5">
              <div className="relative">
                <Input
                  type={showApiKey ? "text" : "password"}
                  value={apiKeyInput}
                  onChange={(event) => onApiKeyChange(event.target.value)}
                  placeholder={
                    apiKeyDirty
                      ? ""
                      : currentProviderCfg?.api_key_masked || "sk-..."
                  }
                  className="h-8 w-[280px] pr-8"
                  spellCheck={false}
                  autoComplete="off"
                />
                <button
                  type="button"
                  onClick={onToggleShowApiKey}
                  tabIndex={-1}
                  aria-label={showApiKey ? "Hide API key" : "Show API key"}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
                >
                  {showApiKey ? (
                    <EyeOff className="h-3.5 w-3.5" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            </div>
          </SettingsRow>

          {!apiKeyDirty && currentProviderCfg?.has_api_key ? (
            <SettingsRow title="">
              <span className="text-xs text-muted-foreground">
                A key is already saved. Leave blank to keep it; type a new value to replace; clear and save to remove.
              </span>
            </SettingsRow>
          ) : null}

          {dirty || saving ? (
            <SettingsFooter
              dirty={dirty}
              saving={saving}
              canSave={canSave}
              saved={false}
              onSave={onSave}
            />
          ) : null}
        </SettingsGroup>
      </section>

      <section>
        <h2 className="mb-2 px-2 text-xs font-medium text-muted-foreground">Interface</h2>
        <SettingsGroup>
          <SettingsRow title="Language">
            <LanguageSwitcher />
          </SettingsRow>
        </SettingsGroup>
      </section>

      {onLogout && (
        <section>
          <h2 className="mb-2 px-2 text-xs font-medium text-muted-foreground">
            {t("app.account.section")}
          </h2>
          <SettingsGroup>
            <SettingsRow title={t("app.account.logoutHint")}>
              <Button size="sm" variant="outline" onClick={onLogout}>
                {t("app.account.logout")}
              </Button>
            </SettingsRow>
          </SettingsGroup>
        </section>
      )}
    </div>
  );
}

/** @description Card wrapper grouping settings rows with vertical dividers. */
export function SettingsGroup({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card/80">
      <div className="divide-y divide-border/50">{children}</div>
    </div>
  );
}

/** @description Single settings row with a label and optional control content. */
export function SettingsRow({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[52px] flex-col gap-3 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="text-sm font-medium leading-5">{title}</div>
      </div>
      {children ? <div className="shrink-0 sm:ml-6">{children}</div> : null}
    </div>
  );
}

/** @description Footer bar showing dirty-state hint and Save button. */
export function SettingsFooter({
  dirty,
  saving,
  canSave,
  saved,
  onSave,
}: {
  dirty: boolean;
  saving: boolean;
  /** When false, the Save button is disabled because required fields
   * (model / Base URL / API Key) are not all filled in. */
  canSave: boolean;
  saved: boolean;
  onSave: () => void;
}) {
  return (
    <div className="flex min-h-[52px] items-center justify-between gap-4 px-3 py-2.5">
      <div className="text-sm text-muted-foreground">
        {saved
          ? "Saved."
          : canSave
            ? "Unsaved changes."
            : "Model, Base URL and API Key are all required."}
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={onSave}
        disabled={!dirty || saving || !canSave}
      >
        {saving ? "Saving" : "Save"}
      </Button>
    </div>
  );
}
