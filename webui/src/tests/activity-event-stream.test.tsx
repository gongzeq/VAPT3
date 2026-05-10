import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityEventStream } from "@/components/ActivityEventStream";
import type { ActivityEvent } from "@/lib/types";

function row(overrides: Partial<ActivityEvent> = {}): ActivityEvent {
  return {
    id: "r-1",
    timestamp: "2026-05-10T12:00:00Z",
    level: "info",
    source: "weak_password",
    message: "running scan",
    task_id: null,
    chat_id: "chat-a",
    agent: "weak_password",
    step: "scan",
    category: "tool_call",
    duration_ms: 42,
    ...overrides,
  };
}

describe("ActivityEventStream", () => {
  it("renders a loading indicator when state is loading and no events yet", () => {
    render(<ActivityEventStream events={[]} state="loading" />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it("renders the empty state when ready with no events", () => {
    render(<ActivityEventStream events={[]} state="ready" />);
    expect(screen.getByText(/No events yet/i)).toBeInTheDocument();
  });

  it("renders events with level + source data attributes", () => {
    render(
      <ActivityEventStream
        state="ready"
        events={[
          row({ id: "a", level: "critical", source: "port_scan" }),
          row({ id: "b", level: "ok", source: "report", category: "tool_result" }),
        ]}
      />,
    );
    const rows = screen.getAllByTestId("activity-event-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-level", "critical");
    expect(rows[0]).toHaveAttribute("data-source", "port_scan");
    expect(rows[1]).toHaveAttribute("data-level", "ok");
  });

  it("shows a paused indicator + retry affordance when state is error", () => {
    const onRefresh = vi.fn();
    render(
      <ActivityEventStream
        events={[]}
        state="error"
        errorCode="network"
        onRefresh={onRefresh}
      />,
    );
    expect(screen.getByTestId("activity-live-indicator")).toHaveTextContent(
      /Paused/i,
    );
    expect(screen.getByText(/Network error/i)).toBeInTheDocument();
  });

  it("renders the live indicator in ready state", () => {
    render(<ActivityEventStream events={[row()]} state="ready" />);
    expect(screen.getByTestId("activity-live-indicator")).toHaveTextContent(
      /Live/i,
    );
  });
});
