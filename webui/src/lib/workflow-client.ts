/**
 * Workflow builder REST client.
 *
 * Contract: `.trellis/tasks/05-11-workflow-builder-ui/api-spec.md`.
 * All payloads are camelCase — the backend (`secbot/api/workflow_routes.py`)
 * serializes directly in this shape, so we do not rename fields.
 *
 * Transport notes:
 *   * Auth uses the same Bearer token that powers the chat WS (obtained
 *     via ``fetchBootstrap``); we consume it from ``useClient()``.
 *   * WebSocket events (``workflow.run.*`` / ``workflow.step.*``) are
 *     wired in a follow-up PR once ``WorkflowService`` exposes
 *     ``progress_cb`` to the WS channel. Until then the UI polls
 *     ``/runs`` while a run is active (3s interval) — consumers can opt
 *     in via the `pollingIntervalMs` config on their React Query call.
 */

import { ApiError } from "./api";

// ─── Data models (mirror api-spec §1) ───────────────────────────────────

export type WorkflowInputType =
  | "string"
  | "cidr"
  | "int"
  | "bool"
  | "enum";

export interface WorkflowInput {
  name: string;
  label: string;
  description?: string | null;
  type: WorkflowInputType;
  required: boolean;
  default?: unknown;
  enumValues?: string[] | null;
}

export type StepKind = "tool" | "script" | "agent" | "llm";
export type StepOnError = "stop" | "continue" | "retry";

/** Raw step payload as stored on the backend. `args` is intentionally
 * unknown — shape depends on `kind`, see api-spec §1.3 table. */
export interface WorkflowStep {
  id: string;
  name: string;
  kind: StepKind;
  ref: string;
  args: Record<string, unknown>;
  condition?: string | null;
  onError: StepOnError;
  retry: number;
}

export type StepResultStatus = "ok" | "error" | "skipped" | "retried";

export interface StepResult {
  status: StepResultStatus;
  startedAtMs: number;
  finishedAtMs: number;
  durationMs: number;
  output: unknown;
  error: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  tags: string[];
  inputs: WorkflowInput[];
  steps: WorkflowStep[];
  scheduleRef: string | null;
  createdAtMs: number;
  updatedAtMs: number;
}

/** Payload used for create/update — server generates `id`/timestamps on POST. */
export type WorkflowDraft = Omit<
  Workflow,
  "id" | "createdAtMs" | "updatedAtMs"
> & {
  id?: string;
};

export type RunStatus = "running" | "ok" | "error" | "cancelled";
export type RunTrigger = "manual" | "cron" | "api";

export interface WorkflowRun {
  id: string;
  workflowId: string;
  startedAtMs: number;
  finishedAtMs: number | null;
  status: RunStatus;
  inputs: Record<string, unknown>;
  stepResults: Record<string, StepResult>;
  trigger: RunTrigger;
  error: string | null;
}

export interface WorkflowListResponse {
  items: Workflow[];
  total: number;
  stats: {
    running: number;
    scheduled: number;
    failed24h: number;
  };
}

export interface WorkflowRunsResponse {
  items: WorkflowRun[];
}

export interface RunStartResponse {
  runId: string;
  status: RunStatus;
}

// ─── Schedule ───────────────────────────────────────────────────────────

export type ScheduleKind = "at" | "every" | "cron";

export interface SchedulePayload {
  kind: ScheduleKind;
  cronExpr?: string | null;
  tz?: string | null;
  atMs?: number | null;
  everyMs?: number | null;
  inputs?: Record<string, unknown>;
  enabled: boolean;
  name?: string | null;
}

// ─── Metadata (editor dropdowns) ────────────────────────────────────────

export interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  default?: unknown;
  description?: string;
  enum?: unknown[];
  items?: JsonSchema;
}

export interface ToolMeta {
  name: string;
  title: string;
  description: string;
  inputSchema: JsonSchema;
  outputSchema?: JsonSchema;
}

export interface AgentMeta {
  name: string;
  title: string;
  description: string;
  inputSchema: JsonSchema;
  outputSchema?: JsonSchema;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  tags: string[];
  /** Draft pre-populated from the template — consumer clones then POSTs. */
  workflow: WorkflowDraft;
}

