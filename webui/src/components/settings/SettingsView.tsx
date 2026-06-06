import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchProviderModels, fetchSettings, updateSettings } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";
import type { SettingsPayload, SettingsUpdate } from "@/lib/types";
import { SettingsSection } from "@/components/settings/SettingsSection";

interface SettingsViewProps {
  onBackToChat: () => void;
  onModelNameChange: (modelName: string | null) => void;
  onLogout?: () => void;
}

/** @description Settings page with model configuration, API key management, and account controls. */
export function SettingsView({
  onBackToChat,
  onModelNameChange,
  onLogout,
}: SettingsViewProps) {
  const { token } = useClient();
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
  // "Fetch models" probe result + loading flag. Cleared whenever the
  // endpoint fields change so a stale list doesn't linger after the user
  // edits ``api_base`` or ``api_key``.
  const [availableModels, setAvailableModels] = useState<string[] | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  /**
   * Last error from :func:`fetchSettings`. We surface it *inside* the page
   * (alongside a Retry button) instead of flipping to an error-only view,
   * per the project rule "errors go through alert() only, never a page
   * switch". Without this the page would render as a blank panel after the
   * alert is dismissed (e.g. token expired after a gateway restart).
   */
  const [loadError, setLoadError] = useState<string | null>(null);

  const applyPayload = useCallback(
    (payload: SettingsPayload) => {
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
      setAvailableModels(null);
      // Keep the top-bar model label in sync with whatever the server
      // persisted (fixes the "configured DeepSeek but UI still shows Opus"
      // case when the settings page reloads from cache).
      onModelNameChange(payload.agent.model || null);
    },
    [onModelNameChange],
  );

  const loadSettings = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) applyPayload(payload);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = (err as Error).message;
        // Per project rule: surface the error through alert, never flip
        // to an error-only page. But we ALSO record ``loadError`` so the
        // body can render a retry affordance instead of a blank panel
        // after the user dismisses the alert.
        window.alert(`Could not load settings: ${msg}`);
        setLoadError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyPayload, token]);

  useEffect(() => loadSettings(), [loadSettings]);

  /**
   * Config for whichever provider is currently selected in the dropdown.
   * ``auto`` maps to the server-resolved active slot (``settings.custom``);
   * any named provider looks itself up in ``provider_configs`` so the UI
   * reflects that slot's saved values, not the active one.
   */
  const currentProviderCfg = useMemo(() => {
    if (!settings) return null;
    if (form.provider === "auto") return settings.custom;
    return settings.provider_configs?.[form.provider] ?? settings.custom;
  }, [settings, form.provider]);

  /**
   * Swap Base URL to the selected provider's saved value (or spec default)
   * and reset the API key draft so the input falls back to that provider's
   * masked placeholder. Without this, picking ``DeepSeek`` while the form
   * still shows ``https://api.openai.com/v1`` silently routed saves to the
   * wrong endpoint.
   */
  const onProviderChange = useCallback(
    (newProvider: string) => {
      setAvailableModels(null);
      setApiKeyInput("");
      setApiKeyDirty(false);
      setShowApiKey(false);
      setForm((prev) => {
        if (!settings) return { ...prev, provider: newProvider };
        const preset: {
          api_base: string;
          default_api_base?: string;
        } | null =
          newProvider === "auto"
            ? settings.custom
            : (settings.provider_configs?.[newProvider] ?? null);
        if (!preset) return { ...prev, provider: newProvider };
        // Prefer the user's saved ``api_base`` — fall back to the provider
        // spec's ``default_api_base`` so e.g. DeepSeek lands on
        // ``https://api.deepseek.com`` instead of a stale openai URL.
        const apiBase: string =
          preset.api_base || preset.default_api_base || "";
        return { ...prev, provider: newProvider, api_base: apiBase };
      });
    },
    [settings],
  );

  const trimmedModel = form.model.trim();
  const trimmedApiBase = form.api_base.trim();
  const trimmedApiKeyInput = apiKeyInput.trim();
  // Effective "has key" state: either the user is typing a fresh key or the
  // currently selected provider already has one saved.
  const hasEffectiveApiKey = apiKeyDirty
    ? trimmedApiKeyInput.length > 0
    : !!currentProviderCfg?.has_api_key;
  const allRequiredFilled =
    trimmedModel.length > 0 &&
    trimmedApiBase.length > 0 &&
    hasEffectiveApiKey;

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
    if (!allRequiredFilled) {
      window.alert(
        "Model, Base URL and API Key are all required before saving.",
      );
      return;
    }
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
    } catch (err) {
      window.alert(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleFetchModels = async () => {
    if (fetchingModels) return;
    if (!trimmedApiBase) {
      window.alert("Please enter the Base URL first.");
      return;
    }
    if (!hasEffectiveApiKey) {
      window.alert("Please enter the API Key first.");
      return;
    }
    setFetchingModels(true);
    try {
      // ``undefined`` tells the backend to fall back to the saved key so the
      // user doesn't have to re-enter an already-persisted one.
      const models = await fetchProviderModels(
        token,
        trimmedApiBase,
        apiKeyDirty ? apiKeyInput : undefined,
      );
      if (models.length === 0) {
        window.alert("Endpoint returned no models.");
        setAvailableModels([]);
        return;
      }
      setAvailableModels(models);
    } catch (err) {
      window.alert(`Fetch models failed: ${(err as Error).message}`);
    } finally {
      setFetchingModels(false);
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
        ) : loadError ? (
          <div className="flex flex-col items-start gap-3 rounded-xl border border-border/60 bg-card/80 p-4">
            <p className="text-sm">
              Could not load settings:{" "}
              <span className="font-mono text-xs">{loadError}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              Your session may have expired after a backend restart. Retry, or sign out to
              re-authenticate.
            </p>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={loadSettings}>
                Retry
              </Button>
              {onLogout ? (
                <Button size="sm" variant="outline" onClick={onLogout}>
                  Sign out
                </Button>
              ) : null}
            </div>
          </div>
        ) : settings ? (
          <SettingsSection
            form={form}
            setForm={setForm}
            settings={settings}
            currentProviderCfg={currentProviderCfg}
            onProviderChange={onProviderChange}
            dirty={dirty}
            saving={saving}
            canSave={allRequiredFilled}
            apiKeyInput={apiKeyInput}
            apiKeyDirty={apiKeyDirty}
            showApiKey={showApiKey}
            onApiKeyChange={(value) => {
              setApiKeyInput(value);
              setApiKeyDirty(true);
              setAvailableModels(null);
            }}
            onToggleShowApiKey={() => setShowApiKey((prev) => !prev)}
            onSave={save}
            onLogout={onLogout}
            availableModels={availableModels}
            fetchingModels={fetchingModels}
            onFetchModels={handleFetchModels}
          />
        ) : (
          // Fallback: neither loading nor errored, but settings is still
          // null. Should not happen in normal flow, but HMR / unmounted
          // effect race conditions can leave the state here. Render a
          // visible affordance instead of a blank panel so the user can
          // always recover.
          <div className="flex flex-col items-start gap-3 rounded-xl border border-border/60 bg-card/80 p-4">
            <p className="text-sm">Settings not loaded.</p>
            <Button size="sm" variant="outline" onClick={loadSettings}>
              Load settings
            </Button>
          </div>
        )}
      </main>
    </div>
  );
}
