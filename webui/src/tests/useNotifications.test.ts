import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNotifications } from "@/hooks/useNotifications";
import type { NotificationListResponse } from "@/lib/types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeListBody(
  overrides: Partial<NotificationListResponse> = {},
): NotificationListResponse {
  return {
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
    unread_count: 0,
    ...overrides,
  };
}

describe("useNotifications", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetches and exposes items on mount when a token is present", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListBody({
          items: [
            {
              id: "a",
              kind: "critical_vuln",
              title: "漏洞 A",
              body: "",
              created_at: "2026-05-10T12:00:00Z",
              read: false,
              link: null,
            },
          ],
          total: 1,
          unread_count: 1,
        }),
      ),
    );

    const { result } = renderHook(() => useNotifications("tok"));

    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });
    expect(result.current.items).toHaveLength(1);
    expect(result.current.items[0].id).toBe("a");
    // URL includes limit and NOT unread (panel loads both read and unread).
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/notifications?");
    expect(url).toContain("limit=20");
    expect(url).not.toContain("unread=");
  });

  it("exposes error + errorCode on a failing fetch and recovers on refresh", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 500 }));

    const { result } = renderHook(() => useNotifications("tok"));

    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.errorCode).toBe("500");

    fetchMock.mockResolvedValueOnce(
      jsonResponse(makeListBody({ items: [], total: 0 })),
    );
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.state).toBe("ready");
    expect(result.current.errorCode).toBeNull();
  });

  it("marks a row read optimistically and calls onDecrement", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListBody({
          items: [
            {
              id: "a",
              kind: "critical_vuln",
              title: "A",
              body: "",
              created_at: "2026-05-10T12:00:00Z",
              read: false,
              link: null,
            },
          ],
          total: 1,
          unread_count: 1,
        }),
      ),
    );
    // mark-read response
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "a", read: true }),
    );

    const onDecrement = vi.fn();
    const { result } = renderHook(() =>
      useNotifications("tok", { onDecrement }),
    );
    await waitFor(() => expect(result.current.state).toBe("ready"));

    await act(async () => {
      await result.current.markRead("a");
    });

    expect(result.current.items[0].read).toBe(true);
    expect(onDecrement).toHaveBeenCalledWith(1);
    // Second call should be the mark-read endpoint.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      "/api/notifications/a/read",
    );
  });

  it("does not re-decrement when markRead is called on an already-read row", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListBody({
          items: [
            {
              id: "a",
              kind: "scan_completed",
              title: "A",
              body: "",
              created_at: "2026-05-10T12:00:00Z",
              read: true,
              link: null,
            },
          ],
          total: 1,
          unread_count: 0,
        }),
      ),
    );

    const onDecrement = vi.fn();
    const { result } = renderHook(() =>
      useNotifications("tok", { onDecrement }),
    );
    await waitFor(() => expect(result.current.state).toBe("ready"));

    await act(async () => {
      await result.current.markRead("a");
    });

    expect(onDecrement).not.toHaveBeenCalled();
    // Only the initial fetch happened; no mark-read network call.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("marks all rows read and calls onReset only when there were unread items", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListBody({
          items: [
            {
              id: "a",
              kind: "critical_vuln",
              title: "A",
              body: "",
              created_at: "2026-05-10T12:00:00Z",
              read: false,
              link: null,
            },
            {
              id: "b",
              kind: "scan_completed",
              title: "B",
              body: "",
              created_at: "2026-05-10T12:01:00Z",
              read: true,
              link: null,
            },
          ],
          total: 2,
          unread_count: 1,
        }),
      ),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ updated: 1 }));

    const onReset = vi.fn();
    const { result } = renderHook(() =>
      useNotifications("tok", { onReset }),
    );
    await waitFor(() => expect(result.current.state).toBe("ready"));

    await act(async () => {
      await result.current.markAllRead();
    });

    expect(result.current.items.every((n) => n.read)).toBe(true);
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      "/api/notifications/read-all",
    );
  });

  it("keeps the hook idle when token is null", async () => {
    const { result } = renderHook(() => useNotifications(null));
    // Give any potential scheduled effects a chance to run.
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.state).toBe("idle");
    expect(result.current.items).toEqual([]);
  });

  it("caps items at NOTIFICATION_PANEL_LIMIT even if backend returns more", async () => {
    const bigList = Array.from({ length: 50 }, (_, i) => ({
      id: `n${i}`,
      kind: "scan_completed",
      title: `row ${i}`,
      body: "",
      created_at: "2026-05-10T12:00:00Z",
      read: false,
      link: null,
    }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(makeListBody({ items: bigList, total: 50, unread_count: 50 })),
    );

    const { result } = renderHook(() => useNotifications("tok"));
    await waitFor(() => expect(result.current.state).toBe("ready"));
    expect(result.current.items).toHaveLength(20);
  });
});
