import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/ChatList";
import type { ChatSummary } from "@/lib/types";

describe("ChatList", () => {
  it("uses the first user message as the active session title", () => {
    const sessions: ChatSummary[] = [
      {
        key: "websocket:chat-title",
        channel: "websocket",
        chatId: "chat-title",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        title: "智能体回复内容",
        preview: "用户的第一句话",
      },
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:chat-title"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
      />,
    );

    const title = screen.getByText("用户的第一句话");
    expect(title).toHaveClass("truncate", "text-sm", "font-medium", "text-primary");
    const subtitle = screen.queryByText("智能体回复内容");
    if (subtitle) {
      expect(subtitle).not.toHaveClass("text-primary");
    }
  });
});
