import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionHistory, useSessions } from "@/hooks/useSessions";
import * as api from "@/lib/api";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listSessions: vi.fn(),
    deleteSession: vi.fn(),
    fetchSessionMessages: vi.fn(),
  };
});

function fakeClient() {
  return {
    status: "open" as const,
    defaultChatId: null as string | null,
    onStatus: () => () => {},
    onError: () => () => {},
    onChat: () => () => {},
    sendMessage: vi.fn(),
    newChat: vi.fn(),
    attach: vi.fn(),
    connect: vi.fn(),
    close: vi.fn(),
    updateUrl: vi.fn(),
  };
}

function wrap(client: ReturnType<typeof fakeClient>) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider
        client={client as unknown as import("@/lib/secbot-client").SecbotClient}
        token="tok"
      >
        {children}
      </ClientProvider>
    );
  };
}

describe("useSessions", () => {
  beforeEach(() => {
    vi.mocked(api.listSessions).mockReset();
    vi.mocked(api.deleteSession).mockReset();
    vi.mocked(api.fetchSessionMessages).mockReset();
  });

  it("removes a session from the local list after delete succeeds", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Alpha",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Beta",
      },
    ]);
    vi.mocked(api.deleteSession).mockResolvedValue(true);

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(2));

    await act(async () => {
      await result.current.deleteChat("websocket:chat-a");
    });

    expect(api.deleteSession).toHaveBeenCalledWith("tok", "websocket:chat-a");
    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-b"]);
  });

  it("hydrates media_urls from historical user turns into UIMessage.images", async () => {
    // Round-trip check for the signed-media replay: the backend emits
    // ``media_urls`` on a historical user row and the hook must surface them
    // as ``images`` so the bubble can render the preview. Assistant turns
    // carry no media_urls and should not sprout an ``images`` field.
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-media",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "user",
          content: "what's this?",
          timestamp: "2026-04-20T10:00:00Z",
          media_urls: [
            { url: "/api/media/sig-1/payload-1", name: "snap.png" },
            { url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
          ],
        },
        {
          role: "assistant",
          content: "it's a cat",
          timestamp: "2026-04-20T10:00:01Z",
        },
        {
          role: "user",
          content: "follow-up without images",
          timestamp: "2026-04-20T10:01:00Z",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-media"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    const [first, second, third] = result.current.messages;
    expect(first.role).toBe("user");
    expect(first.images).toEqual([
      { url: "/api/media/sig-1/payload-1", name: "snap.png" },
      { url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
    ]);
    expect(first.media).toEqual([
      { kind: "image", url: "/api/media/sig-1/payload-1", name: "snap.png" },
      { kind: "image", url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
    ]);
    expect(second.role).toBe("assistant");
    expect(second.images).toBeUndefined();
    expect(third.role).toBe("user");
    expect(third.images).toBeUndefined();
  });

  it("hydrates historical assistant video media_urls into media attachments", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-video",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "clip ready",
          timestamp: "2026-04-20T10:00:01Z",
          media_urls: [
            { url: "/api/media/sig-v/payload-v", name: "clip.mp4" },
          ],
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-video"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages[0].role).toBe("assistant");
    expect(result.current.messages[0].images).toBeUndefined();
    expect(result.current.messages[0].media).toEqual([
      { kind: "video", url: "/api/media/sig-v/payload-v", name: "clip.mp4" },
    ]);
  });

  it("recovers agentName from sender_id on historical assistant messages", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-agent",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "orchestrator reply",
          timestamp: "2026-04-20T10:00:01Z",
        },
        {
          role: "assistant",
          content: "subagent result",
          timestamp: "2026-04-20T10:00:02Z",
          sender_id: "subagent",
        },
        {
          role: "assistant",
          content: "port scan done",
          timestamp: "2026-04-20T10:00:03Z",
          sender_id: "port_scan",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-agent"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const msgs = result.current.messages;
    expect(msgs).toHaveLength(3);
    expect(msgs[0].agentName).toBeUndefined();
    expect(msgs[1].agentName).toBe("subagent");
    expect(msgs[2].agentName).toBe("port_scan");
  });

  it("reconstructs tool_calls as embedded toolCalls instead of trace rows", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-tools",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "user",
          content: "scan it",
          timestamp: "2026-04-20T10:00:00Z",
        },
        {
          role: "assistant",
          content: "Starting scan...",
          timestamp: "2026-04-20T10:00:01Z",
          tool_calls: [
            {
              id: "call_1",
              type: "function",
              function: { name: "scan_port", arguments: '{"target":"1.2.3.4"}' },
            },
          ],
        },
        {
          role: "tool",
          content: "Port 80 open",
          tool_call_id: "call_1",
          name: "scan_port",
          timestamp: "2026-04-20T10:00:02Z",
        },
        {
          role: "assistant",
          content: "Done.",
          timestamp: "2026-04-20T10:00:03Z",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-tools"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const msgs = result.current.messages;
    // User + assistant (with toolCalls) + assistant = 3 messages, no trace row.
    expect(msgs).toHaveLength(3);
    expect(msgs[0].role).toBe("user");
    expect(msgs[1].role).toBe("assistant");
    expect(msgs[1].toolCalls).toHaveLength(1);
    expect(msgs[1].toolCalls?.[0].tool_name).toBe("scan_port");
    expect(msgs[1].toolCalls?.[0].tool_status).toBe("ok");
    expect(msgs[2].role).toBe("assistant");
  });

  it("marks historical tool_call as error when the tool result looks like a failure", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-tool-err",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "trying...",
          timestamp: "2026-04-20T10:00:01Z",
          tool_calls: [
            {
              id: "call_err",
              type: "function",
              function: { name: " risky_cmd", arguments: '{}' },
            },
          ],
        },
        {
          role: "tool",
          content: "Traceback: connection refused",
          tool_call_id: "call_err",
          name: "risky_cmd",
          timestamp: "2026-04-20T10:00:02Z",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-tool-err"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const tc = result.current.messages[0].toolCalls?.[0];
    expect(tc?.tool_status).toBe("error");
    expect(tc?.reason).toContain("Traceback");
  });

  it("keeps the session in the list when delete fails", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Alpha",
      },
    ]);
    vi.mocked(api.deleteSession).mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(1));

    await expect(
      act(async () => {
        await result.current.deleteChat("websocket:chat-a");
      }),
    ).rejects.toThrow("boom");

    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-a"]);
  });

  it("renders persisted agent_event messages as inline cards on replay", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-events",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "user",
          content: "scan it",
          timestamp: "2026-04-20T10:00:00Z",
        },
        {
          role: "assistant",
          content: "",
          timestamp: "2026-04-20T10:00:01Z",
          _kind: "agent_event",
          agent_event: {
            type: "thought",
            agent: "orchestrator",
            content: "I should spawn a port scanner.",
          },
          sender_id: "orchestrator",
        },
        {
          role: "assistant",
          content: "",
          timestamp: "2026-04-20T10:00:02Z",
          _kind: "agent_event",
          agent_event: {
            type: "subagent_spawned",
            task_id: "t1",
            label: "Port Scan",
            task_description: "scan ports",
          },
          sender_id: "port_scan",
        },
        {
          role: "assistant",
          content: "Done.",
          timestamp: "2026-04-20T10:00:03Z",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-events"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const msgs = result.current.messages;
    expect(msgs).toHaveLength(4);
    expect(msgs[0].role).toBe("user");

    expect(msgs[1].role).toBe("assistant");
    expect(msgs[1].kind).toBe("agent_event");
    expect(msgs[1].content).toBe("I should spawn a port scanner.");
    expect(msgs[1].agentName).toBe("orchestrator");
    expect(msgs[1].agentEvent?.type).toBe("thought");

    expect(msgs[2].role).toBe("assistant");
    expect(msgs[2].kind).toBe("agent_event");
    expect(msgs[2].content).toBe("🚀 子智能体「Port Scan」已启动");
    expect(msgs[2].agentName).toBe("port_scan");
    expect(msgs[2].agentEvent?.type).toBe("subagent_spawned");

    expect(msgs[3].role).toBe("assistant");
    expect(msgs[3].kind).toBeUndefined();
  });
});
