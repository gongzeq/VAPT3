import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { toMediaAttachment } from "@/lib/media";
import type { StreamError } from "@/lib/secbot-client";
import { randomId } from "@/lib/utils";
import type {
  InboundEvent,
  OutboundMedia,
  UIImage,
  UIMessage,
} from "@/lib/types";

interface StreamBuffer {
  /** ID of the assistant message currently receiving deltas. */
  messageId: string;
  /** Sequence of deltas accumulated in order. */
  parts: string[];
}

/**
 * Subscribe to a chat by ID. Returns the in-memory message list for the chat,
 * a streaming flag, and a ``send`` function. Initial history must be seeded
 * separately (e.g. via ``fetchSessionMessages``) since the server only replays
 * live events.
 */
/** Payload passed to ``send`` when the user attaches one or more images.
 *
 * ``media`` is handed to the wire client verbatim; ``preview`` powers the
 * optimistic user bubble (blob URLs so the preview appears before the server
 * acks the frame). Keeping the two separate lets the bubble re-use the local
 * blob URL even after the server persists the file under a different name. */
export interface SendImage {
  media: OutboundMedia;
  preview: UIImage;
}

export function useNanobotStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
  onTurnEnd?: () => void,
): {
  messages: UIMessage[];
  isStreaming: boolean;
  send: (content: string, images?: SendImage[]) => void;
  setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>;
  /** Latest transport-level fault raised since the last ``dismissStreamError``.
   * ``null`` when there is nothing to show. */
  streamError: StreamError | null;
  /** Clear the current ``streamError`` (e.g. after the user dismisses the
   * notification or starts a fresh action). */
  dismissStreamError: () => void;
} {
  const { client } = useClient();
  const [messages, setMessages] = useState<UIMessage[]>(initialMessages);
  // ``isStreaming`` is *only* toggled by live evidence of an in-flight turn:
  //   - The authoritative ``attached`` event from the backend (``active_turn``
  //     flag) after a refresh / chat switch.
  //   - The user's own ``send()`` flipping it optimistically.
  //   - Inbound stream events (``delta`` / ``message`` / ``tool_hint`` /
  //     ``progress`` / ``stream_end``) keeping it true across tool boundaries.
  //   - ``turn_end`` clearing it exactly once per completed or aborted turn.
  // We deliberately do NOT infer it from persisted history (trailing trace
  // row, stale ``tool_calls`` in the JSONL, etc.): those signals can outlive
  // the real turn when a process crashes or ``/stop`` trims the tail, and
  // would resurrect the Stop button on idle chats.
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<StreamError | null>(null);
  const buffer = useRef<StreamBuffer | null>(null);
  /** Timer that defers ``isStreaming = false`` after ``stream_end``.
   *
   * When the model finishes a text segment and calls a tool, the server
   * sends ``stream_end`` but the agent is still "thinking" while the tool
   * executes.  By deferring the flag reset by a short window (1 s) we keep
   * the loading spinner alive across tool-call boundaries without needing
   * backend changes. */
  const streamEndTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return client.onError((err) => setStreamError(err));
  }, [client]);

  const dismissStreamError = useCallback(() => setStreamError(null), []);

  // Reset local state when switching chats. ``streamError`` is scoped to the
  // send that triggered it, so a chat swap should wipe it out: a stale
  // "Message too large" banner on a freshly-opened chat-B would confuse the
  // user about which send actually failed (and in which chat).
  //
  // ``isStreaming`` is intentionally reset to ``false`` on every chat
  // change; the authoritative ``attached`` event (see stream handler below)
  // will raise it again when — and only when — the backend still has an
  // in-flight turn for this chat.  Never seed it from persisted history:
  // a stale ``tool_calls`` tail in the session JSONL outlives the real turn
  // when a process dies or ``/stop`` cleans up, which would resurrect the
  // Stop button on idle chats.
  const prevChatIdRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const chatChanged = prevChatIdRef.current !== chatId;
    prevChatIdRef.current = chatId;

    setMessages(initialMessages);

    if (chatChanged) {
      setIsStreaming(false);
      setStreamError(null);
      buffer.current = null;
      if (streamEndTimerRef.current !== null) {
        clearTimeout(streamEndTimerRef.current);
        streamEndTimerRef.current = null;
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, initialMessages]);

  useEffect(() => {
    if (!chatId) return;

    const handle = (ev: InboundEvent) => {
      // The ``attached`` confirmation carries the authoritative active-turn
      // flag from the backend. It arrives right after ``client.attach`` (on
      // chat open, refresh, or reconnect), so we use it as the source of
      // truth for ``isStreaming`` — lifting it when the server still has an
      // in-flight turn and (critically) *lowering* it when the server is
      // idle, even if local state had a stale ``true`` (e.g. a cached
      // optimistic send from a previous session that never got a
      // ``turn_end`` delivery because the tab was closed mid-turn).
      if (ev.event === "attached") {
        setIsStreaming(Boolean(ev.active_turn));
        return;
      }

      // Any incoming event while the debounce timer is alive means the model
      // is still working (e.g. tool result arrived, more text to stream).
      // Cancel the pending "stream ended" timer so we don't hide the spinner.
      if (streamEndTimerRef.current !== null) {
        clearTimeout(streamEndTimerRef.current);
        streamEndTimerRef.current = null;
      }

      // Any event other than ``turn_end`` / ``session_updated`` / ``error`` is
      // evidence the turn is still in flight. Keep the loading indicator (and
      // the composer's Stop button) alive across tool-call boundaries —
      // otherwise pure ``tool_hint`` / ``progress`` events (no deltas) would
      // leave ``isStreaming`` stuck at ``false`` while the agent is busy
      // calling tools.
      if (
        ev.event !== "turn_end"
        && ev.event !== "session_updated"
        && ev.event !== "error"
      ) {
        setIsStreaming(true);
      }

      if (ev.event === "delta") {
        const id = buffer.current?.messageId ?? randomId();
        if (!buffer.current) {
          buffer.current = { messageId: id, parts: [] };
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "assistant",
              content: "",
              isStreaming: true,
              createdAt: Date.now(),
            },
          ]);
          setIsStreaming(true);
        }
        buffer.current.parts.push(ev.text);
        const combined = buffer.current.parts.join("");
        const targetId = buffer.current.messageId;
        setMessages((prev) =>
          prev.map((m) => (m.id === targetId ? { ...m, content: combined } : m)),
        );
        return;
      }

      if (ev.event === "stream_end") {
        // stream_end only means the text segment finished — the model may
        // still be executing tools.  Do NOT reset isStreaming here; the
        // definitive "turn is complete" signal is ``turn_end``.
        if (!buffer.current) return;
        buffer.current = null;
        return;
      }

      if (ev.event === "turn_end") {
        // Definitive signal that the turn is fully complete.  Cancel any
        // pending debounce timer and stop the loading indicator immediately.
        if (streamEndTimerRef.current !== null) {
          clearTimeout(streamEndTimerRef.current);
          streamEndTimerRef.current = null;
        }
        setIsStreaming(false);
        setMessages((prev) =>
          prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)),
        );
        onTurnEnd?.();
        return;
      }

      if (ev.event === "session_updated") {
        onTurnEnd?.();
        return;
      }

      if (ev.event === "message") {
        // Intermediate agent breadcrumbs (tool-call hints, raw progress).
        // Attach them to the last trace row if it was the last emitted item
        // so a sequence of calls collapses into one compact trace group.
        if (ev.kind === "tool_hint" || ev.kind === "progress") {
          const line = ev.text;
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.kind === "trace" && !last.isStreaming) {
              const merged: UIMessage = {
                ...last,
                traces: [...(last.traces ?? [last.content]), line],
                content: line,
              };
              return [...prev.slice(0, -1), merged];
            }
            return [
              ...prev,
              {
                id: randomId(),
                role: "tool",
                kind: "trace",
                content: line,
                traces: [line],
                createdAt: Date.now(),
              },
            ];
          });
          return;
        }

        const media = ev.media_urls?.length
          ? ev.media_urls.map((m) => toMediaAttachment(m))
          : ev.media?.map((url) => toMediaAttachment({ url }));

        // A complete (non-streamed) assistant message. If a stream was in
        // flight, drop the placeholder so we don't render the text twice.
        const activeId = buffer.current?.messageId;
        buffer.current = null;
        // Do NOT reset isStreaming here — only ``turn_end`` signals that
        // the full turn (all tool calls + final text) is complete.
        setMessages((prev) => {
          const filtered = activeId ? prev.filter((m) => m.id !== activeId) : prev;
          const content = ev.buttons?.length ? (ev.button_prompt ?? ev.text) : ev.text;
          return [
            ...filtered,
            {
              id: randomId(),
              role: "assistant",
              content,
              createdAt: Date.now(),
              ...(ev.buttons && ev.buttons.length > 0 ? { buttons: ev.buttons } : {}),
              ...(media && media.length > 0 ? { media } : {}),
            },
          ];
        });
        return;
      }

      if (ev.event === "agent_event") {
        // Wire format places ``type`` at the frame top-level (alongside
        // ``event`` / ``chat_id``) while the rest of the shape lives under
        // ``payload``. Merge them back into a single ``AgentEventPayload``
        // so downstream switches have a single source of truth.
        const payload = { ...ev.payload, type: ev.type };
        const content = (() => {
          switch (payload.type) {
            case "thought":
              return payload.content ?? "";
            case "subagent_spawned":
              return `🚀 子智能体「${payload.label ?? payload.task_id}」已启动`;
            case "subagent_status":
              return `⏳ 子智能体「${payload.task_id}」状态: ${payload.phase ?? "unknown"} (迭代 ${payload.iteration ?? 0})`;
            case "subagent_done":
              return payload.status === "ok"
                ? `✅ 子智能体「${payload.label ?? payload.task_id}」已完成`
                : `❌ 子智能体「${payload.label ?? payload.task_id}」失败`;
            case "blackboard_entry":
              return `📝 黑板条目 [${payload.agent_name}]: ${payload.text ?? ""}`;
            default:
              return "";
          }
        })();
        setMessages((prev) => [
          ...prev,
          {
            id: randomId(),
            role: "assistant",
            kind: "agent_event",
            content,
            agentEvent: payload,
            createdAt: Date.now(),
          },
        ]);
        return;
      }
      // ``attached`` / ``error`` frames aren't actionable here; the client
      // shell handles them separately.
    };

    const unsub = client.onChat(chatId, handle);
    return () => {
      unsub();
      buffer.current = null;
      if (streamEndTimerRef.current !== null) {
        clearTimeout(streamEndTimerRef.current);
        streamEndTimerRef.current = null;
      }
    };
  }, [chatId, client, onTurnEnd]);

  const send = useCallback(
    (content: string, images?: SendImage[]) => {
      if (!chatId) return;
      const hasImages = !!images && images.length > 0;
      // Text is optional when images are attached — the agent will still see
      // the image blocks via ``media`` paths.
      if (!hasImages && !content.trim()) return;

      const previews = hasImages ? images!.map((i) => i.preview) : undefined;
      setMessages((prev) => [
        ...prev,
        {
          id: randomId(),
          role: "user",
          content,
          createdAt: Date.now(),
          ...(previews ? { images: previews } : {}),
        },
      ]);
      // Mark streaming immediately so the UI shows the loading indicator
      // right away, before the first delta arrives from the server.
      setIsStreaming(true);
      const wireMedia = hasImages ? images!.map((i) => i.media) : undefined;
      client.sendMessage(chatId, content, wireMedia);
    },
    [chatId, client],
  );

  return {
    messages,
    isStreaming,
    send,
    setMessages,
    streamError,
    dismissStreamError,
  };
}
