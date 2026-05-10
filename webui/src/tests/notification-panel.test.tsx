import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { NotificationPanel } from "@/components/NotificationPanel";
import type { Notification } from "@/lib/types";
import type { UseNotificationsResult } from "@/hooks/useNotifications";

function makeRow(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n-1",
    kind: "critical_vuln",
    title: "发现严重漏洞",
    body: "host 10.0.0.1 上检测到 CVE-2025-0001",
    created_at: "2026-05-10T12:00:00Z",
    read: false,
    link: null,
    ...overrides,
  };
}

function makeController(
  overrides: Partial<UseNotificationsResult> = {},
): UseNotificationsResult {
  return {
    items: [],
    state: "ready",
    errorCode: null,
    refresh: vi.fn().mockResolvedValue(undefined),
    markRead: vi.fn().mockResolvedValue(undefined),
    markAllRead: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function renderPanel(
  controller: UseNotificationsResult,
  props: { open?: boolean; onClose?: () => void } = {},
) {
  return render(
    <MemoryRouter>
      <NotificationPanel
        token="tok"
        open={props.open ?? true}
        onClose={props.onClose}
        controller={controller}
      />
    </MemoryRouter>,
  );
}

describe("NotificationPanel", () => {
  it("renders the empty state when no items are present", () => {
    renderPanel(makeController({ items: [], state: "ready" }));
    expect(screen.getByText(/No notifications/i)).toBeInTheDocument();
  });

  it("renders rows with unread style and title/body", () => {
    const controller = makeController({
      items: [
        makeRow({ id: "a", title: "严重漏洞 A", read: false }),
        makeRow({ id: "b", title: "扫描完成", read: true, kind: "scan_completed" }),
      ],
    });
    renderPanel(controller);

    const rows = screen.getAllByTestId("notification-item");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-read", "false");
    expect(rows[1]).toHaveAttribute("data-read", "true");
    expect(rows[0]).toHaveTextContent("严重漏洞 A");
  });

  it("calls markRead + onClose when a row is clicked", async () => {
    const onClose = vi.fn();
    const controller = makeController({
      items: [makeRow({ id: "a", read: false, link: null })],
    });
    renderPanel(controller, { onClose });

    fireEvent.click(screen.getAllByTestId("notification-item")[0]);

    await waitFor(() => {
      expect(controller.markRead).toHaveBeenCalledWith("a");
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("invokes markAllRead when the button is clicked and disables at zero unread", async () => {
    const controller = makeController({
      items: [makeRow({ id: "a", read: false })],
    });
    const { rerender } = renderPanel(controller);

    const btn = screen.getByTestId("notification-mark-all") as HTMLButtonElement;
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    await waitFor(() => {
      expect(controller.markAllRead).toHaveBeenCalled();
    });

    // After all-read, the button disables.
    rerender(
      <MemoryRouter>
        <NotificationPanel
          token="tok"
          open
          controller={makeController({
            items: [makeRow({ id: "a", read: true })],
          })}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("notification-mark-all")).toBeDisabled();
  });

  it("shows an error state with a retry affordance when errorCode is set", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderPanel(
      makeController({
        items: [],
        state: "error",
        errorCode: "network",
        refresh,
      }),
    );

    expect(screen.getByText(/Network error/i)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /Retry/i });
    fireEvent.click(retry);
    expect(refresh).toHaveBeenCalled();
  });

  it("refetches when the open prop transitions from closed → open", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const controller = makeController({
      items: [makeRow({ read: true })],
      refresh,
    });
    const { rerender } = render(
      <MemoryRouter>
        <NotificationPanel
          token="tok"
          open={false}
          controller={controller}
        />
      </MemoryRouter>,
    );
    expect(refresh).not.toHaveBeenCalled();
    rerender(
      <MemoryRouter>
        <NotificationPanel
          token="tok"
          open
          controller={controller}
        />
      </MemoryRouter>,
    );
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });
});
