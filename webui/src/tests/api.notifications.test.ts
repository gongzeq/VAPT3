import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  fetchActivityEvents,
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";

describe("webui notification / activity API helpers", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({}),
      }),
    );
  });

  it("serialises fetchNotifications with unread + limit + offset", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        unread_count: 0,
      }),
    } as Response);

    await fetchNotifications("tok", { unread: true, limit: 50, offset: 0 });
    expect(fetch).toHaveBeenCalledWith(
      "/api/notifications?unread=1&limit=50&offset=0",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("omits the query string when no options are passed", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        unread_count: 0,
      }),
    } as Response);

    await fetchNotifications("tok");
    expect(fetch).toHaveBeenCalledWith(
      "/api/notifications",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("returns the parsed payload for fetchNotifications", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        items: [
          {
            id: "n-1",
            kind: "critical_vuln",
            title: "严重漏洞",
            body: "SSH root 弱口令",
            created_at: "2026-05-10T12:00:00Z",
            read: false,
            link: "/tasks/T-1",
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
        unread_count: 1,
      }),
    } as Response);

    await expect(
      fetchNotifications("tok", { unread: true, limit: 1 }),
    ).resolves.toMatchObject({
      unread_count: 1,
      items: [{ id: "n-1", kind: "critical_vuln", read: false }],
    });
  });

  it("surfaces HTTP failures as ApiError (non-2xx short-circuits)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    } as Response);

    await expect(fetchNotifications("tok")).rejects.toBeInstanceOf(ApiError);
  });

  it("percent-encodes notification ids on mark-as-read", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: "n 1/a", read: true }),
    } as Response);

    await expect(markNotificationRead("tok", "n 1/a")).resolves.toEqual({
      id: "n 1/a",
      read: true,
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/notifications/n%201%2Fa/read",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("hits read-all (note: GET, not POST — websockets lib constraint)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ updated: 4 }),
    } as Response);

    await expect(markAllNotificationsRead("tok")).resolves.toEqual({
      updated: 4,
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/notifications/read-all",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("forwards since + limit to fetchActivityEvents", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    } as Response);

    await fetchActivityEvents("tok", {
      since: "2026-05-10T11:55:00Z",
      limit: 100,
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/events?since=2026-05-10T11%3A55%3A00Z&limit=100",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });
});
