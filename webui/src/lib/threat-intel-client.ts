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
  const params = new URLSearchParams({ action: "add" });
  if (note) params.set("note", note);
  await request(`${BASE}/groups/${groupId}/watch?${params}`, token);
}

export async function unwatchGroup(
  token: string,
  groupId: string,
): Promise<void> {
  await request(`${BASE}/groups/${groupId}/watch?action=remove`, token);
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
  // The websockets gateway only accepts GET; the feed pull is exposed as
  // ``GET /feeds/pull?source=<name>`` instead of POST.
  return request<FeedPullResult>(
    `${BASE}/feeds/pull?source=${encodeURIComponent(source)}`,
    token,
  );
}

// ── Graph Types & API (P1) ─────────────────────────────────────────────

export interface GraphNode {
  id: string;
  type: "group" | "ip" | "malware" | "vuln" | "cluster";
  label: string;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "uses_c2" | "uses_malware" | "exploits" | "targets";
  confidence: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: {
    total_nodes: number;
    total_edges: number;
    clustered_nodes: number;
    groups_included: number;
  };
}

export async function fetchGraph(
  token: string,
  params: {
    group_id?: string;
    watched?: boolean;
    group_ids?: string[];
    top_n?: number;
    min_confidence?: number;
    node_types?: string[];
    expand_cluster?: string;
  },
): Promise<GraphData> {
  const search = new URLSearchParams();
  if (params.group_id) search.set("group_id", params.group_id);
  if (params.watched !== undefined) search.set("watched", String(params.watched));
  if (params.group_ids) search.set("group_ids", params.group_ids.join(","));
  if (params.top_n) search.set("top_n", String(params.top_n));
  if (params.min_confidence !== undefined) search.set("min_confidence", String(params.min_confidence));
  if (params.node_types) search.set("node_types", params.node_types.join(","));
  if (params.expand_cluster) search.set("expand_cluster", params.expand_cluster);
  const qs = search.toString();
  return request<GraphData>(`${BASE}/graph${qs ? `?${qs}` : ""}`, token);
}

// ── Detail Types & API (P1) ────────────────────────────────────────────

export interface ThreatVulnDetail extends ThreatVulnSummary {
  description: string | null;
  affected_products: string[];
  sources: string[];
  source_refs: SourceRef[];
  tags: string[];
  exploiting_groups: {
    group_id: string;
    group_name: string;
    relationship_type: string;
    confidence: number;
    last_seen: string | null;
  }[];
  last_ingested_at: string;
  created_at: string;
  updated_at: string;
}

export interface ThreatInfraIPDetail extends ThreatInfraIPSummary {
  group_id: string;
  group_name: string | null;
  source_refs: SourceRef[];
  tags: string[];
  last_ingested_at: string;
  created_at: string;
}

export interface MalwareFamilyDetail extends MalwareFamilySummary {
  group_id: string;
  group_name: string | null;
  aliases: string[];
  description: string | null;
  sample_hashes: { md5?: string; sha256?: string; source: string }[];
  yara_rules: string[];
  source_refs: SourceRef[];
  tags: string[];
  last_ingested_at: string;
  created_at: string;
}

export async function fetchVulnDetail(token: string, vulnId: string): Promise<ThreatVulnDetail> {
  return request<ThreatVulnDetail>(`${BASE}/vulns/${vulnId}`, token);
}

export async function fetchIPDetail(token: string, ipId: string): Promise<ThreatInfraIPDetail> {
  return request<ThreatInfraIPDetail>(`${BASE}/ips/${ipId}`, token);
}

export async function fetchMalwareDetail(token: string, malwareId: string): Promise<MalwareFamilyDetail> {
  return request<MalwareFamilyDetail>(`${BASE}/malware/${malwareId}`, token);
}

// ── Config Management API (P1) ────────────────────────────────────────

export interface IndustryCPEEntry {
  id: number;
  cpe_string: string;
  product_name: string;
  vendor: string | null;
  industry_tag: string;
  confidence: number;
  source: string;
  note: string | null;
}

export interface AptAliasFull {
  id: number;
  group_id: string | null;
  alias_name: string;
  naming_org: string | null;
  confidence: number;
  source_url: string | null;
}

export async function fetchIndustryCPEs(token: string): Promise<{ items: IndustryCPEEntry[]; total: number }> {
  return request(`${BASE}/config/industry-cpes`, token);
}

export async function addIndustryCPE(
  token: string,
  data: { cpe_string: string; product_name: string; vendor?: string; industry_tag?: string; confidence?: number },
): Promise<IndustryCPEEntry> {
  return request(`${BASE}/config/industry-cpes`, token, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function deleteIndustryCPE(token: string, cpeId: number): Promise<void> {
  await request(`${BASE}/config/industry-cpes/${cpeId}`, token, { method: "DELETE" });
}

export async function fetchAptAliases(token: string): Promise<{ items: AptAliasFull[]; total: number }> {
  return request(`${BASE}/config/aliases`, token);
}

export async function addAptAlias(
  token: string,
  data: { alias_name: string; group_id?: string; naming_org?: string; confidence?: number; source_url?: string },
): Promise<AptAliasFull> {
  return request(`${BASE}/config/aliases`, token, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function batchImportAliases(
  token: string,
  aliases: { alias_name: string; mitre_id?: string; group_id?: string; naming_org?: string; confidence?: number }[],
): Promise<{ total: number; inserted: number; updated: number; failed: number; errors: { alias_name: string; error: string }[] }> {
  return request(`${BASE}/config/aliases/batch`, token, {
    method: "POST",
    body: JSON.stringify({ aliases }),
  });
}

// ── Maritime Review API (P2) ──────────────────────────────────────────

export async function reviewMaritimeEvent(
  token: string,
  eventId: string,
  verificationStatus: "confirmed" | "dismissed",
): Promise<void> {
  await request(`${BASE}/maritime/${eventId}`, token, {
    method: "PATCH",
    body: JSON.stringify({ verification_status: verificationStatus }),
  });
}

// ── Review Queue API (P2) ─────────────────────────────────────────────

export interface ReviewQueueItem {
  id: string;
  entity_type: "ip" | "maritime";
  label: string;
  confidence: number;
  group_id: string | null;
  group_name: string | null;
  source: string;
  source_refs: SourceRef[];
  review_action: string;
}

export async function fetchReviewQueue(
  token: string,
  params: { type?: string; max_confidence?: number; page?: number; page_size?: number },
): Promise<PaginatedResponse<ReviewQueueItem>> {
  const search = new URLSearchParams();
  if (params.type) search.set("type", params.type);
  if (params.max_confidence !== undefined) search.set("max_confidence", String(params.max_confidence));
  if (params.page) search.set("page", String(params.page));
  if (params.page_size) search.set("page_size", String(params.page_size));
  const qs = search.toString();
  return request<PaginatedResponse<ReviewQueueItem>>(`${BASE}/review-queue${qs ? `?${qs}` : ""}`, token);
}

export async function submitReviewAction(
  token: string,
  itemId: string,
  action: string,
  body?: Record<string, unknown>,
): Promise<void> {
  await request(`${BASE}/review-queue/${itemId}/action`, token, {
    method: "POST",
    body: JSON.stringify({ action, ...body }),
  });
}

// ── Expiry Sweep API (P2) ─────────────────────────────────────────────

export async function triggerExpirySweep(token: string): Promise<Record<string, number>> {
  return request(`${BASE}/expiry-sweep`, token, { method: "POST" });
}
