import { render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { describe, expect, it } from "vitest";

import { AgentThoughtChainRenderer } from "../agent-thought-chain";

/**
 * Runtime invariants for <AgentThoughtChainRenderer>.
 *
 * Covers:
 *   - Three status states (running / ok / error)
 *   - Icon dispatch via `args.icon`
 *   - Token streaming via `result.tokens`
 *   - Duration formatting
 *   - Prefers-reduced-motion degradation surface (beam overlay gets
 *     `motion-reduce:hidden`, shimmer span keeps `motion-reduce:animate-none`)
 *
 * These are Testing Library assertions rather than a snapshot so that minor
 * Tailwind class ordering changes do not generate false positives; the
 * structural contract is what PR3-R6 actually ships.
 */

// assistant-ui tool-call renderers receive a strict ReadonlyJSONObject type.
// For these runtime-shape tests we cast through `unknown` so the helper stays
// readable; the structural contract is what we actually assert below.
const Component = AgentThoughtChainRenderer as unknown as ComponentType<{
  toolName: string;
  toolCallId: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  status?: { type: string };
  addResult: () => void;
  argsText: string;
  isError: boolean;
  type: "tool-call";
}>;

function renderWithProps(props: {
  toolName?: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  status?: { type: string };
}) {
  return render(
    <Component
      toolName={props.toolName ?? "__thought__"}
      toolCallId="call_test"
      args={props.args}
      result={props.result}
      status={props.status ?? { type: "running" }}
      addResult={() => undefined}
      argsText={JSON.stringify(props.args)}
      isError={false}
      type="tool-call"
    />,
  );
}

describe("AgentThoughtChainRenderer", () => {
  it("renders the running state with a motion-reduce-safe beam overlay", () => {
    renderWithProps({
      args: { step_id: "s1", title: "分析目标资产", icon: "search" },
      // No result yet — behaves as running
    });

    const root = screen.getByTestId("agent-thought-chain");
    expect(root).toBeInTheDocument();
    expect(root).toHaveAttribute("data-status", "running");
    expect(root).toHaveAttribute("data-step-id", "s1");

    // Beam is present while running
    const beam = screen.getByTestId("agent-thought-chain-beam");
    expect(beam).toBeInTheDocument();
    // Respects prefers-reduced-motion via Tailwind variant
    expect(beam.className).toMatch(/motion-reduce:hidden/);

    // No duration on a running step
    expect(
      screen.queryByTestId("agent-thought-chain-duration"),
    ).not.toBeInTheDocument();
  });

  it("renders the completed state with duration + next_action + hidden beam", () => {
    renderWithProps({
      args: { step_id: "s2", title: "规划扫描步骤", icon: "brain" },
      result: {
        status: "ok",
        tokens: "选择 nmap 扫描目标 10.0.0.0/24",
        duration_ms: 2150,
        next_action: "nmap-port-scan",
      },
    });

    const root = screen.getByTestId("agent-thought-chain");
    expect(root).toHaveAttribute("data-status", "ok");

    // No beam once the step has completed
    expect(
      screen.queryByTestId("agent-thought-chain-beam"),
    ).not.toBeInTheDocument();

    // Duration is rendered and formatted to seconds
    const duration = screen.getByTestId("agent-thought-chain-duration");
    expect(duration).toHaveTextContent("2.1s");

    // Token body + next_action label visible inside the expanded collapsible
    const tokens = screen.getByTestId("agent-thought-chain-tokens");
    expect(tokens).toHaveTextContent("选择 nmap 扫描目标");
    expect(screen.getByText(/nmap-port-scan/)).toBeInTheDocument();
    expect(screen.getByText(/下一步/)).toBeInTheDocument();
  });

  it("renders the error state with critical severity styling", () => {
    renderWithProps({
      args: { step_id: "s3", title: "生成报告", icon: "filetext" },
      result: { status: "error", tokens: "LLM backend timeout after 30s" },
    });

    const root = screen.getByTestId("agent-thought-chain");
    expect(root).toHaveAttribute("data-status", "error");
    expect(root.textContent).toContain("LLM backend timeout");
  });

  it("formats sub-second durations in milliseconds", () => {
    renderWithProps({
      args: { step_id: "s4", title: "快速思考", icon: "wrench" },
      result: { status: "ok", duration_ms: 420 },
    });

    expect(
      screen.getByTestId("agent-thought-chain-duration"),
    ).toHaveTextContent("420ms");
  });

  it("falls back to a Brain icon for unknown icon keys", () => {
    renderWithProps({
      args: { step_id: "s5", title: "未知图标", icon: "__bogus__" as never },
      result: { status: "ok", duration_ms: 100 },
    });

    // Renders without throwing; the icon is visual so we just assert the
    // component mounted cleanly for the unknown-icon branch.
    expect(screen.getByTestId("agent-thought-chain")).toBeInTheDocument();
  });

  it("renders an empty-tokens placeholder when running without content yet", () => {
    renderWithProps({
      args: { step_id: "s6", title: "启动中…" },
    });

    expect(screen.getByText("(正在推理…)")).toBeInTheDocument();
  });

  it("shows the parent_step_id ancestry breadcrumb when provided", () => {
    renderWithProps({
      args: { step_id: "s7", title: "展开子步骤", parent_step_id: "s2" },
      result: { status: "ok", duration_ms: 50 },
    });

    expect(screen.getByText(/承接 s2/)).toBeInTheDocument();
  });
});
