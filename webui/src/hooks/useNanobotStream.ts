import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { toMediaAttachment } from "@/lib/media";
import { planFromToolEvents, planFromWritePlanToolCall } from "@/lib/plan-events";
import type { StreamError } from "@/lib/secbot-client";
import {
  hasOnlyHiddenToolEvents,
  isHiddenFrontendToolName,
  isHiddenToolHintText,
} from "@/lib/tool-visibility";
import { randomId } from "@/lib/utils";
import type {
  AgentEventPayload,
  CumulativeUsage,
  InboundEvent,
  OutboundMedia,
  ToolCallStatus,
  UIImage,
  UIMessage,
} from "@/lib/types";

/** Generate a human-readable content string for a tool_call event card. */
function toolCallContent(toolName: string, status: ToolCallStatus, reason?: string): string {
  switch (status) {
    case "running":
      return `⚙️ ${toolName} 执行中…`;
    case "critical":
      return `⚠️ ${toolName} 高风险，等待审批…`;
    case "ok":
      return `✅ ${toolName} 已完成`;
    case "error":
      return reason
        ? `❌ ${toolName} 失败: ${reason}`
        : `❌ ${toolName} 失败`;
  }
}

function isTransientStreamingPlaceholder(message: UIMessage, agent: string): boolean {
  return (
    message.role === "assistant"
    && message.kind !== "trace"
    && message.agentName === agent
    && message.isStreaming === true
    && message.content.trim().length === 0
    && (message.media?.length ?? 0) === 0
    && (message.toolCalls?.length ?? 0) === 0
  );
}

/** Merge a ``tool_call`` payload into the most recent assistant message from
 * the same agent so it renders inside the bubble. Falls back to appending a
 * new assistant row when no suitable host exists. */
function mergeToolCall(
  prev: UIMessage[],
  payload: AgentEventPayload,
  agent: string,
): UIMessage[] {
  const tcId = payload.tool_call_id;
  const status = (payload.status ?? payload.tool_status ?? "running") as ToolCallStatus;
  payload.tool_status = status;
  const messages = prev.filter((m) => !isTransientStreamingPlaceholder(m, agent));

  // Terminal statuses — try to find the matching running/critical tool call
  // inside an existing message and update it in-place.
  if ((status === "ok" || status === "error") && tcId) {
    const msgIdx = messages.findIndex((m) =>
      m.toolCalls?.some((tc) => tc.tool_call_id === tcId),
    );
    if (msgIdx !== -1) {
      const msg = messages[msgIdx];
      const tcIdx = msg.toolCalls?.findIndex((tc) => tc.tool_call_id === tcId) ?? -1;
      if (tcIdx !== -1) {
        const updatedToolCalls = [...(msg.toolCalls ?? [])];
        updatedToolCalls[tcIdx] = { ...updatedToolCalls[tcIdx], ...payload, tool_status: status };
        const updated: UIMessage = {
          ...msg,
          toolCalls: updatedToolCalls,
          content: toolCallContent(payload.tool_name ?? "", status, payload.reason),
        };
        return [...messages.slice(0, msgIdx), updated, ...messages.slice(msgIdx + 1)];
      }
    }
  }

  // Find the most recent assistant message from the same agent.
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === "assistant" && m.kind !== "trace" && m.agentName === agent) {
      const updated: UIMessage = {
        ...m,
        toolCalls: [...(m.toolCalls || []), payload],
      };
      return [...messages.slice(0, i), updated, ...messages.slice(i + 1)];
    }
  }

  // Fallback — no host message; append a slim assistant row.
  return [
    ...messages,
    {
      id: randomId(),
      role: "assistant",
      content: toolCallContent(payload.tool_name ?? "", status, payload.reason),
      agentName: agent,
      toolCalls: [payload],
      createdAt: Date.now(),
    },
  ];
}

function planSignature(payload: AgentEventPayload): string {
  return JSON.stringify(payload.steps ?? []);
}

