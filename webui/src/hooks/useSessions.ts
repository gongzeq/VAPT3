import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import i18n from "@/i18n";
import {
  ApiError,
  deleteSession as apiDeleteSession,
  fetchSessionMessages,
  listSessions,
} from "@/lib/api";
import { deriveTitle } from "@/lib/format";
import { toMediaAttachment } from "@/lib/media";
import type { AgentEventPayload, ChatSummary, ToolCallStatus, UIMessage } from "@/lib/types";

const EMPTY_MESSAGES: UIMessage[] = [];

type RawHistoryMessage = {
  role: string;
  content: string;
  timestamp?: string;
  tool_calls?: unknown;
  tool_call_id?: string;
  name?: string;
  sender_id?: string;
  media_urls?: Array<{ url: string; name?: string }>;
  _kind?: string;
  agent_event?: Record<string, unknown>;
};

/** Trim a tool result string to a compact one-line preview suitable for
 * rendering inside the collapsible trace group. */
function toolResultPreview(content: string, name?: string): string {
  const trimmed = content.replace(/\s+/g, " ").trim();
  const short = trimmed.length > 120 ? `${trimmed.slice(0, 120)}…` : trimmed;
  const prefix = name ? `↳ ${name}` : "↳";
  return short ? `${prefix}: ${short}` : prefix;
}

/** Infer the agent name from a persisted assistant message. */
function inferAgentName(m: RawHistoryMessage): string | undefined {
  if (m.sender_id && m.sender_id !== "assistant") {
    return m.sender_id;
  }
  if (m.name) {
    return m.name;
  }
  return undefined;
}

/** Convert an OpenAI-compatible ``tool_call`` entry into an
 * ``AgentEventPayload`` so the UI can render it as a ``ToolCallCard``. */
function convertOpenAIToolCall(
  call: unknown,
  toolResults: Map<string, { content: string; name?: string }>,
): AgentEventPayload | null {
  if (!call || typeof call !== "object") return null;
  const obj = call as Record<string, unknown>;
  const fn = obj.function as Record<string, unknown> | undefined;
  const toolCallId = typeof obj.id === "string" ? obj.id : undefined;
  const toolName =
    (fn && typeof fn.name === "string" && fn.name) ||
    (typeof obj.name === "string" && obj.name) ||
    "tool";

  let toolArgs: Record<string, unknown> | undefined;
  if (fn && typeof fn.arguments === "string") {
    try {
      toolArgs = JSON.parse(fn.arguments);
    } catch {
      toolArgs = { raw: fn.arguments };
    }
  } else if (fn && typeof fn.arguments === "object") {
    toolArgs = fn.arguments as Record<string, unknown>;
  }

  // Look up the matching tool result to infer terminal status.
  const result = toolCallId ? toolResults.get(toolCallId) : undefined;
  let toolStatus: ToolCallStatus = "ok";
  let reason: string | undefined;
  if (result) {
    const lower = result.content.toLowerCase();
    if (
      lower.includes("error") ||
      lower.includes("exception") ||
      lower.includes("traceback") ||
      lower.includes("失败")
    ) {
      toolStatus = "error";
      reason = result.content.slice(0, 200);
    }
  }

  return {
    type: "tool_call",
    tool_call_id: toolCallId,
    tool_name: toolName,
    tool_args: toolArgs,
    tool_status: toolStatus,
    reason,
  };
}

/** Build a display string for a persisted ``agent_event`` so historical
 * replay matches the live-stream rendering in ``useNanobotStream``. */
function buildAgentEventContent(payload: AgentEventPayload): string {
  switch (payload.type) {
    case "thought":
      return payload.content ?? "";
    case "orchestrator_plan":
      return `编排计划：${payload.steps?.length ?? 0} 步`;
    case "subagent_spawned":
      return `🚀 子智能体「${payload.label ?? payload.task_id}」已启动`;
    case "subagent_done":
      return payload.status === "ok"
        ? `✅ 子智能体「${payload.label ?? payload.task_id}」已完成`
        : `❌ 子智能体「${payload.label ?? payload.task_id}」失败`;
    case "blackboard_entry":
      return `📝 黑板条目 [${payload.agent_name}]: ${payload.text ?? ""}`;
    default:
      return "";
  }
}

