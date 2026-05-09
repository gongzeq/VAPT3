import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { SecbotClient } from "@/lib/secbot-client";

/**
 * Bootstrapping state shared across the App. Lifted out of App.tsx so that
 * <ProtectedRoute> can reason about it without re-reading the bootstrap
 * secret. The "loading" state is intentionally treated as "not authenticated
 * yet" so the route guard never flashes protected content before the secret
 * has been validated against the gateway.
 */
export type BootStatus =
  | { status: "loading" }
  | { status: "auth"; failed?: boolean }
  | {
      status: "ready";
      client: SecbotClient;
      token: string;
      modelName: string | null;
    };

export interface ProtectedRouteProps {
  state: BootStatus;
  /**
   * Optional fallback shown while bootstrap is still in flight. When the
   * caller does not provide one we render `null` to avoid a flash of unrelated
   * content; the parent App layout is responsible for the global spinner.
   */
  loadingFallback?: React.ReactNode;
}

/**
 * Route guard that mirrors the existing bootstrap-secret flow:
 *
 *   - "loading" → render the loading fallback (parent App owns the spinner)
 *   - "auth"    → redirect to /login while preserving `?next=` so the user
 *                 returns to the originally requested URL after sign-in
 *   - "ready"   → render the protected outlet
 *
 * No new auth surface is introduced; this is purely a wrapper around the
 * single boot state owned by App.tsx.
 */
export function ProtectedRoute({ state, loadingFallback = null }: ProtectedRouteProps) {
  const location = useLocation();

  if (state.status === "loading") {
    return <>{loadingFallback}</>;
  }

  if (state.status !== "ready") {
    const next = `${location.pathname}${location.search}`;
    const target =
      next && next !== "/login"
        ? `/login?next=${encodeURIComponent(next)}`
        : "/login";
    return <Navigate to={target} replace />;
  }

  return <Outlet />;
}

export default ProtectedRoute;
