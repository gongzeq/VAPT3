import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageBubble } from "@/components/MessageBubble";
import type { UIMessage } from "@/lib/types";

describe("MessageBubble", () => {
  it("renders user messages as right-aligned pills", () => {
    const message: UIMessage = {
      id: "u1",
      role: "user",
      content: "hello",
      createdAt: Date.now(),
    };

    const { container } = render(<MessageBubble message={message} />);
    const row = container.firstElementChild;
    const pill = screen.getByText("hello");

    expect(row).toHaveClass("justify-end", "flex");
    expect(pill).toHaveClass("rounded-2xl", "rounded-tr-sm");
    expect(screen.queryByRole("button", { name: "Copy reply" })).not.toBeInTheDocument();
  });

  it("copies completed assistant replies from the action row", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const message: UIMessage = {
      id: "a-copy",
      role: "assistant",
      content: "I can help with the next step.",
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy reply" }));

    expect(writeText).toHaveBeenCalledWith("I can help with the next step.");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Copied reply" })).toBeInTheDocument(),
    );
  });

  it("does not show copy actions for streaming placeholders", () => {
    const message: UIMessage = {
      id: "a-streaming",
      role: "assistant",
      content: "",
      isStreaming: true,
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    expect(screen.queryByRole("button", { name: "Copy reply" })).not.toBeInTheDocument();
  });

  it("renders tool calls on an otherwise empty streaming assistant row", () => {
    const message: UIMessage = {
      id: "a-tool-streaming",
      role: "assistant",
      content: "",
      isStreaming: true,
      agentName: "port_scan",
      createdAt: Date.now(),
      toolCalls: [
        {
          type: "tool_call",
          tool_call_id: "call_scan",
          tool_name: "scan_port",
          tool_args: { target: "1.2.3.4" },
          status: "running",
        },
      ],
    };

    render(<MessageBubble message={message} />);

    // 命令默认折叠在分组气泡内，需先展开才能看到具体工具调用。
    fireEvent.click(screen.getByRole("button", { name: /执行命令/ }));
    expect(screen.getByText("scan_port")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.queryByLabelText(/assistant is typing/i)).not.toBeInTheDocument();
  });

  it("renders tool call arguments from backend args fallback", () => {
    const message: UIMessage = {
      id: "a-tool-args-fallback",
      role: "assistant",
      content: "",
      agentName: "vuln_scan",
      createdAt: Date.now(),
      toolCalls: [
        {
          type: "tool_call",
          tool_call_id: "call_scan",
          tool_name: "sqlmap-detect",
          args: { url: "http://target.test/sqli.php?id=1" },
          status: "ok",
        },
      ],
    };

    render(<MessageBubble message={message} />);

    // 先展开 subagent 命令分组，再展开单条工具调用查看参数。
    fireEvent.click(screen.getByRole("button", { name: /执行命令/ }));
    fireEvent.click(screen.getByRole("button", { name: /sqlmap-detect/i }));
    // URL 同时出现在按钮摘要 span 和展开详情 pre 中，用 getAllByText 匹配
    expect(screen.getAllByText(/target\.test\/sqli\.php/).length).toBeGreaterThan(0);
    expect(screen.queryByText("无参数")).not.toBeInTheDocument();
  });

  it("renders trace messages as collapsible tool groups", () => {
    const message: UIMessage = {
      id: "t1",
      role: "tool",
      kind: "trace",
      content: 'search "hk weather"',
      traces: ['weather("get")', 'search "hk weather"'],
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);
    const toggle = screen.getByRole("button", { name: /used 2 tools/i });

    expect(screen.queryByText('weather("get")')).not.toBeInTheDocument();
    expect(screen.queryByText('search "hk weather"')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText('weather("get")')).toBeInTheDocument();
    expect(screen.getByText('search "hk weather"')).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByText('weather("get")')).not.toBeInTheDocument();
  });

  it("renders orchestrator plan agent events", () => {
    const message: UIMessage = {
      id: "plan-1",
      role: "assistant",
      kind: "agent_event",
      content: "编排计划：2 步",
      createdAt: Date.now(),
      agentEvent: {
        type: "orchestrator_plan",
        agent: "orchestrator",
        steps: [
          { title: "Asset discovery", detail: "Find live hosts." },
          { title: "Report" },
        ],
      },
    };

    render(<MessageBubble message={message} />);

    expect(screen.getByText("编排计划")).toBeInTheDocument();
    expect(screen.getByText("Asset discovery")).toBeInTheDocument();
    expect(screen.getByText("Find live hosts.")).toBeInTheDocument();
    expect(screen.getByText("Report")).toBeInTheDocument();
  });

  it("hides the whole agent event row for asset_push tool calls", () => {
    const message: UIMessage = {
      id: "asset-push-tool",
      role: "assistant",
      kind: "agent_event",
      content: "⚙️ asset_push 执行中…",
      agentName: "crawl_web",
      createdAt: Date.now(),
      agentEvent: {
        type: "tool_call",
        tool_name: "asset_push",
        tool_call_id: "call_asset_push",
        tool_status: "running",
        tool_args: { kind: "url" },
      },
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(container.firstChild).toBeNull();
    expect(screen.queryByText(/asset_push/)).not.toBeInTheDocument();
  });

  it("uses the agent name as the subagent lifecycle title", () => {
    const message: UIMessage = {
      id: "subagent-done",
      role: "assistant",
      kind: "agent_event",
      content: "✅ 子智能体「port_scan」已完成",
      agentName: "port_scan",
      createdAt: Date.now(),
      agentEvent: {
        type: "subagent_done",
        agent_name: "port_scan",
        task_id: "t1",
        label: "The subagent response was accidentally placed here.",
        status: "ok",
        result: "Actual result body",
      },
    };

    render(<MessageBubble message={message} />);

    const title = screen
      .getAllByText("Port Scan")
      .find((el) => el.classList.contains("font-medium"));
    if (!title) throw new Error("Missing subagent lifecycle title");
    expect(title).toHaveClass("text-foreground");
    expect(screen.queryByText("The subagent response was accidentally placed here.")).not.toBeInTheDocument();
    // subagent_done 默认折叠结果，需先展开
    fireEvent.click(screen.getByRole("button", { name: /已完成/ }));
    expect(screen.getByText("Actual result body")).not.toHaveClass("text-foreground");
  });

  it("renders video media as an inline player", () => {
    const message: UIMessage = {
      id: "a1",
      role: "assistant",
      content: "here is the clip",
      createdAt: Date.now(),
      media: [
        {
          kind: "video",
          url: "/api/media/sig/payload",
          name: "demo.mp4",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(screen.getByText("here is the clip")).toBeInTheDocument();
    const video = screen.getByLabelText(/video attachment/i);
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("src", "/api/media/sig/payload");
    expect(container.querySelector("video[controls]")).toBeInTheDocument();
  });
});