/** Convert the raw persisted session messages into the UI's message shape.
 *
 * Tool-call rows are reconstructed as ``toolCalls`` embedded inside the
 * assistant bubble (mirroring the live-stream layout) rather than flattened
 * into detached trace lines.  The ``agentName`` is recovered from
 * ``sender_id`` / ``name`` so avatars and meta labels stay correct on replay. */
function buildHistoryMessages(raw: RawHistoryMessage[]): UIMessage[] {
  // Pre-scan tool results so we can pair them with their call requests.
  const toolResults = new Map<string, { content: string; name?: string }>();
  for (const m of raw) {
    if (m.role === "tool" && typeof m.content === "string" && m.tool_call_id) {
      toolResults.set(m.tool_call_id, { content: m.content, name: m.name });
    }
  }

  const out: UIMessage[] = [];
  let pending: string[] = [];
  const flushPending = (idx: number) => {
    if (pending.length === 0) return;
    out.push({
      id: `hist-trace-${idx}`,
      role: "tool",
      kind: "trace",
      content: pending[pending.length - 1],
      traces: pending,
      createdAt: Date.now(),
    });
    pending = [];
  };

  raw.forEach((m, idx) => {
    if (m.role === "assistant") {
      // UI-only agent events (thought, subagent lifecycle, blackboard)
      // are persisted with ``_kind="agent_event"`` so they render as
      // inline cards on historical replay.
      if (m._kind === "agent_event" && m.agent_event) {
        const payload = m.agent_event as unknown as AgentEventPayload;
        const agentName =
          inferAgentName(m) || payload.agent_name || payload.agent || "assistant";
        flushPending(idx);
        out.push({
          id: `hist-${idx}`,
          role: "assistant",
          kind: "agent_event",
          content: buildAgentEventContent(payload),
          agentEvent: payload,
          agentName,
          createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
        });
        return;
      }

      const hasContent = typeof m.content === "string" && m.content.length > 0;
      const rawToolCalls = Array.isArray(m.tool_calls) ? m.tool_calls : [];
      const toolCalls = rawToolCalls
        .map((call) => convertOpenAIToolCall(call, toolResults))
        .filter(Boolean) as AgentEventPayload[];

      if (!hasContent && toolCalls.length === 0) {
        return;
      }

      flushPending(idx);
      const media =
        Array.isArray(m.media_urls) && m.media_urls.length > 0
          ? m.media_urls.map((mu) => toMediaAttachment(mu))
          : undefined;

      out.push({
        id: `hist-${idx}`,
        role: "assistant",
        content: m.content || "",
        agentName: inferAgentName(m),
        ...(toolCalls.length > 0 ? { toolCalls } : {}),
        createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
        ...(media ? { media } : {}),
      });
      return;
    }

    if (m.role === "tool") {
      // Only orphan tool results (no paired tool_call_id) become trace lines.
      if (!m.tool_call_id && typeof m.content === "string") {
        pending.push(toolResultPreview(m.content, m.name));
      }
      return;
    }

    if (m.role === "user") {
      if (typeof m.content !== "string") return;
      flushPending(idx);
      const media =
        Array.isArray(m.media_urls) && m.media_urls.length > 0
          ? m.media_urls.map((mu) => toMediaAttachment(mu))
          : undefined;
      const images =
        media?.every((item) => item.kind === "image")
          ? media.map((item) => ({ url: item.url, name: item.name }))
          : undefined;
      out.push({
        id: `hist-${idx}`,
        role: "user",
        content: m.content,
        createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
        ...(images ? { images } : {}),
        ...(media ? { media } : {}),
      });
    }
  });

  flushPending(raw.length);
  return out;
}

