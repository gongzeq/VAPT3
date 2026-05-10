import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useActivityStream } from "@/hooks/useActivityStream";
import { ClientProvider } from "@/providers/ClientProvider";
import type { SecbotClient } from "@/lib/secbot-client";
import type { ActivityEvent, ActivityEventFrame } from "@/lib/types";

type ActivityHandler = (frame: ActivityEventFrame) => void;

/** Minimal SecbotClient double that only implements what the hook uses. */
function makeClient(): {
  client: SecbotClient;
  push: (frame: ActivityEventFrame) => void;
  handlers: Set<ActivityHandler>;
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
  function push(frame: ActivityEventFrame) {
    for (const h of handlers) h(frame);
  }
  return { client, push, handlers };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeSeedRow(overrides: Partial<ActivityEvent> = {}): ActivityEvent {
  return {
    id: "rest-1",
    timestamp: "2026-05-10T12:00:00Z",
    level: "info",
    source: "orchestrator",
    message: "seed row",
    task_id: null,
    chat_id: "chat-a",
    agent: "orchestrator",
    step: null,
    category: null,
    duration_ms: null,
    ...overrides,
  };
}

describe("useActivityStream", () => {
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

  it("seeds from REST and sorts newest-first", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          makeSeedRow({ id: "older", timestamp: "2026-05-10T11:00:00Z" }),
          makeSeedRow({ id: "newer", timestamp: "2026-05-10T12:00:00Z" }),
        ],
      }),
    );
    // useUnreadCount also fires a fetch from ClientProvider — stub it out.
    fetchMock.mockResolvedValue(
      jsonResponse({
        items: [],
        total: 0,
        limit: 1,
        offset: 0,
        unread_count: 0,
      }),
    );

    const { client } = makeClient();
    const { result } = renderHook(() => useActivityStream(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(result.current.events.map((e) => e.id)).toEqual(["newer", "older"]);
    const activityUrl = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .find((u) => u.includes("/api/events"));
    expect(activityUrl).toMatch(/\/api\/events\?/);
  });

  it("prepends WS frames and caps the list", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [] }),
    );
    fetchMock.mockResolvedValue(
      jsonResponse({
        items: [],
        total: 0,
        limit: 1,
        offset: 0,
        unread_count: 0,
      }),
    );
    const { client, push } = makeClient();
    const { result } = renderHook(() => useActivityStream(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.state).toBe("ready"));

    act(() => {
      push({
        event: "activity_event",
        chat_id: "chat-a",
        category: "tool_call",
        agent: "weak_password",
        step: "scan-1",
        timestamp: "2026-05-10T12:05:00Z",
        duration_ms: 12,
      });
    });

    await waitFor(() => expect(result.current.events.length).toBe(1));
    const ev = result.current.events[0];
    expect(ev.id).toBe("ws|chat-a|2026-05-10T12:05:00Z|scan-1");
    expect(ev.source).toBe("weak_password");
    expect(ev.category).toBe("tool_call");
    expect(ev.duration_ms).toBe(12);
  });

  it("surfaces an error state on a failing REST fetch and recovers on refresh", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 500 }));
    fetchMock.mockResolvedValue(
      jsonResponse({
        items: [],
        total: 0,
        limit: 1,
        offset: 0,
        unread_count: 0,
      }),
    );
    const { client } = makeClient();
    const { result } = renderHook(() => useActivityStream(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.errorCode).toBe("500");

    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [makeSeedRow()] }));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.state).toBe("ready");
    expect(result.current.errorCode).toBeNull();
    expect(result.current.events).toHaveLength(1);
  });

  it("deduplicates events by id (WS → REST overlap is collapsed)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          makeSeedRow({
            id: "ws|chat-a|2026-05-10T12:00:00Z|step-1",
            source: "weak_password",
            level: "critical",
          }),
        ],
      }),
    );
    fetchMock.mockResolvedValue(
      jsonResponse({
        items: [],
        total: 0,
        limit: 1,
        offset: 0,
        unread_count: 0,
      }),
    );
    const { client, push } = makeClient();
    const { result } = renderHook(() => useActivityStream(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.state).toBe("ready"));

    act(() => {
      push({
        event: "activity_event",
        chat_id: "chat-a",
        category: "tool_call",
        agent: "weak_password",
        step: "step-1",
        timestamp: "2026-05-10T12:00:00Z",
      });
    });

    // One row total — the WS frame shared an id with the REST seed, so it
    // overwrote rather than duplicated. REST seed was committed first, so
    // the WS "last write wins" downgrades level to ``info``.
    expect(result.current.events).toHaveLength(1);
  });
});
