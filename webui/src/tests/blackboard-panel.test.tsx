import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BlackboardPanel } from "@/components/BlackboardPanel";
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

function wrap(client: SecbotClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider client={client} token="tok">
        {children}
      </ClientProvider>
    );
  };
}

describe("BlackboardPanel", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("hydrates entries from /api/blackboard on mount and renders kind colours", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/blackboard")) {
        return Promise.resolve(
          jsonResponse({
            chat_id: "chat-a",
            entries: [
              {
                id: "e1",
                agent_name: "orchestrator",
                text: "[milestone] phase 1 done",
                timestamp: 1715600000,
                kind: "milestone",
              },
              {
                id: "e2",
                agent_name: "port_scan",
                text: "[blocker] cannot reach 10.0.0.5",
                timestamp: 1715600100,
                kind: "blocker",
              },
            ],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const Wrapper = wrap(fake.client);
    render(
      <Wrapper>
        <BlackboardPanel chatId="chat-a" />
      </Wrapper>,
    );

    await waitFor(() =>
      expect(screen.getByText(/phase 1 done/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/cannot reach/)).toBeInTheDocument();

    // The blocker row must apply the breath animation per F8 visual contract.
    const blockerNode = screen.getByText(/cannot reach/).closest("article");
    expect(blockerNode?.className).toContain("animate-breath");

    // The milestone row must NOT pulse.
    const milestoneNode = screen.getByText(/phase 1 done/).closest("article");
    expect(milestoneNode?.className).not.toContain("animate-breath");
  });

  it("appends WS blackboard_entry frames without re-rendering the HTTP-seeded row", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/blackboard")) {
        return Promise.resolve(
          jsonResponse({
            chat_id: "chat-a",
            entries: [
              {
                id: "seed",
                agent_name: "orchestrator",
                text: "[finding] open port 22",
                timestamp: 1715600000,
                kind: "finding",
              },
            ],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const Wrapper = wrap(fake.client);
    render(
      <Wrapper>
        <BlackboardPanel chatId="chat-a" />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/open port 22/)).toBeInTheDocument(),
    );

    // Same id as the HTTP seed — the dedup set MUST drop it.
    act(() => {
      fake.emit("chat-a", {
        event: "agent_event",
        chat_id: "chat-a",
        type: "blackboard_entry",
        payload: {
          type: "blackboard_entry",
          id: "seed",
          agent_name: "orchestrator",
          text: "[finding] open port 22",
          timestamp: 1715600000,
          kind: "finding",
        },
        timestamp: "2026-05-13T01:00:00Z",
      });
    });
    expect(screen.getAllByText(/open port 22/)).toHaveLength(1);

    // A new id MUST append.
    act(() => {
      fake.emit("chat-a", {
        event: "agent_event",
        chat_id: "chat-a",
        type: "blackboard_entry",
        payload: {
          type: "blackboard_entry",
          id: "live-1",
          agent_name: "weak_password",
          text: "[progress] 30% scanned",
          timestamp: 1715600200,
          kind: "progress",
        },
        timestamp: "2026-05-13T01:01:00Z",
      });
    });
    expect(screen.getByText(/30% scanned/)).toBeInTheDocument();
  });

  it("falls back to the [tag] regex when payload.kind is null", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/blackboard")) {
        return Promise.resolve(
          jsonResponse({
            chat_id: "chat-a",
            entries: [
              {
                id: "e1",
                agent_name: "orchestrator",
                text: "[blocker] degraded mode",
                timestamp: 1715600000,
                kind: null,
              },
            ],
          }),
        );
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const Wrapper = wrap(fake.client);
    render(
      <Wrapper>
        <BlackboardPanel chatId="chat-a" />
      </Wrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/degraded mode/)).toBeInTheDocument(),
    );
    const node = screen.getByText(/degraded mode/).closest("article");
    expect(node?.className).toContain("animate-breath");
  });

  it("renders empty state when chatId is null", () => {
    fetchMock.mockResolvedValue(jsonResponse({ unread_count: 0 }));
    const fake = makeClient();
    const Wrapper = wrap(fake.client);
    render(
      <Wrapper>
        <BlackboardPanel chatId={null} />
      </Wrapper>,
    );
    expect(screen.getByText(/选择会话后查看黑板/)).toBeInTheDocument();
  });
});
