/**
 * REST client for the Threat Intel module (PRD §6).
 *
 * All endpoints are under ``/api/threat-intel/``. Authentication uses the
 * shared Bearer token from ``useClient()``.  Types mirror the backend
 * response shapes defined in ``secbot/threat_intel/repo.py``.
 */

import { ApiError } from "./api";

// ── Helper ──────────────────────────────────────────────────────────────

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
      "Content-Type": "application/json",
    },
    credentials: "same-origin",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => `HTTP ${res.status}`);
    throw new ApiError(res.status, text);
  }
  return (await res.json()) as T;
}

// ── Types ───────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface OverviewData {
  freshness: {
    last_success_at: string | null;
    stale_sources: string[];
    failed_sources: string[];
  };
  watched_groups_activity: {
    total_watched: number;
    recent_activity_count: number;
    activities: WatchedActivity[];
  };
  high_severity_vulns: {
    total: number;
    new_last_7d: number;
    supply_chain_count: number;
    trend: string;
  };
  active_c2_ips: {
    total: number;
    by_group: { group_name: string; count: number }[];
  };
  maritime_events: {
    total: number;
    recent_count: number;
    latest: { title: string; event_date: string; severity: string } | null;
  };
  malware_activity: {
    total_families: number;
    recent_samples_7d: number;
    top_families: { family: string; group: string; sample_count: number }[];
  };
}

export interface WatchedActivity {
  group_id: string;
  group_name: string;
  activity_type: string;
  count: number;
  timestamp: string;
}

export interface ThreatGroupSummary {
  id: string;
  name: string;
  aliases: string[];
  description: string | null;
  origin_country: string | null;
  target_sectors: string[];
  mitre_id: string | null;
  first_seen: string | null;
  last_seen: string | null;
  source: string;
  confidence: number;
  is_watched: boolean;
}

export interface ThreatGroupDetail extends ThreatGroupSummary {
  techniques: string[];
  source_refs: SourceRef[];
  infra_ips: ThreatInfraIPSummary[];
  malware_families: MalwareFamilySummary[];
  vulnerabilities: GroupVulnSummary[];
  apt_aliases: AptAliasEntry[];
}

export interface ThreatInfraIPSummary {
  id: string;
  ip_address: string;
  ip_type: string;
  malware_family: string | null;
  geo_country: string | null;
  asn: string | null;
  first_seen: string | null;
  last_seen: string | null;
  status: string;
  source: string;
  confidence: number;
}

export interface MalwareFamilySummary {
  id: string;
  family_name: string;
  aliases: string[];
  type: string;
  platform: string[];
  first_seen: string | null;
  last_active: string | null;
  source: string;
}

export interface GroupVulnSummary {
  id: string;
  cve_id: string;
  title: string | null;
  cvss_score: number | null;
  severity: string;
  is_cisa_kev: boolean;
  relationship_type: string;
  confidence: number;
  last_seen: string | null;
}

export interface AptAliasEntry {
  alias_name: string;
  naming_org: string | null;
  confidence: number;
}

export interface SourceRef {
  source: string;
  source_id?: string;
  url?: string | null;
  observed_at?: string | null;
  confidence?: number;
}

export interface ThreatVulnSummary {
  id: string;
  cve_id: string;
  title: string | null;
  cvss_score: number | null;
  severity: string;
  is_supply_chain: boolean;
  is_cisa_kev: boolean;
  has_poc: boolean;
  exploit_available: boolean;
  published_date: string | null;
  cisa_kev_date: string | null;
  primary_source: string;
}

export interface FeedPullRunSummary {
  id: string;
  source: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  inserted_count: number;
  updated_count: number;
  skipped_count: number;
  unmapped_count: number;
  error_message: string | null;
}

export interface FeedPullResult {
  run_id: string;
  source: string;
  status: string;
  inserted: number;
  updated: number;
  skipped: number;
  unmapped: number;
  error: string | null;
  metadata?: Record<string, unknown>;
}

// ── API Functions ───────────────────────────────────────────────────────

const BASE = "/api/threat-intel";

export async function fetchOverview(token: string): Promise<OverviewData> {
  return request<OverviewData>(`${BASE}/overview`, token);
}

