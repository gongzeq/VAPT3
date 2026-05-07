/**
 * Lightweight typed wrappers around secbot's REST endpoints.
 * The backend exposes:
 *   GET /api/assets?actor_id=...
 *   GET /api/scans?actor_id=...&limit=50
 *   GET /api/scans/:scan_id
 *   GET /api/scans/:scan_id/report.{md,pdf,docx}
 *   GET /api/reports?actor_id=...
 */

export interface Asset {
  id: string;
  ip: string;
  hostname?: string;
  os?: string;
  tags?: string[];
  service_count?: number;
  vuln_count?: number;
  severity_max?: "critical" | "high" | "medium" | "low" | "info" | null;
  last_seen?: string;
}

export interface ScanRecord {
  id: string;
  status: "running" | "succeeded" | "failed" | "cancelled";
  started_at: string;
  finished_at?: string;
  agent: string;
  steps: number;
  totals: { assets: number; vulnerabilities: number };
  severity_counts: Partial<Record<"critical" | "high" | "medium" | "low" | "info", number>>;
}

export interface ReportRecord {
  scan_id: string;
  format: "markdown" | "pdf" | "docx";
  download_url: string;
  generated_at: string;
  size_bytes?: number;
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return (await res.json()) as T;
}

export const secbotApi = {
  listAssets: () => fetchJson<Asset[]>("/api/assets"),
  listScans: (limit = 50) => fetchJson<ScanRecord[]>(`/api/scans?limit=${limit}`),
  getScan: (scanId: string) => fetchJson<ScanRecord>(`/api/scans/${scanId}`),
  listReports: () => fetchJson<ReportRecord[]>("/api/reports"),
};
