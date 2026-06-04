import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RightRail } from "@/components/RightRail";

vi.mock("@/components/AgentStatusPanel", () => ({
  AgentStatusPanel: () => <div>Agent status panel</div>,
}));

vi.mock("@/components/AssetsPanel", () => ({
  AssetsPanel: () => <div>Assets panel</div>,
}));

vi.mock("@/components/BlackboardPanel", () => ({
  BlackboardPanel: () => <div>Blackboard panel</div>,
}));

describe("RightRail", () => {
  it("does not render the trace tab in the tab list", () => {
    render(<RightRail session={null} />);

    expect(
      screen.getByRole("tab", { name: /黑板|blackboard/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /资产|assets/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /智能体|agents/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: /工作台|prompts/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: /追踪|trace/i }),
    ).not.toBeInTheDocument();
  });
});