export async function fetchGroups(
  token: string,
  params?: {
    q?: string;
    watched?: boolean;
    origin_country?: string;
    target_sector?: string;
    page?: number;
    page_size?: number;
  },
): Promise<PaginatedResponse<ThreatGroupSummary>> {
  const search = new URLSearchParams();
  if (params?.q) search.set("q", params.q);
  if (params?.watched !== undefined) search.set("watched", String(params.watched));
  if (params?.origin_country) search.set("origin_country", params.origin_country);
  if (params?.target_sector) search.set("target_sector", params.target_sector);
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return request<PaginatedResponse<ThreatGroupSummary>>(
    `${BASE}/groups${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function fetchGroupDetail(
  token: string,
  groupId: string,
): Promise<ThreatGroupDetail> {
  return request<ThreatGroupDetail>(`${BASE}/groups/${groupId}`, token);
}

export async function watchGroup(
  token: string,
  groupId: string,
  note?: string,
): Promise<void> {
  await request(`${BASE}/groups/${groupId}/watch`, token, {
    method: "POST",
    body: JSON.stringify(note ? { note } : {}),
  });
}

export async function unwatchGroup(
  token: string,
  groupId: string,
): Promise<void> {
  await request(`${BASE}/groups/${groupId}/watch`, token, {
    method: "DELETE",
  });
}

export async function fetchThreatIPs(
  token: string,
  params?: {
    group_id?: string;
    ip_type?: string;
    status?: string;
    q?: string;
    page?: number;
    page_size?: number;
  },
): Promise<PaginatedResponse<ThreatInfraIPSummary>> {
  const search = new URLSearchParams();
  if (params?.group_id) search.set("group_id", params.group_id);
  if (params?.ip_type) search.set("ip_type", params.ip_type);
  if (params?.status) search.set("status", params.status);
  if (params?.q) search.set("q", params.q);
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return request<PaginatedResponse<ThreatInfraIPSummary>>(
    `${BASE}/ips${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function fetchVulns(
  token: string,
  params?: {
    q?: string;
    severity?: string;
    is_supply_chain?: boolean;
    is_cisa_kev?: boolean;
    has_poc?: boolean;
    exploit_available?: boolean;
    page?: number;
    page_size?: number;
  },
): Promise<PaginatedResponse<ThreatVulnSummary>> {
  const search = new URLSearchParams();
  if (params?.q) search.set("q", params.q);
  if (params?.severity) search.set("severity", params.severity);
  if (params?.is_supply_chain !== undefined) search.set("is_supply_chain", String(params.is_supply_chain));
  if (params?.is_cisa_kev !== undefined) search.set("is_cisa_kev", String(params.is_cisa_kev));
  if (params?.has_poc !== undefined) search.set("has_poc", String(params.has_poc));
  if (params?.exploit_available !== undefined) search.set("exploit_available", String(params.exploit_available));
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return request<PaginatedResponse<ThreatVulnSummary>>(
    `${BASE}/vulns${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function fetchMalware(
  token: string,
  params?: {
    group_id?: string;
    type?: string;
    q?: string;
    page?: number;
    page_size?: number;
  },
): Promise<PaginatedResponse<MalwareFamilySummary>> {
  const search = new URLSearchParams();
  if (params?.group_id) search.set("group_id", params.group_id);
  if (params?.type) search.set("type", params.type);
  if (params?.q) search.set("q", params.q);
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return request<PaginatedResponse<MalwareFamilySummary>>(
    `${BASE}/malware${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function fetchFeedRuns(
  token: string,
  params?: { source?: string; status?: string; page?: number; page_size?: number },
): Promise<PaginatedResponse<FeedPullRunSummary>> {
  const search = new URLSearchParams();
  if (params?.source) search.set("source", params.source);
  if (params?.status) search.set("status", params.status);
  if (params?.page) search.set("page", String(params.page));
  if (params?.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return request<PaginatedResponse<FeedPullRunSummary>>(
    `${BASE}/feeds/runs${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function triggerFeedPull(
  token: string,
  source: string,
): Promise<FeedPullResult> {
  return request<FeedPullResult>(`${BASE}/feeds/pull`, token, {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}
