/**
 * Hook fetching the structured session list rendered on `/sessions`.
 *
 * Calls `GET /api/sessions` and maps the backend snake_case response to
 * the frontend `SessionRow` camelCase type via `fetchSessionRows`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { ApiError, fetchSessionRows } from "@/lib/api";
import type { SessionRow } from "@/lib/types";

export interface UseSessionsListResult {
  sessions: SessionRow[];
  loading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useSessionsList(): UseSessionsListResult {
  const { token } = useClient();
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const tokenRef = useMemo(() => ({ current: token }), [token]);
  tokenRef.current = token;

  const doFetch = useCallback(async () => {
    let cancelled = false;
    setLoading(true);
    try {
      const rows = await fetchSessionRows(tokenRef.current);
      if (!cancelled) {
        setSessions(rows);
        setError(null);
      }
    } catch (e) {
      if (cancelled) return;
      if (e instanceof ApiError && e.status === 401) {
        // Token expired — the api layer will auto-refresh; retry on next cycle.
        setSessions([]);
      } else {
        setError(e instanceof Error ? e : new Error(String(e)));
      }
    } finally {
      if (!cancelled) setLoading(false);
    }
    return () => { cancelled = true; };
  }, [tokenRef]);

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    doFetch().then((c) => { cleanup = c; });
    return () => { cleanup?.(); };
  }, [doFetch, refreshKey]);

  return useMemo(
    () => ({
      sessions,
      loading,
      error,
      refresh: () => setRefreshKey((n) => n + 1),
    }),
    [sessions, loading, error],
  );
}
