import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useUnreadCount } from "@/hooks/useUnreadCount";

function mockNotificationsResponse(unreadCount: number) {
  return {
    ok: true,
    json: async () => ({
      items: [],
      total: 0,
      limit: 1,
      offset: 0,
      unread_count: unreadCount,
    }),
  } as Response;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useUnreadCount", () => {
  it("seeds the badge from the mount fetch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockNotificationsResponse(3)),
    );
    const { result, unmount } = renderHook(() =>
      useUnreadCount("tok", { intervalMs: 60_000 }),
    );
    await waitFor(() => {
      expect(result.current.unreadCount).toBe(3);
    });
    unmount();
  });

  it("optimistic decrement clamps at zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockNotificationsResponse(0)),
    );
    const { result, unmount } = renderHook(() =>
      useUnreadCount("tok", { intervalMs: 60_000 }),
    );
    await waitFor(() => {
      expect(result.current.unreadCount).toBe(0);
    });
    act(() => {
      result.current.decrement(5);
    });
    expect(result.current.unreadCount).toBe(0);
    unmount();
  });

  it("optimistic reset forces the badge to zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockNotificationsResponse(4)),
    );
    const { result, unmount } = renderHook(() =>
      useUnreadCount("tok", { intervalMs: 60_000 }),
    );
    await waitFor(() => {
      expect(result.current.unreadCount).toBe(4);
    });
    act(() => {
      result.current.reset();
    });
    expect(result.current.unreadCount).toBe(0);
    unmount();
  });

  it("drops stale responses arriving after a newer fetch has committed", async () => {
    // Race: the first fetch hangs; a newer one resolves first with
    // unread_count=9. The hook's monotonic request-id must discard the
    // late first response when it finally settles.
    let resolveFirst: ((res: Response) => void) | null = null;
    const fetchMock = vi.fn<(...args: unknown[]) => Promise<Response>>();
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveFirst = resolve;
        }),
    );
    fetchMock.mockResolvedValueOnce(mockNotificationsResponse(9));
    vi.stubGlobal("fetch", fetchMock);

    const { result, unmount } = renderHook(() =>
      useUnreadCount("tok", { intervalMs: 60_000 }),
    );

    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.unreadCount).toBe(9);

    await act(async () => {
      resolveFirst?.(mockNotificationsResponse(1));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.unreadCount).toBe(9);
    unmount();
  });

  it("skips polling when token is null", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockNotificationsResponse(0));
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = renderHook(() =>
      useUnreadCount(null, { intervalMs: 30 }),
    );
    await flush();
    await new Promise((r) => setTimeout(r, 80));
    expect(fetchMock).not.toHaveBeenCalled();
    unmount();
  });

  it("re-polls on the interval while the tab is visible", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(mockNotificationsResponse(1))
        .mockResolvedValue(mockNotificationsResponse(5)),
    );
    const { result, unmount } = renderHook(() =>
      useUnreadCount("tok", { intervalMs: 50 }),
    );
    await waitFor(
      () => {
        expect(result.current.unreadCount).toBe(5);
      },
      { timeout: 1_000 },
    );
    unmount();
  });

  it("stops polling when the document becomes hidden and resumes on visible", async () => {
    // This test mutates document.hidden. It is placed last in the suite
    // so any lingering side-effect (property descriptor swap, pending
    // timers) cannot cascade into the earlier, simpler assertions.
    let currentUnread = 2;
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(mockNotificationsResponse(currentUnread)),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { result, unmount } = renderHook(() =>
      useUnreadCount("tok", { intervalMs: 40 }),
    );
    await waitFor(() => {
      expect(result.current.unreadCount).toBe(2);
    });

    const hiddenGetter = vi
      .spyOn(document, "hidden", "get")
      .mockReturnValue(true);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const callsWhenHidden = fetchMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 120));
    expect(fetchMock.mock.calls.length).toBe(callsWhenHidden);

    currentUnread = 7;
    hiddenGetter.mockReturnValue(false);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => {
      expect(result.current.unreadCount).toBe(7);
    });
    hiddenGetter.mockRestore();
    unmount();
  });
});
