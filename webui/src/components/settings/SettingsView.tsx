import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, Eye, EyeOff, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchSettings, updateSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { SettingsPayload, SettingsUpdate } from "@/lib/types";

interface SettingsViewProps {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onBackToChat: () => void;
  onModelNameChange: (modelName: string | null) => void;
  onLogout?: () => void;
}

export function SettingsView({
  onBackToChat,
  onModelNameChange,
  onLogout,
}: SettingsViewProps) {
  const { token } = useClient();
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    model: "",
    provider: "auto",
    api_base: "",
  });
  /**
   * API Key input is tri-state to match the backend contract:
   * - ``apiKeyDirty=false`` → field omitted in update (keep existing key).
   * - ``apiKeyDirty=true``  → `apiKeyInput` is sent verbatim; empty string
   *   clears the stored key. This mirrors the ``X-Settings-Api-Key`` header
   *   semantics (absent / empty / value).
   */
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  const applyPayload = useCallback((payload: SettingsPayload) => {
    setSettings(payload);
    setForm({
      model: payload.agent.model,
      provider: payload.agent.provider,
      api_base: payload.custom.api_base,
    });
    // Server never returns the plaintext key — reset local draft state so the
    // input shows the masked placeholder again.
    setApiKeyInput("");
    setApiKeyDirty(false);
    setShowApiKey(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) {
          applyPayload(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyPayload, token]);

  const dirty = useMemo(() => {
    if (!settings) return false;
    return (
      form.model !== settings.agent.model ||
      form.provider !== settings.agent.provider ||
      form.api_base !== settings.custom.api_base ||
      apiKeyDirty
    );
  }, [form, settings, apiKeyDirty]);

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      const update: SettingsUpdate = {
        model: form.model,
        provider: form.provider,
        api_base: form.api_base,
      };
      // Only include ``api_key`` when the user explicitly touched the field,
      // so a round-trip that only edits (e.g.) the model never rewrites the
      // saved key.
      if (apiKeyDirty) update.api_key = apiKeyInput;
      const payload = await updateSettings(token, update);
      applyPayload(payload);
      onModelNameChange(payload.agent.model || null);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-background">
      <main className="mx-auto w-full max-w-[1000px] px-6 py-6">
        <button
          type="button"
          onClick={onBackToChat}
          className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Back to chat
        </button>

        <h1 className="mb-6 text-base font-semibold tracking-tight">General</h1>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading settings...
          </div>
        ) : error ? (
          <SettingsGroup>
            <SettingsRow title="Could not load settings">
              <span className="max-w-[520px] text-sm text-muted-foreground">{error}</span>
            </SettingsRow>
          </SettingsGroup>
        ) : settings ? (
          <SettingsSection
            form={form}
            setForm={setForm}
            settings={settings}
            dirty={dirty}
            saving={saving}
            apiKeyInput={apiKeyInput}
            apiKeyDirty={apiKeyDirty}
            showApiKey={showApiKey}
            onApiKeyChange={(value) => {
              setApiKeyInput(value);
              setApiKeyDirty(true);
            }}
            onToggleShowApiKey={() => setShowApiKey((prev) => !prev)}
            onSave={save}
            onLogout={onLogout}
          />
        ) : null}
      </main>
    </div>
  );
}

interface SettingsForm {
  model: string;
  provider: string;
  api_base: string;
}

function SettingsSection({
  form,
  setForm,
  settings,
  dirty,
  saving,
  apiKeyInput,
  apiKeyDirty,
  showApiKey,
  onApiKeyChange,
  onToggleShowApiKey,
  onSave,
  onLogout,
}: {
  form: SettingsForm;
  setForm: React.Dispatch<React.SetStateAction<SettingsForm>>;
  settings: SettingsPayload;
  dirty: boolean;
  saving: boolean;
  apiKeyInput: string;
  apiKeyDirty: boolean;
  showApiKey: boolean;
  onApiKeyChange: (value: string) => void;
  onToggleShowApiKey: () => void;
  onSave: () => void;
  onLogout?: () => void;
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
              onChange={(event) => setForm((prev) => ({ ...prev, provider: event.target.value }))}
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
            <Input
              value={form.model}
              onChange={(event) => setForm((prev) => ({ ...prev, model: event.target.value }))}
              className="h-8 w-[280px]"
            />
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
                      : settings.custom.api_key_masked || "sk-..."
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

          {!apiKeyDirty && settings.custom.has_api_key ? (
            <SettingsRow title="">
              <span className="text-xs text-muted-foreground">
                A key is already saved. Leave blank to keep it; type a new value to replace; clear and save to remove.
              </span>
            </SettingsRow>
          ) : null}

          {(dirty || saving) ? (
            <SettingsFooter
              dirty={dirty}
              saving={saving}
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
          <h2 className="mb-2 px-2 text-xs font-medium text-muted-foreground">{t("app.account.section")}</h2>
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

function SettingsGroup({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card/80">
      <div className="divide-y divide-border/50">{children}</div>
    </div>
  );
}

function SettingsRow({
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

function SettingsFooter({
  dirty,
  saving,
  saved,
  onSave,
}: {
  dirty: boolean;
  saving: boolean;
  saved: boolean;
  onSave: () => void;
}) {
  return (
    <div className="flex min-h-[52px] items-center justify-between gap-4 px-3 py-2.5">
      <div className="text-sm text-muted-foreground">
        {saved ? "Saved." : "Unsaved changes."}
      </div>
      <Button size="sm" variant="outline" onClick={onSave} disabled={!dirty || saving}>
        {saving ? "Saving" : "Save"}
      </Button>
    </div>
  );
}
