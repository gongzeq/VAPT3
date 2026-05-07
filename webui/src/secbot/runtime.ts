/**
 * secbot ChatRuntime adapter — bridges assistant-ui's ChatModelAdapter to
 * the existing secbot websocket gateway (`/api/ws`).
 *
 * The runtime streams Orchestrator deltas as text parts and surfaces every
 * skill execution as a `tool-call` content part so it can be rendered by the
 * registered skill renderers in `tool-ui.tsx`.
 */
import {
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
  useLocalRuntime,
} from "@assistant-ui/react";

export interface SecbotRuntimeOptions {
  /** Backend WS endpoint, defaults to relative `/api/ws`. */
  endpoint?: string;
  /** Optional bearer token for multi-tenant auth (`actor_id` is derived server-side). */
  token?: string;
}

interface SecbotPlanStep {
  step: number;
  expert: string;
  skill: string;
  args: Record<string, unknown>;
}

interface SecbotEvent {
  type:
    | "delta"
    | "plan"
    | "tool_call_start"
    | "tool_call_result"
    | "confirm_request"
    | "done"
    | "error";
  text?: string;
  plan?: SecbotPlanStep[];
  tool_call_id?: string;
  skill?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  message?: string;
}

function buildAdapter(options: SecbotRuntimeOptions): ChatModelAdapter {
  const endpoint = options.endpoint ?? "/api/ws";

  return {
    async *run({ messages, abortSignal }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult> {
      const url = new URL(endpoint, window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(url.toString(), options.token ? ["bearer", options.token] : undefined);

      const ready = new Promise<void>((resolve, reject) => {
        ws.addEventListener("open", () => resolve(), { once: true });
        ws.addEventListener("error", () => reject(new Error("ws connect failed")), { once: true });
      });
      await ready;

      abortSignal.addEventListener("abort", () => ws.close());

      ws.send(
        JSON.stringify({
          kind: "user_message",
          messages: messages.map((m: { role: string; content: unknown }) => ({ role: m.role, content: m.content })),
        }),
      );

      // Aggregate state across the run.
      const text: string[] = [];
      const toolCalls: Record<string, ChatModelRunResult["content"][number] & { type: "tool-call" }> = {};

      const queue: SecbotEvent[] = [];
      let resolveNext: ((v: SecbotEvent | null) => void) | null = null;
      ws.addEventListener("message", (ev) => {
        try {
          const evt: SecbotEvent = JSON.parse(ev.data);
          if (resolveNext) {
            resolveNext(evt);
            resolveNext = null;
          } else {
            queue.push(evt);
          }
        } catch {
          /* ignore malformed frames */
        }
      });
      ws.addEventListener("close", () => {
        if (resolveNext) {
          resolveNext(null);
          resolveNext = null;
        }
      });

      const nextEvent = (): Promise<SecbotEvent | null> =>
        queue.length
          ? Promise.resolve(queue.shift()!)
          : new Promise((res) => {
              resolveNext = res;
            });

      while (true) {
        const evt = await nextEvent();
        if (!evt) break;

        if (evt.type === "delta" && evt.text) {
          text.push(evt.text);
        } else if (evt.type === "tool_call_start" && evt.tool_call_id && evt.skill) {
          toolCalls[evt.tool_call_id] = {
            type: "tool-call",
            toolCallId: evt.tool_call_id,
            toolName: evt.skill,
            args: evt.args ?? {},
            argsText: JSON.stringify(evt.args ?? {}),
          };
        } else if (evt.type === "tool_call_result" && evt.tool_call_id) {
          const tc = toolCalls[evt.tool_call_id];
          if (tc) {
            // attach the structured result so the registered tool-ui renderer can pick it up
            (tc as unknown as { result?: unknown }).result = evt.result ?? {};
          }
        } else if (evt.type === "done") {
          break;
        } else if (evt.type === "error") {
          throw new Error(evt.message ?? "secbot backend error");
        }

        // emit incremental snapshot
        yield {
          content: [
            ...(text.length ? [{ type: "text" as const, text: text.join("") }] : []),
            ...Object.values(toolCalls),
          ],
        };
      }
    },
  };
}

export function useSecbotRuntime(options: SecbotRuntimeOptions = {}) {
  return useLocalRuntime(buildAdapter(options));
}
