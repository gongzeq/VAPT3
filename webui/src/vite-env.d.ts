/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * One-shot rollback flag for the UI/UX template refactor (task 05-09).
   *
   * - "true"  → mount BrowserRouter with the new 5-route surface
   *             (LoginPage / HomePage / DashboardPage / TaskDetailPage /
   *             SettingsPage) — the target shell for PR3+.
   * - unset / anything else → keep the legacy in-app view switching
   *             (loading → auth → Shell with chat ↔ settings toggle).
   *
   * Defaults to "true" in PR3 so the new routing is on by default; flipping
   * to "false" provides a clean rollback path during the refactor without
   * deleting any legacy code.
   */
  readonly VITE_UIUX_TEMPLATE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
