import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteSession,
  fetchAssetRiskTopology,
  fetchAssetAutoManagement,
  fetchSessionMessages,
  listSessions,
  listSlashCommands,
  setApiTokenRefreshListener,
  setAssetAutoManagement,
  updateSettings,
} from "@/lib/api";

describe("webui API helpers", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ deleted: true, key: "websocket:chat-1", messages: [] }),
      }),
    );
  });

  it("percent-encodes websocket keys when fetching session history", async () => {
    await fetchSessionMessages("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/messages",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("percent-encodes websocket keys when deleting a session", async () => {
    await deleteSession("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/delete",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("reads and updates session asset auto-management state", async () => {
    await fetchAssetAutoManagement("tok", "websocket:chat-1");
    await setAssetAutoManagement("tok", "websocket:chat-1", true);

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/sessions/websocket%3Achat-1/asset-auto-management",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/sessions/websocket%3Achat-1/asset-auto-management?enabled=1",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("serializes asset risk topology filters", async () => {
    await fetchAssetRiskTopology("tok", {
      businessSystem: "CRM",
      subnet: "10.0.0.0/24",
      assetType: "业务",
      vulnerabilityIdentity: "CVE:CVE-2026-0001",
      candidateStatus: "candidate",
      recentScan: "scan-1",
      focusId: "asset:1",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/dashboard/asset-risk-topology?business_system=CRM&subnet=10.0.0.0%2F24&asset_type=%E4%B8%9A%E5%8A%A1&vulnerability_identity=CVE%3ACVE-2026-0001&candidate_status=candidate&recent_scan=scan-1&focus_id=asset%3A1",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("serializes settings updates as a narrow query string", async () => {
    await updateSettings("tok", {
      model: "openrouter/test",
      provider: "openrouter",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/settings/update?model=openrouter%2Ftest&provider=openrouter",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("maps generated session titles from the sessions list", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        sessions: [
          {
            key: "websocket:chat-1",
            created_at: "2026-05-01T10:00:00",
            updated_at: "2026-05-01T10:01:00",
            title: "优化 WebUI 标题",
          },
        ],
      }),
    } as Response);

    await expect(listSessions("tok")).resolves.toMatchObject([
      {
        key: "websocket:chat-1",
        title: "优化 WebUI 标题",
        preview: "",
      },
    ]);
  });

  it("maps slash command metadata from the commands endpoint", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        commands: [
          {
            command: "/history",
            title: "Show conversation history",
            description: "Print the last N messages.",
            icon: "history",
            arg_hint: "[n]",
          },
        ],
      }),
    } as Response);

    await expect(listSlashCommands("tok")).resolves.toEqual([
      {
        command: "/history",
        title: "Show conversation history",
        description: "Print the last N messages.",
        icon: "history",
        argHint: "[n]",
      },
    ]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/commands",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("notifies the app when a 401 refresh mints a replacement token", async () => {
    const listener = vi.fn();
    const cleanup = setApiTokenRefreshListener(listener);
    vi.mocked(fetch)
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({}),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          token: "fresh-token",
          ws_path: "/",
          expires_in: 300,
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ sessions: [] }),
      } as Response);

    try {
      await expect(listSessions("stale-token")).resolves.toEqual([]);
    } finally {
      cleanup();
    }

    expect(listener).toHaveBeenCalledWith("fresh-token");
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/sessions",
      expect.objectContaining({
        headers: { Authorization: "Bearer stale-token" },
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "/api/sessions",
      expect.objectContaining({
        headers: { Authorization: "Bearer fresh-token" },
      }),
    );
  });
});