export interface ToolListResponse {
  items: ToolMeta[];
}
export interface AgentListResponse {
  items: AgentMeta[];
}
export interface TemplateListResponse {
  items: WorkflowTemplate[];
}

// ─── Errors ─────────────────────────────────────────────────────────────

/** Business error body returned with 4xx/5xx (api-spec §4). */
export interface WorkflowErrorBody {
  code: string;
  message: string;
}

/** Enriched error surfaced for API calls when the server returns a
 * structured ``{ "error": { code, message } }`` body. Extends
 * :class:`ApiError` so existing ``instanceof`` checks keep working. */
export class WorkflowApiError extends ApiError {
  code: string;
  constructor(status: number, code: string, message: string) {
    super(status, message);
    this.code = code;
    this.name = "WorkflowApiError";
  }
}

// ─── Internals ──────────────────────────────────────────────────────────

interface RequestOptions extends RequestInit {
  token: string;
}

async function wfRequest<T>(
  url: string,
  { token, headers, ...init }: RequestOptions,
): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
    credentials: "same-origin",
  });
  if (!res.ok) {
    // Prefer the structured body documented in api-spec §4; fall back to
    // plain HTTP status when the server hands us something else.
    let code = `http.${res.status}`;
    let message = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { error?: WorkflowErrorBody };
      if (body && typeof body === "object" && body.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
    } catch {
      // non-JSON body — keep the fallback values
    }
    throw new WorkflowApiError(res.status, code, message);
  }
  // Some mutating endpoints (e.g. DELETE) may return no body.
  if (res.status === 204) return undefined as unknown as T;
  const text = await res.text();
  if (!text) return undefined as unknown as T;
  return JSON.parse(text) as T;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

// ─── Public API ─────────────────────────────────────────────────────────

export interface ListWorkflowsOptions {
  tag?: string;
  status?: string;
  search?: string;
  [key: string]: string | number | boolean | undefined;
}

export interface WorkflowClientConfig {
  token: string;
  /** HTTP base, default "" (same-origin). */
  baseUrl?: string;
}

/** Thin stateless REST façade. Instantiate per-render-cycle or memoize
 * via ``useMemo(() => new WorkflowClient({ token }), [token])``. */
export class WorkflowClient {
  private readonly token: string;
  private readonly base: string;

  constructor({ token, baseUrl = "" }: WorkflowClientConfig) {
    this.token = token;
    this.base = baseUrl;
  }

  // CRUD --------------------------------------------------------------

  list(opts: ListWorkflowsOptions = {}): Promise<WorkflowListResponse> {
    return wfRequest<WorkflowListResponse>(
      `${this.base}/api/workflows${qs(opts)}`,
      { token: this.token },
    );
  }

