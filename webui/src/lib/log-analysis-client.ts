/**
 * REST client for the log-analysis dashboard surface.
 *
 * The 2 endpoints are read-only views over the ``log_analysis`` table
 * in ``detection_results.db``, written by the log-analysis workflow's
 * step2 script.
 */

import { ApiError } from "./api";

async function request<T>(
  url: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(url, {
    ...(init ?? {}),
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
    credentials: "same-origin",
  });
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

// ── Types ───────────────────────────────────────────────────────────────

export interface SeverityDistribution {
  critical: number;
  high: number;
  medium: number;
  low: number;
  safe: number;
}

/** Payload from ``GET /api/dashboard/log-analysis/latest``. */
export interface LogAnalysisLatest {
  found: boolean;
  id: number;
  file_name: string;
  created_at: string;
  anomaly_count: number;
  total_entries: number;
  char_count: number;
  log_format: string;
  confidence: number; // 0..1
  reason: string;
  suggested_action: string;
  risk_factors: string[];
  severity_distribution: SeverityDistribution;
  summary: string; // brief text summary
}

/** Three-state status for a log-analysis record (PR1). */
export type LogAnalysisStatus = "alert" | "handled" | "normal";

export interface LogAnalysisHistoryItem {
  id: number;
  file_name: string;
  created_at: string;
  anomaly_count: number;
  total_entries: number;
  severity_distribution: SeverityDistribution;
  confidence: number;
  reason: string;
  suggested_action: string;
  risk_factors: string[];
  anomaly_entries: Array<{
    desc: string;
    severity: "critical" | "high" | "medium" | "low";
  }>;
  summary: string;
  char_count: number;
  log_format: string;
  /** Derived three-state status (alert/handled/normal). */
  status?: LogAnalysisStatus;
}

export interface LogAnalysisHistoryPage {
  items: LogAnalysisHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

// ── Fetchers ────────────────────────────────────────────────────────────

export async function fetchLogAnalysisLatest(
  token: string,
  base: string = "",
): Promise<LogAnalysisLatest> {
  return request<LogAnalysisLatest>(
    `${base}/api/dashboard/log-analysis/latest`,
    token,
  );
}

export async function fetchLogAnalysisHistory(
  token: string,
  options: { page?: number; pageSize?: number } = {},
  base: string = "",
): Promise<LogAnalysisHistoryPage> {
  const query = new URLSearchParams();
  if (options.page !== undefined) query.set("page", String(options.page));
  if (options.pageSize !== undefined)
    query.set("page_size", String(options.pageSize));
  const qs = query.toString();
  return request<LogAnalysisHistoryPage>(
    `${base}/api/dashboard/log-analysis/history${qs ? `?${qs}` : ""}`,
    token,
  );
}

/**
 * Mark a log-analysis record as handled (acknowledged).
 * Returns the server response with ``ok``, ``log_id``, ``handled_at``.
 */
export async function handleLogAnalysis(
  token: string,
  logId: number,
  base: string = "",
): Promise<{ ok: boolean; log_id: number; handled_at?: string }> {
  return request(
    `${base}/api/dashboard/log-analysis/${logId}/handle`,
    token,
  );
}

/**
 * Undo a previous handle action.
 */
export async function unhandleLogAnalysis(
  token: string,
  logId: number,
  base: string = "",
): Promise<{ ok: boolean; log_id: number }> {
  return request(
    `${base}/api/dashboard/log-analysis/${logId}/unhandle`,
    token,
  );
}
