import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssetsPanel } from "@/components/AssetsPanel";
import type { SecbotClient } from "@/lib/secbot-client";
import type { InboundEvent } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

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

describe("AssetsPanel", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps live asset_pushed rows when the HTTP replay resolves later empty", async () => {
    let resolveAssets!: (response: Response) => void;
    const assetsPromise = new Promise<Response>((resolve) => {
      resolveAssets = resolve;
    });
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/assets")) {
        return assetsPromise;
      }
      return Promise.resolve(jsonResponse({ unread_count: 0 }));
    });

    const fake = makeClient();
    const Wrapper = wrap(fake.client);
    render(
      <Wrapper>
        <AssetsPanel chatId="chat-a" />
      </Wrapper>,
    );

    act(() => {
      fake.emit("chat-a", {
        event: "agent_event",
        chat_id: "chat-a",
        type: "asset_pushed",
        payload: {
          type: "asset_pushed",
          id: 1,
          kind: "port",
          agent_name: "port_scan",
          payload: { host: "10.0.0.5", port: 80, service: "http" },
          created_at: 1715600300,
        },
        timestamp: "2026-05-13T01:02:00Z",
      });
    });

    expect(screen.getByText(/10\.0\.0\.5:80 \(http\)/)).toBeInTheDocument();

    await act(async () => {
      resolveAssets(
        jsonResponse({
          chat_id: "chat-a",
          entries: [],
          latest_id: 0,
          counts: {},
        }),
      );
      await assetsPromise;
    });

    expect(screen.getByText(/10\.0\.0\.5:80 \(http\)/)).toBeInTheDocument();
  });
});
