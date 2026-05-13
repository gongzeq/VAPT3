import type {
  ActivityEventListResponse,
  AgentRegistryRow,
  BlackboardEntry,
  ChatSummary,
  NotificationListResponse,
  SettingsPayload,
  SettingsUpdate,
  SlashCommand,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

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

function splitKey(key: string): { channel: string; chatId: string } {
  const idx = key.indexOf(":");
  if (idx === -1) return { channel: "", chatId: key };
  return { channel: key.slice(0, idx), chatId: key.slice(idx + 1) };
}

export async function listSessions(
  token: string,
  base: string = "",
): Promise<ChatSummary[]> {
  type Row = {
    key: string;
    created_at: string | null;
    updated_at: string | null;
    title?: string;
    preview?: string;
  };
  const body = await request<{ sessions: Row[] }>(
    `${base}/api/sessions`,
    token,
  );
  return body.sessions.map((s) => ({
    key: s.key,
    ...splitKey(s.key),
    createdAt: s.created_at,
    updatedAt: s.updated_at,
    title: s.title ?? "",
    preview: s.preview ?? "",
  }));
}

/** Signed image URL attached to a historical user message. The server
 * emits these in place of raw on-disk paths so the client can render
 * previews without learning where media lives on disk. Each URL is a
 * self-authenticating ``/api/media/...`` route (see backend
 * ``_sign_media_path``) safe to drop into an ``<img src>`` attribute. */
export interface SessionMediaUrl {
  url: string;
  name?: string;
}

export async function fetchSessionMessages(
  token: string,
  key: string,
  base: string = "",
): Promise<{
  key: string;
  created_at: string | null;
  updated_at: string | null;
  messages: Array<{
    role: string;
    content: string;
    timestamp?: string;
    tool_calls?: unknown;
    tool_call_id?: string;
    name?: string;
    /** Present on ``user`` turns that attached images. Paths have already
     * been stripped server-side; only the signed fetch URLs survive. */
    media_urls?: SessionMediaUrl[];
  }>;
}> {
  return request(
    `${base}/api/sessions/${encodeURIComponent(key)}/messages`,
    token,
  );
}

export async function deleteSession(
  token: string,
  key: string,
  base: string = "",
): Promise<boolean> {
  const body = await request<{ deleted: boolean }>(
    `${base}/api/sessions/${encodeURIComponent(key)}/delete`,
    token,
  );
  return body.deleted;
}

export async function fetchSettings(
  token: string,
  base: string = "",
): Promise<SettingsPayload> {
  return request<SettingsPayload>(`${base}/api/settings`, token);
}

export async function listSlashCommands(
  token: string,
  base: string = "",
): Promise<SlashCommand[]> {
  type Row = {
    command: string;
    title: string;
    description: string;
    icon: string;
    arg_hint?: string;
  };
  const body = await request<{ commands: Row[] }>(`${base}/api/commands`, token);
  return body.commands.map((command) => ({
    command: command.command,
    title: command.title,
    description: command.description,
    icon: command.icon,
    argHint: command.arg_hint ?? "",
  }));
}

export async function updateSettings(
  token: string,
  update: SettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  if (update.model !== undefined) query.set("model", update.model);
  if (update.provider !== undefined) query.set("provider", update.provider);
  if (update.api_base !== undefined) query.set("api_base", update.api_base);
  // ``api_key`` MUST travel via a request header, never the URL, so it does
  // not leak into access logs or browser history. Keeping the field undefined
  // means "don't touch the saved key"; an empty string means "clear it".
  const headers: Record<string, string> = {};
  if (update.api_key !== undefined) {
    headers["X-Settings-Api-Key"] = update.api_key;
  }
  return request<SettingsPayload>(
    `${base}/api/settings/update?${query}`,
    token,
    { headers },
  );
}

/**
 * Probe the user-supplied OpenAI-compatible endpoint for its model list.
 *
 * ``apiKey`` is optional: omitting it reuses the persisted key on the server
 * side, while a non-empty value travels over ``X-Settings-Api-Key`` so it is
 * never appended to the URL / access logs / browser history.
 */
export async function fetchProviderModels(
  token: string,
  apiBase: string,
  apiKey: string | undefined,
  base: string = "",
): Promise<string[]> {
  const query = new URLSearchParams();
  query.set("api_base", apiBase);
  const headers: Record<string, string> = {};
  if (apiKey !== undefined) {
    headers["X-Settings-Api-Key"] = apiKey;
  }
  const body = await request<{ models: string[] }>(
    `${base}/api/settings/models?${query}`,
    token,
    { headers },
  );
  return Array.isArray(body.models) ? body.models : [];
}

// ────────────────────────────────────────────────────────────────────────
// Notification center (P2) — REST contract from the archived backend PRD
// ``05-10-p2-notification-activity``. The backend uses ``GET`` (not POST)
// for the mutating endpoints because the ``websockets`` library's HTTP
// parser is incompatible with POST on the same port.
// ────────────────────────────────────────────────────────────────────────

export interface FetchNotificationsOptions {
  /** Filter to unread only. Backend treats ``unread=1`` as truthy. */
  unread?: boolean;
  /** Default 50 server-side; max is ring-buffer capacity (500). */
  limit?: number;
  /** Reserved for a future "load more" UI (E2 in PRD). Sent as ``0``
   * today but the signature keeps it extensible without a breaking
   * change. */
  offset?: number;
}

export async function fetchNotifications(
  token: string,
  options: FetchNotificationsOptions = {},
  base: string = "",
): Promise<NotificationListResponse> {
  const query = new URLSearchParams();
  if (options.unread) query.set("unread", "1");
  if (options.limit !== undefined) query.set("limit", String(options.limit));
  if (options.offset !== undefined) query.set("offset", String(options.offset));
  const qs = query.toString();
  return request<NotificationListResponse>(
    `${base}/api/notifications${qs ? `?${qs}` : ""}`,
    token,
  );
}

export async function markNotificationRead(
  token: string,
  id: string,
  base: string = "",
): Promise<{ id: string; read: boolean }> {
  return request<{ id: string; read: boolean }>(
    `${base}/api/notifications/${encodeURIComponent(id)}/read`,
    token,
  );
}

export async function markAllNotificationsRead(
  token: string,
  base: string = "",
): Promise<{ updated: number }> {
  return request<{ updated: number }>(
    `${base}/api/notifications/read-all`,
    token,
  );
}

export interface FetchActivityEventsOptions {
  /** ISO-8601 timestamp. When set, backend returns events strictly
   * newer than this instant (overrides the default 5-minute window). */
  since?: string;
  /** Default 50; backend caps at ring-buffer capacity (500). */
  limit?: number;
}

export async function fetchActivityEvents(
  token: string,
  options: FetchActivityEventsOptions = {},
  base: string = "",
): Promise<ActivityEventListResponse> {
  const query = new URLSearchParams();
  if (options.since) query.set("since", options.since);
  if (options.limit !== undefined) query.set("limit", String(options.limit));
  const qs = query.toString();
  return request<ActivityEventListResponse>(
    `${base}/api/events${qs ? `?${qs}` : ""}`,
    token,
  );
}

// ────────────────────────────────────────────────────────────────────────
// Expert agents & skills CRUD (PR3 — security tools as first-class tools).
// The backend enforces ``scoped_skills`` per agent and probes the real
// binaries referenced by each skill's ``external_binary`` header. The
// ``available`` / ``missing_binaries`` pair lets the UI surface offline
// status without a second round-trip.
// ────────────────────────────────────────────────────────────────────────

export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  scoped_skills: string[];
  max_iterations?: number;
  source_path?: string | null;
  /** True when every binary referenced by the agent's scoped skills is on
   * ``$PATH``. Defaults to ``true`` when the backend loaded the registry
   * without a skills root (i.e. could not probe). */
  available: boolean;
  required_binaries: string[];
  missing_binaries: string[];
}

