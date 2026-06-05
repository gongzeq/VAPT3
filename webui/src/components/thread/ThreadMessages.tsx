import { useMemo } from "react";
import { MessageBubble } from "@/components/MessageBubble";
import type { UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
}

/**
 * Group messages into "turns". A turn starts with a user message and
 * includes all subsequent non-user messages (assistant, trace, agent_event)
 * until the next user message. If the conversation starts with non-user
 * messages (e.g. initial agent events), they form their own turn.
 */
function groupIntoTurns(messages: UIMessage[]): UIMessage[][] {
  const turns: UIMessage[][] = [];
  let current: UIMessage[] = [];

  for (const msg of messages) {
    if (msg.role === "user" && current.length > 0) {
      turns.push(current);
      current = [];
    }
    current.push(msg);
  }
  if (current.length > 0) turns.push(current);
  return turns;
}

export function ThreadMessages({ messages }: ThreadMessagesProps) {
  const turns = useMemo(() => groupIntoTurns(messages), [messages]);

  return (
    <div className="flex w-full flex-col gap-6">
      {turns.map((turn) => (
        <div
          key={turn[0].id}
          className="rounded-xl border border-border/30 bg-card/50 px-5 py-4 backdrop-blur-sm"
        >
          <div className="flex flex-col gap-4">
            {turn.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
