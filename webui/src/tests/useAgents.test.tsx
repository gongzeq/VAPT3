import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgents } from "@/hooks/useAgents";
import { ClientProvider } from "@/providers/ClientProvider";
import type { SecbotClient } from "@/lib/secbot-client";
import type { InboundEvent } from "@/lib/types";

type ChatHandler = (ev: InboundEvent) => void;

function makeClient() {
  const handlers = new Map<string, Set<ChatHandler>>();
  const client = {
    status: "idle",
    onStatus: () => () => {},
    onChat(chatId: string, handler: ChatHandler) {
      let set = handlers.get(chatId);
      if (!set) {
        set = new Set();
        handlers.set(chatId, set);
      }
      set.add(handler);
      return () => set!.delete(handler);
    },
  } as unknown as SecbotClient;
  return {
    client,
    emit(chatId: string, ev: InboundEvent) {
      handlers.get(chatId)?.forEach((h) => h(ev));
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useAgents", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function wrap(client: SecbotClient) {
    return ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="tok">
        {children}
      </ClientProvider>
    );
  }

  it("seeds the agent list from /api/agents?include_status=true", async () => {
    // useUnreadCount inside ClientProvider also fires a fetch — return an
    // empty body for any unrelated URL so we don't crash. Then queue our
    // /api/agents response.
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/agents")) {
        return Promise.resolve(
          jsonResponse({
            agents: [
              {
                name: "port_scan",
                display_name: "端口扫描",
                status: "idle",
                current_task_id: null,
                progress: null,
                last_heartbeat_at: null,
              },
              {
                name: "weak_password",
                status: "running",
                current_task_id: "task-1",
                progress: null,
                last_heartbeat_at: "2026-05-13T01:00:00Z",
              },
            ],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const { result } = renderHook(() => useAgents({ chatId: "chat-a" }), {
      wrapper: wrap(fake.client),
    });

    await waitFor(() => expect(result.current.agents).toHaveLength(2));
    expect(result.current.agents[0].name).toBe("port_scan");
    expect(result.current.agents[0].status).toBe("idle");
    expect(result.current.agents[1].status).toBe("running");
    // The hook MUST have appended ?include_status=true so the backend
    // returns runtime fields (PRD B1 / D7).
    const agentsCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/agents"),
    );
    expect(String(agentsCall?.[0])).toContain("include_status=true");
  });

  it("patches a row in-place when an agent_status WS frame arrives", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/agents")) {
        return Promise.resolve(
          jsonResponse({
            agents: [
              {
                name: "port_scan",
                status: "idle",
                current_task_id: null,
                progress: null,
                last_heartbeat_at: null,
              },
            ],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const { result } = renderHook(() => useAgents({ chatId: "chat-a" }), {
      wrapper: wrap(fake.client),
    });
    await waitFor(() => expect(result.current.agents).toHaveLength(1));
    expect(result.current.agents[0].status).toBe("idle");

    act(() => {
      fake.emit("chat-a", {
        event: "agent_event",
        chat_id: "chat-a",
        type: "agent_status",
        payload: {
          type: "agent_status",
          agent_name: "port_scan",
          agent_status: "running",
          current_task_id: "task-9",
          last_heartbeat_at: "2026-05-13T01:30:00Z",
        },
        timestamp: "2026-05-13T01:30:00Z",
      });
    });

    expect(result.current.agents[0].status).toBe("running");
    expect(result.current.agents[0].current_task_id).toBe("task-9");
  });

  it("ignores agent_status frames whose name is not in the registry", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/agents")) {
        return Promise.resolve(
          jsonResponse({
            agents: [{ name: "port_scan", status: "idle" }],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const { result } = renderHook(() => useAgents({ chatId: "chat-a" }), {
      wrapper: wrap(fake.client),
    });
    await waitFor(() => expect(result.current.agents).toHaveLength(1));

    act(() => {
      fake.emit("chat-a", {
        event: "agent_event",
        chat_id: "chat-a",
        type: "agent_status",
        payload: {
          type: "agent_status",
          agent_name: "ghost_agent",
          agent_status: "running",
        },
        timestamp: "2026-05-13T01:30:00Z",
      });
    });

    // Registry length unchanged; existing row still idle.
    expect(result.current.agents).toHaveLength(1);
    expect(result.current.agents[0].status).toBe("idle");
  });
});