function appendPlanMessage(
  prev: UIMessage[],
  planPayload: AgentEventPayload,
  agent: string,
): UIMessage[] {
  const signature = planSignature(planPayload);
  const last = prev[prev.length - 1];
  if (
    last?.kind === "agent_event" &&
    last.agentEvent?.type === "orchestrator_plan" &&
    planSignature(last.agentEvent) === signature
  ) {
    return prev;
  }
  return [
    ...prev,
    {
      id: randomId(),
      role: "assistant",
      kind: "agent_event",
      content: `编排计划：${planPayload.steps?.length ?? 0} 步`,
      agentEvent: planPayload,
      agentName: agent,
      createdAt: Date.now(),
    },
  ];
}

function agentEventName(payload: AgentEventPayload, fallback: string): string {
  return payload.agent_name ?? payload.agent ?? fallback;
}

function isNonStreamingEvent(ev: InboundEvent): boolean {
  return (
    ev.event === "turn_end"
    || ev.event === "session_updated"
    || ev.event === "error"
    || (
      ev.event === "agent_event"
      && (ev.type === "asset_pushed" || ev.type === "agent_status" || ev.type === "llm_retry")
    )
    || (
      ev.event === "agent_event"
      && ev.type === "tool_call"
      && isHiddenFrontendToolName(ev.payload.tool_name)
    )
    || (
      ev.event === "message"
      && (ev.kind === "tool_hint" || ev.kind === "progress")
      && (
        hasOnlyHiddenToolEvents(ev.tool_events)
        || isHiddenToolHintText(ev.text)
      )
    )
  );
}

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
  /** Cumulative token usage across all completed turns in the current chat. */
  cumulativeUsage: CumulativeUsage;
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
  const [cumulativeUsage, setCumulativeUsage] = useState<CumulativeUsage>({
    promptTokens: 0,
    completionTokens: 0,
    cachedTokens: 0,
    turnCount: 0,
  });
  const buffer = useRef<StreamBuffer | null>(null);
  /** Most recent agent that emitted an ``agent_event`` or ``message``. Used
   * to tag plain assistant turns so they inherit the correct avatar colour. */
  const currentAgentRef = useRef<string>("orchestrator");
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
      setCumulativeUsage({ promptTokens: 0, completionTokens: 0, cachedTokens: 0, turnCount: 0 });
      buffer.current = null;
      currentAgentRef.current = "orchestrator";
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
        // Seed cumulative usage from the backend's persisted turn data so
        // the token badge reflects history even on a fresh connection.
        if (ev.cumulative_usage) {
          setCumulativeUsage({
            promptTokens: ev.cumulative_usage.prompt_tokens || 0,
            completionTokens: ev.cumulative_usage.completion_tokens || 0,
            cachedTokens: ev.cumulative_usage.cached_tokens || 0,
            turnCount: ev.cumulative_usage.turn_count || 0,
          });
        }
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
      if (!isNonStreamingEvent(ev)) {
        setIsStreaming(true);
      }

      if (ev.event === "delta") {
        // A delta arriving after an llm_retry means the provider recovered.
        // Clear the disruption banner so the user sees the stream resume.
        setStreamError((prev) => prev?.kind === "llm_retry" ? null : prev);
        if (ev.text.length === 0) return;
        if (!buffer.current && ev.text.trim().length === 0) return;
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
              agentName: currentAgentRef.current,
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
        // If the LLM recovered after a retry, dismiss the disruption banner.
        setStreamError((prev) => prev?.kind === "llm_retry" ? null : prev);
        setIsStreaming(false);

        // Attach per-turn usage to the last assistant message and accumulate.
        const usage = ev.usage;
        setMessages((prev) => {
          const updated = prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
          if (usage) {
            // Find the last assistant message and attach turnUsage to it.
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].role === "assistant" && updated[i].kind !== "trace") {
                updated[i] = { ...updated[i], turnUsage: usage };
                break;
              }
            }
          }
          return updated;
        });
        if (usage) {
          setCumulativeUsage((prev) => ({
            promptTokens: prev.promptTokens + (usage.prompt_tokens || 0),
            completionTokens: prev.completionTokens + (usage.completion_tokens || 0),
            cachedTokens: prev.cachedTokens + (usage.cached_tokens || 0),
            turnCount: prev.turnCount + 1,
          }));
        }
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
          if (
            hasOnlyHiddenToolEvents(ev.tool_events)
            || isHiddenToolHintText(ev.text)
          ) {
            return;
          }
          const planPayload = planFromToolEvents(ev.tool_events);
          if (planPayload) {
            setMessages((prev) =>
              appendPlanMessage(prev, planPayload, currentAgentRef.current),
            );
            return;
          }
          const line = ev.text;
          if (!line.trim()) return;
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
              agentName: currentAgentRef.current,
              ...(ev.buttons && ev.buttons.length > 0 ? { buttons: ev.buttons } : {}),
              ...(ev.tool_name ? { toolName: ev.tool_name } : {}),
              ...(ev.prompt_kind ? { promptKind: ev.prompt_kind } : {}),
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

        // Infer the speaking agent from the payload and keep it live so
        // subsequent plain ``delta`` / ``message`` turns inherit the label.
        const inferredAgent = payload.agent_name || payload.agent || currentAgentRef.current;
        currentAgentRef.current = inferredAgent;

        // ── llm_retry → surface connection-disruption banner ────────────
        // The backend emits this when the LLM provider drops and the agent
        // loop is retrying with backoff. Surface it as a streamError so
        // StreamErrorNotice renders a visible alert above the composer.
        if (payload.type === "llm_retry") {
          setStreamError({
            kind: "llm_retry",
            attempt: payload.attempt ?? null,
            delaySec: payload.delay_sec ?? null,
          });
          return;
        }

        // ── tool_call merge logic (F2) ─────────────────────────────────
        // Merge into the most recent assistant message from the same agent
        // so the UI can render tool cards *inside* the bubble.
        if (payload.type === "tool_call") {
          if (isHiddenFrontendToolName(payload.tool_name)) {
            return;
          }
          const planPayload = planFromWritePlanToolCall(payload);
          if (planPayload) {
            setMessages((prev) => appendPlanMessage(prev, planPayload, inferredAgent));
            return;
          }
          setMessages((prev) => mergeToolCall(prev, payload, inferredAgent));
          return;
        }

        // ── high_risk_confirm → inline approval card (F5) ─────────────
        // Convert the backend's confirmation payload into an assistant
        // message with buttons so ThreadShell renders it as AskUserPrompt
        // with variant="approval". The ask_id is stashed so the answer
        // routes via ``client.sendUserReply`` (not a regular message).
        if (payload.type === "high_risk_confirm") {
          const skill = payload.skill ?? payload.tool_name ?? "unknown";
          const summary = payload.summary_for_user ?? `⦁安全确认：${skill} 将执行高风险操作`;
          const rawArgs = payload.tool_args ?? payload.args;
          const detail = rawArgs
            ? JSON.stringify(rawArgs, null, 2)
            : undefined;
          setMessages((prev) => [
            ...prev,
            {
              id: randomId(),
              role: "assistant",
              content: summary,
              agentName: inferredAgent,
              toolName: "request_approval",
              promptKind: "approval",
              buttons: [["Approve", "Deny"]],
              askId: payload.ask_id,
              approvalDetail: detail,
              createdAt: Date.now(),
            },
          ]);
          return;
        }

        // 隐藏子智能体中间状态（工具调用过程）不在前端展示
        if (payload.type === "subagent_status") {
          return;
        }

        // agent_status 是纯 sidebar 状态心跳；asset_pushed 由资产面板消费。
        // 这类数据馈送不应在聊天流中生成空 agent_event 外壳。
        if (payload.type === "agent_status" || payload.type === "asset_pushed") {
          return;
        }

        if (payload.type === "orchestrator_plan") {
          setMessages((prev) => appendPlanMessage(prev, payload, inferredAgent));
          return;
        }

        const content = (() => {
          const eventAgentName = agentEventName(payload, inferredAgent);
          switch (payload.type) {
            case "thought":
              return payload.content ?? "";
            case "subagent_spawned":
              return `🚀 子智能体「${eventAgentName}」已启动`;
            case "subagent_done":
              return payload.status === "ok"
                ? `✅ 子智能体「${eventAgentName}」已完成`
                : `❌ 子智能体「${eventAgentName}」失败`;
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
            agentName: inferredAgent,
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

      const previews = hasImages ? images?.map((i) => i.preview) : undefined;
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
      const wireMedia = hasImages ? images?.map((i) => i.media) : undefined;
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
    cumulativeUsage,
  };
}
