/**
 * REST client for the phishing-email dashboard surface (PRD §R6).
 *
 * The 6 endpoints are read-only views over ``detection_results.db`` written
 * by the phishing workflow's step3 script. Backend handlers swallow
 * missing-DB / sqlite errors into empty payloads, so callers only need to
 * defend against transport-level failures (network / 5xx).
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

export interface PhishingSparkPoint {
  date: string; // ``YYYY-MM-DD``
  phishing: number;
}

export interface PhishingSummary {
  today_phishing: number;
  today_total: number;
  cache_hit_rate: number; // 0..1
  avg_duration_ms: number;
  spark_7d: PhishingSparkPoint[];
  generated_at: string;
}

export interface PhishingStatsDelta {
  today_total_pct: number;
  today_phishing: number;
  cache_hit_pct: number;
  avg_duration_ms: number;
}

export interface PhishingStats {
  today_total: number;
  today_phishing: number;
  today_phishing_rate: number; // 0..1
  cache_hit_rate: number; // 0..1
  avg_duration_ms: number;
  delta: PhishingStatsDelta;
  generated_at: string;
}

export type PhishingFilter = "all" | "phishing" | "suspicious" | "normal";

export interface PhishingHistoryItem {
  id: number;
  content_hash: string;
  sender: string;
  subject: string;
  is_phishing: boolean;
  confidence: number; // 0..1
  reason: string;
  action: string;
  created_at: string;
  processed_time_ms: number;
}

export interface PhishingHistoryPage {
  items: PhishingHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface PhishingTrendBucket {
  date: string;
  phishing: number;
  suspicious: number;
  normal: number;
  rate: number;
}

export interface PhishingTrend {
  buckets: PhishingTrendBucket[];
}

export interface PhishingTopSenderItem {
  sender: string;
  phishing: number;
  max_confidence: number;
  last_seen: string;
}

export interface PhishingTopSenders {
  items: PhishingTopSenderItem[];
  limit: number;
  days: number;
}

export type PhishingHealthStatus = "ok" | "running" | "slow" | "down" | string;

export interface PhishingHealthComponent {
  name: string;
  status: PhishingHealthStatus;
  detail?: string;
}

export interface PhishingHealth {
  components: PhishingHealthComponent[];
  generated_at?: string;
}

// ── Fetchers ────────────────────────────────────────────────────────────

export async function fetchPhishingSummary(
  token: string,
  base: string = "",
): Promise<PhishingSummary> {
  return request<PhishingSummary>(
    `${base}/api/dashboard/phishing/summary`,
    token,
  );
}

export async function fetchPhishingStats(
  token: string,
  base: string = "",
): Promise<PhishingStats> {
  return request<PhishingStats>(`${base}/api/dashboard/phishing/stats`, token);
}

export interface FetchPhishingHistoryOptions {
  page?: number;
  pageSize?: number;
  search?: string;
  filter?: PhishingFilter;
}

export async function fetchPhishingHistory(
  token: string,
  options: FetchPhishingHistoryOptions = {},
  base: string = "",
): Promise<PhishingHistoryPage> {
  const query = new URLSearchParams();
  if (options.page !== undefined) query.set("page", String(options.page));
  if (options.pageSize !== undefined)
    query.set("page_size", String(options.pageSize));
  if (options.search) query.set("search", options.search);
  if (options.filter) query.set("filter", options.filter);
  const qs = query.toString();
  return request<PhishingHistoryPage>(
    `${base}/api/dashboard/phishing/history${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function fetchPhishingTrend(
  token: string,
  range: "7d" | "30d" | "90d" = "7d",
  base: string = "",
): Promise<PhishingTrend> {
  return request<PhishingTrend>(
    `${base}/api/dashboard/phishing/trend?range=${range}`,
    token,
  );
}

export async function fetchPhishingTopSenders(
  token: string,
  options: { limit?: number; days?: number } = {},
  base: string = "",
): Promise<PhishingTopSenders> {
  const query = new URLSearchParams();
  if (options.limit !== undefined) query.set("limit", String(options.limit));
  if (options.days !== undefined) query.set("days", String(options.days));
  const qs = query.toString();
  return request<PhishingTopSenders>(
    `${base}/api/dashboard/phishing/top-senders${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function fetchPhishingHealth(
  token: string,
  base: string = "",
): Promise<PhishingHealth> {
  return request<PhishingHealth>(
    `${base}/api/dashboard/phishing/health`,
    token,
  );
}
