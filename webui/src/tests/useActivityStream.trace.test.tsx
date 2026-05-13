import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useActivityStream } from "@/hooks/useActivityStream";
import { ClientProvider } from "@/providers/ClientProvider";
import type { SecbotClient } from "@/lib/secbot-client";
import type { ActivityEventFrame } from "@/lib/types";

/**
 * F9 Trace Tab — useActivityStream `chatId` / `categories` scoping.
 *
 * Covers the three PRD paths:
 *   1. HTTP seed URL includes ``chat_id`` + ``category`` when props set.
 *   2. No props → URL stays exactly as the dashboard knows it (back-compat).
 *   3. WS frames are filtered client-side by ``chat_id`` and ``category``.
 */

type ActivityHandler = (frame: ActivityEventFrame) => void;

function makeClient(): {
  client: SecbotClient;
  push: (frame: ActivityEventFrame) => void;
} {
  const handlers = new Set<ActivityHandler>();
  const client = {
    status: "idle",
    onStatus: () => () => {},
    onActivityEvent(handler: ActivityHandler) {
      handlers.add(handler);
      return () => {
        handlers.delete(handler);
      };
    },
  } as unknown as SecbotClient;
  return {
    client,
    push(frame) {
      for (const h of handlers) h(frame);
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** ClientProvider fires an "unread count" fetch that isn't relevant
 * to these tests — always stub it with an empty envelope. */
function stubUnreadFetch(mock: ReturnType<typeof vi.fn>) {
  mock.mockResolvedValue(
    jsonResponse({
      items: [],
      total: 0,
      limit: 1,
      offset: 0,
      unread_count: 0,
    }),
  );
}

describe("useActivityStream — Trace scope", () => {
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
    return ({ children }: { children: React.ReactNode }) => (
      <ClientProvider client={client} token="tok">
        {children}
      </ClientProvider>
    );
  }

  it("adds chat_id + category query params to the HTTP seed", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [] }));
    stubUnreadFetch(fetchMock);

    const { client } = makeClient();
    renderHook(
      () =>
        useActivityStream({
          chatId: "chat-trace-1",
          categories: ["tool_call", "tool_result"],
        }),
      { wrapper: wrap(client) },
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const activityUrl = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .find((u) => u.includes("/api/events"));
    expect(activityUrl).toBeDefined();
    // Order-independent assertion — URLSearchParams encodes deterministically
    // but the test stays robust if the internal key order changes.
    expect(activityUrl).toContain("chat_id=chat-trace-1");
    expect(activityUrl).toMatch(/category=tool_call(%2C|,)tool_result/);
  });

  it("emits no chat_id / category params when called without props (dashboard back-compat)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [] }));
    stubUnreadFetch(fetchMock);

    const { client } = makeClient();
    renderHook(() => useActivityStream(), { wrapper: wrap(client) });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const activityUrl = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .find((u) => u.includes("/api/events"));
    expect(activityUrl).toBeDefined();
    expect(activityUrl).not.toContain("chat_id=");
    expect(activityUrl).not.toContain("category=");
  });

  it("drops WS frames whose chat_id does not match", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [] }));
    stubUnreadFetch(fetchMock);

    const { client, push } = makeClient();
    const { result } = renderHook(
      () => useActivityStream({ chatId: "chat-A" }),
      { wrapper: wrap(client) },
    );

    await waitFor(() => expect(result.current.state).toBe("ready"));

    act(() => {
      // Other chat — must be filtered out.
      push({
        event: "activity_event",
        chat_id: "chat-B",
        category: "tool_call",
        agent: "port_scan",
        step: "other-chat",
        timestamp: "2026-05-10T12:00:00Z",
      });
      // Matching chat — must land.
      push({
        event: "activity_event",
        chat_id: "chat-A",
        category: "tool_call",
        agent: "port_scan",
        step: "this-chat",
        timestamp: "2026-05-10T12:00:01Z",
      });
    });

    await waitFor(() => expect(result.current.events.length).toBe(1));
    expect(result.current.events[0].chat_id).toBe("chat-A");
    expect(result.current.events[0].step).toBe("this-chat");
  });

  it("drops WS frames whose category is not in the filter set", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [] }));
    stubUnreadFetch(fetchMock);

    const { client, push } = makeClient();
    const { result } = renderHook(
      () =>
        useActivityStream({
          chatId: "chat-A",
          categories: ["tool_call"],
        }),
      { wrapper: wrap(client) },
    );

    await waitFor(() => expect(result.current.state).toBe("ready"));

    act(() => {
      // Thought in the same chat — filtered out by category.
      push({
        event: "activity_event",
        chat_id: "chat-A",
        category: "thought",
        agent: "orchestrator",
        step: "plan",
        timestamp: "2026-05-10T12:00:00Z",
      });
      // Tool call in the same chat — kept.
      push({
        event: "activity_event",
        chat_id: "chat-A",
        category: "tool_call",
        agent: "port_scan",
        step: "nmap",
        timestamp: "2026-05-10T12:00:01Z",
      });
    });

    await waitFor(() => expect(result.current.events.length).toBe(1));
    expect(result.current.events[0].category).toBe("tool_call");
  });
});
