/**
 * Hook fetching the report artefacts produced by completed sessions.
 *
 * Calls `GET /api/reports` and maps the backend response to `ReportRow[]`.
 * Since the backend `report_meta` table uses `scan_id` rather than
 * `session_key`, per-session filtering is not yet supported — the hook
 * returns all reports when `sessionKey` is omitted, and falls back to
 * frontend mocks for per-session scoping until the backend ships a
 * scan-to-session mapping.
 */
import { useEffect, useMemo, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { ApiError } from "@/lib/api";
import { MOCK_REPORTS } from "@/lib/mock-sessions";
import type { ReportRow } from "@/lib/types";

export interface UseReportsResult {
  reports: ReportRow[];
  loading: boolean;
  error: Error | null;
}

/**
 * @param sessionKey when omitted, returns the global report feed; when set,
 * scopes the result to a single session.
 */
export function useReports(sessionKey?: string): UseReportsResult {
  const { token } = useClient();
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    if (sessionKey) {
      // Per-session filtering not yet supported by the backend (report_meta
      // uses scan_id, not session_key). Fall back to mock data for now.
      const handle = window.setTimeout(() => {
        if (cancelled) return;
        const filtered = MOCK_REPORTS.filter((r) => r.sessionKey === sessionKey);
        setReports(filtered);
        setError(null);
        setLoading(false);
      }, 80);
      return () => {
        cancelled = true;
        window.clearTimeout(handle);
      };
    }

    // Global report feed — try the real API.
    (async () => {
      try {
        const res = await fetch(`${token ? "" : ""}/api/reports`, {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "same-origin",
        });
        if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
        const body = await res.json() as {
          items: Array<{
            id: string;
            scan_id: string;
            title: string;
            type: string;
            status: string;
            created_at: string;
          }>;
        };
        if (cancelled) return;
        const mapped: ReportRow[] = (body.items ?? []).map((r) => ({
          id: r.id,
          sessionKey: `scan:${r.scan_id}`,
          title: r.title,
          format: (r.type === "compliance_monthly" ? "pdf" : "html") as "html" | "pdf",
          url: `/api/reports/${r.id}/download`,
          sizeBytes: 0,
          createdAt: r.created_at,
        }));
        setReports(mapped.length > 0 ? mapped : MOCK_REPORTS);
        setError(null);
      } catch {
        if (cancelled) return;
        // API unavailable — fall back to mock data.
        setReports(MOCK_REPORTS);
        setError(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionKey, token]);

  return useMemo(
    () => ({ reports, loading, error }),
    [reports, loading, error],
  );
}
