import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
} from "react-router-dom";
import { AuthForm } from "@/components/AuthForm";
import { preloadMarkdownText } from "@/components/MarkdownText";
import { ProtectedRoute, type BootStatus } from "@/components/ProtectedRoute";
import { Shell } from "@/components/Shell";
import { ClientProvider } from "@/providers/ClientProvider";
import {
  clearSavedSecret,
  deriveWorkflowApiBase,
  deriveWsUrl,
  fetchBootstrap,
  loadSavedSecret,
  saveSecret,
} from "@/lib/bootstrap";
import { SecbotClient } from "@/lib/secbot-client";
import { DashboardPage } from "@/pages/DashboardPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { WorkflowListPage } from "@/pages/WorkflowListPage";
import { WorkflowDetailPage } from "@/pages/WorkflowDetailPage";
import { WORKFLOW_BUILDER_ENABLED } from "@/lib/workflow-client";

/**
 * Default to ON so the refactor lands behind a default-true flag — flipping
 * `VITE_UIUX_TEMPLATE=false` at build time restores the legacy in-app view
 * switching for an emergency rollback without touching code.
 */
const TEMPLATE_ENABLED =
  (import.meta.env.VITE_UIUX_TEMPLATE ?? "true").toLowerCase() !== "false";

function GlobalLoading() {
  const { t } = useTranslation();
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="flex flex-col items-center gap-3 animate-in fade-in-0 duration-300">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/60" />
          </span>
          {t("app.loading.connecting")}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<BootStatus>({ status: "loading" });

  const bootstrapWithSecret = useCallback((secret: string) => {
    let cancelled = false;
    (async () => {
      setState({ status: "loading" });
      try {
        const boot = await fetchBootstrap("", secret);
        if (cancelled) return;
        if (secret) saveSecret(secret);
        const url = deriveWsUrl(boot.ws_path, boot.token);
        const client = new SecbotClient({
          url,
          onReauth: async () => {
            try {
              const refreshed = await fetchBootstrap("", secret);
              return deriveWsUrl(refreshed.ws_path, refreshed.token);
            } catch {
              return null;
            }
          },
        });
        client.connect();
        setState({
          status: "ready",
          client,
          token: boot.token,
          modelName: boot.model_name ?? null,
          workflowApiBase: deriveWorkflowApiBase(boot.workflow_api_port),
        });
      } catch (e) {
        if (cancelled) return;
        const msg = (e as Error).message;
        if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
          // 401/403 is the normal "not logged in" path, not a fatal error
          // — show the auth form so the user can enter the shared secret.
          setState({ status: "auth", failed: true });
        } else {
          // Per project rule: surface every other error as an alert
          // instead of flipping to an error-only page.
          window.alert(`Connection failed: ${msg}`);
          setState({ status: "auth" });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const saved = loadSavedSecret();
    return bootstrapWithSecret(saved);
  }, [bootstrapWithSecret]);

  useEffect(() => {
    const warm = () => preloadMarkdownText();
    const win = globalThis as typeof globalThis & {
      requestIdleCallback?: (
        callback: IdleRequestCallback,
        options?: IdleRequestOptions,
      ) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (typeof win.requestIdleCallback === "function") {
      const id = win.requestIdleCallback(warm, { timeout: 1500 });
      return () => win.cancelIdleCallback?.(id);
    }
    const id = globalThis.setTimeout(warm, 250);
    return () => globalThis.clearTimeout(id);
  }, []);

  // NOTE: both handlers MUST be memoised AND declared before any early
  // ``return`` so React's hook order stays stable across renders.
  const handleModelNameChange = useCallback((modelName: string | null) => {
    setState((current) =>
      current.status === "ready" ? { ...current, modelName } : current,
    );
  }, []);

  // ``state`` captured via ref so handleLogout has no reactive deps.
  const stateRef = useRef(state);
  stateRef.current = state;
  const handleLogout = useCallback(() => {
    const snap = stateRef.current;
    if (snap.status === "ready") {
      snap.client.close();
    }
    clearSavedSecret();
    setState({ status: "auth" });
  }, []);

  // ── Legacy code path ────────────────────────────────────────────────
  // VITE_UIUX_TEMPLATE=false → keep the original in-place view switching.
  if (!TEMPLATE_ENABLED) {
    if (state.status === "loading") return <GlobalLoading />;
    if (state.status === "auth") {
      return (
        <div className="flex h-full w-full items-center justify-center px-6">
          <AuthForm
            failed={!!state.failed}
            onSecret={(s) => bootstrapWithSecret(s)}
          />
        </div>
      );
    }
    return (
      <ClientProvider
        client={state.client}
        token={state.token}
        modelName={state.modelName}
        workflowApiBase={state.workflowApiBase}
      >
        <Shell
          onModelNameChange={handleModelNameChange}
          onLogout={handleLogout}
        />
      </ClientProvider>
    );
  }

  // ── Template-mode router path ───────────────────────────────────────
  // Loading is owned at App level so neither LoginPage nor protected pages
  // ever flash before bootstrap has resolved.
  if (state.status === "loading") return <GlobalLoading />;

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={<LoginPage state={state} onSecret={bootstrapWithSecret} />}
        />

        <Route
          element={
            <ProtectedRoute state={state} loadingFallback={<GlobalLoading />} />
          }
        >
          <Route
            element={
              state.status === "ready" ? (
                <ClientProvider
                  client={state.client}
                  token={state.token}
                  modelName={state.modelName}
                  workflowApiBase={state.workflowApiBase}
                >
                  <Outlet />
                </ClientProvider>
              ) : null
            }
          >
            <Route
              index
              element={
                <HomePage
                  onModelNameChange={handleModelNameChange}
                  onLogout={handleLogout}
                />
              }
            />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            {WORKFLOW_BUILDER_ENABLED && (
              <>
                <Route path="/workflows" element={<WorkflowListPage />} />
                <Route
                  path="/workflows/:id"
                  element={<WorkflowDetailPage />}
                />
              </>
            )}
            <Route
              path="/settings"
              element={
                <SettingsPage
                  onModelNameChange={handleModelNameChange}
                  onLogout={handleLogout}
                />
              }
            />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
