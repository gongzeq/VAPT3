import * as React from "react";
import {
  AssistantRuntimeProvider,
  Thread,
} from "@assistant-ui/react";

import { useSecbotRuntime, type SecbotRuntimeOptions } from "./runtime";
import { SKILL_RENDERERS } from "./tool-ui";
import { ToolCallCard } from "./renderers/tool-call-card";

/**
 * Top-level chat surface for secbot.
 *
 * Wires:
 *   - SecbotChatRuntime → /api/ws (orchestrator + skill streaming)
 *   - assistant-ui Thread (canonical chat layout: messages + composer)
 *   - per-skill tool-call renderers from `tool-ui.ts`
 *   - generic <ToolCallCard> as the fallback for any unknown skill
 */
export function SecbotThread(props: SecbotRuntimeOptions = {}) {
  const runtime = useSecbotRuntime(props);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread
        tools={SKILL_RENDERERS}
        components={{ ToolFallback: ToolCallCard }}
      />
    </AssistantRuntimeProvider>
  );
}