export interface AgentDetail extends AgentInfo {
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  system_prompt: string;
  max_iterations: number;
  emit_plan_steps?: boolean;
  yaml_content: string;
  source_path: string | null;
}

export async function listAgents(
  token: string,
  base: string = "",
): Promise<AgentInfo[]> {
  const body = await request<{ agents: AgentInfo[] }>(
    `${base}/api/agents`,
    token,
  );
  return Array.isArray(body.agents) ? body.agents : [];
}

export async function getAgent(
  token: string,
  name: string,
  base: string = "",
): Promise<AgentDetail> {
  return request<AgentDetail>(
    `${base}/api/agents/${encodeURIComponent(name)}`,
    token,
  );
}

export async function createAgent(
  token: string,
  data: Partial<AgentDetail>,
  base: string = "",
): Promise<{ name: string; restart_required: boolean }> {
  return request(`${base}/api/agents`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateAgent(
  token: string,
  name: string,
  data: Partial<AgentDetail>,
  base: string = "",
): Promise<{ name: string; restart_required: boolean }> {
  return request(`${base}/api/agents/${encodeURIComponent(name)}`, token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteAgent(
  token: string,
  name: string,
  base: string = "",
): Promise<{ deleted: string; restart_required: boolean }> {
  return request(`${base}/api/agents/${encodeURIComponent(name)}`, token, {
    method: "DELETE",
  });
}

export interface SkillInfo {
  name: string;
  description: string;
  path: string;
  source_dir: string;
}

export interface SkillDetail {
  name: string;
  content: string;
  path: string;
}

export async function listSkills(
  token: string,
  base: string = "",
): Promise<SkillInfo[]> {
  const body = await request<{ skills: SkillInfo[] }>(
    `${base}/api/skills`,
    token,
  );
  return Array.isArray(body.skills) ? body.skills : [];
}

export async function getSkill(
  token: string,
  name: string,
  base: string = "",
): Promise<SkillDetail> {
  return request<SkillDetail>(
    `${base}/api/skills/${encodeURIComponent(name)}`,
    token,
  );
}

export async function createSkill(
  token: string,
  data: { name: string; content: string },
  base: string = "",
): Promise<{ name: string; path: string; restart_required: boolean }> {
  return request(`${base}/api/skills`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateSkill(
  token: string,
  name: string,
  data: { content: string },
  base: string = "",
): Promise<{ name: string; restart_required: boolean }> {
  return request(`${base}/api/skills/${encodeURIComponent(name)}`, token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteSkill(
  token: string,
  name: string,
  base: string = "",
): Promise<{ deleted: string; restart_required: boolean }> {
  return request(`${base}/api/skills/${encodeURIComponent(name)}`, token, {
    method: "DELETE",
  });
}

/** Fetch the expert-agent registry. With ``includeStatus=true`` each row is
 * enriched with ``status / current_task_id / progress / last_heartbeat_at``
 * pulled from the live ``SubagentManager`` snapshot. The default response
 * stays byte-stable for older callers (PRD 验收 6).
 */
export async function fetchAgents(
  token: string,
  options: { includeStatus?: boolean; base?: string } = {},
): Promise<AgentRegistryRow[]> {
  const { includeStatus = false, base = "" } = options;
  const qs = includeStatus ? "?include_status=true" : "";
  const body = await request<{ agents: AgentRegistryRow[] }>(
    `${base}/api/agents${qs}`,
    token,
  );
  return body.agents;
}

/** Fetch the blackboard snapshot for ``chatId``. The route returns an empty
 * ``entries`` array when the registry has no board for the chat (intentional
 * — reads do NOT create boards). 400 surfaces as ``ApiError`` with the
 * descriptive backend message. */
export async function fetchBlackboard(
  token: string,
  chatId: string,
  base: string = "",
): Promise<BlackboardEntry[]> {
  const body = await request<{ chat_id: string; entries: BlackboardEntry[] }>(
    `${base}/api/blackboard?chat_id=${encodeURIComponent(chatId)}`,
    token,
  );
  return body.entries ?? [];
}
