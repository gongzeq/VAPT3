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
import type { ChatSummary, UIMessage } from "@/lib/types";

const EMPTY_MESSAGES: UIMessage[] = [];

type RawHistoryMessage = {
  role: string;
  content: string;
  timestamp?: string;
  tool_calls?: unknown;
  tool_call_id?: string;
  name?: string;
  media_urls?: Array<{ url: string; name?: string }>;
};

/** Extract a tool function name from an OpenAI-compatible ``tool_call`` entry.
 * Falls back to the generic ``name``/``id`` fields so non-function tool
 * backends still render something meaningful. */
function toolCallLabel(call: unknown): string {
  if (!call || typeof call !== "object") return "tool";
  const obj = call as Record<string, unknown>;
  const fn = obj.function as Record<string, unknown> | undefined;
  const name =
    (fn && typeof fn.name === "string" && fn.name) ||
    (typeof obj.name === "string" && obj.name) ||
    (typeof obj.id === "string" && obj.id) ||
    "tool";
  return String(name);
}

/** Trim a tool result string to a compact one-line preview suitable for
 * rendering inside the collapsible trace group. */
function toolResultPreview(content: string, name?: string): string {
  const trimmed = content.replace(/\s+/g, " ").trim();
  const short = trimmed.length > 120 ? `${trimmed.slice(0, 120)}…` : trimmed;
  const prefix = name ? `↳ ${name}` : "↳";
  return short ? `${prefix}: ${short}` : prefix;
}

/** Convert the raw persisted session messages into the UI's message shape,
 * reconstructing the trace (tool-usage) rows from ``tool_calls`` and
 * ``role: "tool"`` entries so reopening a conversation still shows the
 * "Used N tools" breadcrumbs that appeared live. */
function buildHistoryMessages(raw: RawHistoryMessage[]): UIMessage[] {
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
      if (Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
        for (const call of m.tool_calls) {
          pending.push(`→ ${toolCallLabel(call)}`);
        }
      }
      if (typeof m.content === "string" && m.content.length > 0) {
        flushPending(idx);
        const media =
          Array.isArray(m.media_urls) && m.media_urls.length > 0
            ? m.media_urls.map((mu) => toMediaAttachment(mu))
            : undefined;
        out.push({
          id: `hist-${idx}`,
          role: "assistant",
          content: m.content,
          createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
          ...(media ? { media } : {}),
        });
      }
      return;
    }
    if (m.role === "tool") {
      if (typeof m.content === "string") {
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

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const rows = await listSessions(tokenRef.current);
      setSessions(rows);
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