/** Sidebar state: fetches the full session list and exposes create / delete actions. */
export function useSessions(): {
  sessions: ChatSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createChat: () => Promise<string>;
  deleteChat: (key: string) => Promise<void>;
} {
  const { client, token } = useClient();
  const [sessions, setSessions] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tokenRef = useRef(token);
  tokenRef.current = token;
  /** Keys of optimistically-inserted sessions so ``refresh()`` does not
   * wipe them before the server has persisted them. */
  const optimisticKeysRef = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const rows = await listSessions(tokenRef.current);
      setSessions((prev) => {
        const serverKeys = new Set(rows.map((r) => r.key));
        // Keep optimistic sessions that the server has not returned yet.
        const kept = prev.filter((s) => {
          if (serverKeys.has(s.key)) {
            optimisticKeysRef.current.delete(s.key);
            return false;
          }
          return optimisticKeysRef.current.has(s.key);
        });
        return [...kept, ...rows];
      });
      setError(null);
    } catch (e) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const createChat = useCallback(async (): Promise<string> => {
    const chatId = await client.newChat();
    const key = `websocket:${chatId}`;
    optimisticKeysRef.current.add(key);
    // Optimistic insert; a subsequent refresh will replace it with the
    // authoritative row once the server persists the session.
    setSessions((prev) => [
      {
        key,
        channel: "websocket",
        chatId,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        title: "",
        preview: "",
      },
      ...prev.filter((s) => s.key !== key),
    ]);
    return chatId;
  }, [client]);

  const deleteChat = useCallback(
    async (key: string) => {
      await apiDeleteSession(tokenRef.current, key);
      setSessions((prev) => prev.filter((s) => s.key !== key));
    },
    [],
  );

  return { sessions, loading, error, refresh, createChat, deleteChat };
}

/** Lazy-load a session's on-disk messages the first time the UI displays it.
 *
 * NOTE: we intentionally do NOT try to infer "turn still running" from the
 * persisted JSONL tail (e.g. trailing assistant row with ``tool_calls`` and
 * no tool result). That heuristic is wrong when a process dies mid-turn or
 * ``/stop`` trims the tail, and would resurrect the Stop button on idle
 * chats. The authoritative live-turn signal comes from the backend's
 * ``attached`` event (``active_turn`` flag) — see ``useNanobotStream``. */
export function useSessionHistory(key: string | null): {
  messages: UIMessage[];
  loading: boolean;
  error: string | null;
} {
  const { token } = useClient();
  const [state, setState] = useState<{
    key: string | null;
    messages: UIMessage[];
    loading: boolean;
    error: string | null;
  }>({
    key: null,
    messages: [],
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!key) {
      setState({
        key: null,
        messages: [],
        loading: false,
        error: null,
      });
      return;
    }
    let cancelled = false;
    // Mark the new key as loading immediately so callers never see stale
    // messages from the previous session during the render right after a switch.
    setState({
      key,
      messages: [],
      loading: true,
      error: null,
    });
    (async () => {
      try {
        const body = await fetchSessionMessages(token, key);
        if (cancelled) return;
        const ui = buildHistoryMessages(body.messages);
        setState({
          key,
          messages: ui,
          loading: false,
          error: null,
        });
      } catch (e) {
        if (cancelled) return;
        // A 404 just means the session hasn't been persisted yet (brand-new
        // chat, first message not sent). That's a normal state, not an error.
        if (e instanceof ApiError && e.status === 404) {
          setState({
            key,
            messages: [],
            loading: false,
            error: null,
          });
        } else {
          setState({
            key,
            messages: [],
            loading: false,
            error: (e as Error).message,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, token]);

  if (!key) {
    return { messages: EMPTY_MESSAGES, loading: false, error: null };
  }

  // Even before the effect above commits its loading state, never surface the
  // previous session's payload for a brand-new key.
  if (state.key !== key) {
    return { messages: EMPTY_MESSAGES, loading: true, error: null };
  }

  return {
    messages: state.messages,
    loading: state.loading,
    error: state.error,
  };
}

/** Produce a compact display title for a session. */
export function sessionTitle(
  session: ChatSummary,
  firstUserMessage?: string,
): string {
  return deriveTitle(
    session.title || firstUserMessage || session.preview,
    i18n.t("chat.newChat"),
  );
}