  get(id: string): Promise<Workflow> {
    return wfRequest<Workflow>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}`,
      { token: this.token },
    );
  }

  create(draft: WorkflowDraft): Promise<Workflow> {
    return wfRequest<Workflow>(`${this.base}/api/workflows`, {
      token: this.token,
      method: "POST",
      body: JSON.stringify(draft),
    });
  }

  update(id: string, draft: WorkflowDraft): Promise<Workflow> {
    return wfRequest<Workflow>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}`,
      {
        token: this.token,
        method: "PUT",
        body: JSON.stringify(draft),
      },
    );
  }

  patch(id: string, patch: Partial<WorkflowDraft>): Promise<Workflow> {
    return wfRequest<Workflow>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}`,
      {
        token: this.token,
        method: "PATCH",
        body: JSON.stringify(patch),
      },
    );
  }

  remove(id: string): Promise<void> {
    return wfRequest<void>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}`,
      { token: this.token, method: "DELETE" },
    );
  }

  // Run control -------------------------------------------------------

  run(id: string, inputs: Record<string, unknown>): Promise<RunStartResponse> {
    return wfRequest<RunStartResponse>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}/run`,
      {
        token: this.token,
        method: "POST",
        body: JSON.stringify({ inputs }),
      },
    );
  }

  cancel(id: string): Promise<{ runId: string; status: RunStatus }> {
    return wfRequest(
      `${this.base}/api/workflows/${encodeURIComponent(id)}/cancel`,
      { token: this.token, method: "POST" },
    );
  }

  listRuns(id: string, limit = 20): Promise<WorkflowRunsResponse> {
    return wfRequest<WorkflowRunsResponse>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}/runs${qs({
        limit,
      })}`,
      { token: this.token },
    );
  }

  getRun(id: string, runId: string): Promise<WorkflowRun> {
    return wfRequest<WorkflowRun>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`,
      { token: this.token },
    );
  }

  // Schedule ----------------------------------------------------------

  attachSchedule(id: string, payload: SchedulePayload): Promise<Workflow> {
    return wfRequest<Workflow>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}/schedule`,
      {
        token: this.token,
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  }

  detachSchedule(id: string): Promise<Workflow> {
    return wfRequest<Workflow>(
      `${this.base}/api/workflows/${encodeURIComponent(id)}/schedule`,
      { token: this.token, method: "DELETE" },
    );
  }

  // Metadata ----------------------------------------------------------

  listTools(): Promise<ToolListResponse> {
    return wfRequest<ToolListResponse>(
      `${this.base}/api/workflows/_tools`,
      { token: this.token },
    );
  }

  listAgents(): Promise<AgentListResponse> {
    return wfRequest<AgentListResponse>(
      `${this.base}/api/workflows/_agents`,
      { token: this.token },
    );
  }

  listTemplates(): Promise<TemplateListResponse> {
    return wfRequest<TemplateListResponse>(
      `${this.base}/api/workflows/_templates`,
      { token: this.token },
    );
  }
}

// ─── Helpers for the UI layer ───────────────────────────────────────────

/** Empty draft used by "create new" flows. */
export function emptyWorkflowDraft(): WorkflowDraft {
  return {
    name: "",
    description: "",
    tags: [],
    inputs: [],
    steps: [],
    scheduleRef: null,
  };
}

/** Freshly-generated step id that is unique within ``existing``. */
export function nextStepId(existing: WorkflowStep[]): string {
  const used = new Set(existing.map((s) => s.id));
  for (let i = 1; i < 1000; i += 1) {
    const candidate = `s${i}`;
    if (!used.has(candidate)) return candidate;
  }
  return `s${Date.now().toString(36)}`;
}

/** Deterministic blank step for each kind (args shape per api-spec §1.3). */
export function blankStep(kind: StepKind, id: string): WorkflowStep {
  const base: WorkflowStep = {
    id,
    name: "",
    kind,
    ref: "",
    args: {},
    condition: null,
    onError: "stop",
    retry: 0,
  };
  if (kind === "script") {
    base.ref = "python";
    base.args = { code: "", timeoutMs: 15000 };
  } else if (kind === "llm") {
    base.ref = "chat";
    base.args = {
      systemPrompt: "",
      userPrompt: "",
      temperature: 0.2,
      responseFormat: "text",
    };
  }
  return base;
}

/** Short colour hint per kind used by StepCard / Badge. */
export const STEP_KIND_TONE: Record<
  StepKind,
  { dot: string; badge: string; label: string }
> = {
  tool: {
    dot: "bg-primary",
    badge: "bg-primary/10 text-primary border-primary/30",
    label: "tool",
  },
  script: {
    dot: "bg-purple-500",
    badge:
      "bg-purple-500/10 text-purple-300 border-purple-400/30",
    label: "script",
  },
  agent: {
    dot: "bg-indigo-500",
    badge:
      "bg-indigo-500/10 text-indigo-300 border-indigo-400/30",
    label: "agent",
  },
  llm: {
    dot: "bg-pink-500",
    badge:
      "bg-pink-500/10 text-pink-300 border-pink-400/30",
    label: "llm",
  },
};

/** Feature flag — `true` (default) enables the builder UI. Flipping
 * `VITE_WORKFLOW_BUILDER=false` at build time hides it without a code
 * change, matching the pattern used by `VITE_UIUX_TEMPLATE`. */
export const WORKFLOW_BUILDER_ENABLED =
  (import.meta.env.VITE_WORKFLOW_BUILDER ?? "true").toLowerCase() !== "false";
