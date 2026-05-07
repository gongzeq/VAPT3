import * as React from "react";
import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { StatusPill } from "./_shared";

/**
 * Generic fallback renderer used for any skill that has no dedicated UI.
 * Shows tool name + collapsible JSON args / result.
 */
export const ToolCallCard: ToolCallContentPartComponent = ({ toolName, args, result }) => {
  const status = (result as { status?: string } | undefined)?.status ?? "running";
  return (
    <div className="my-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-text-secondary">tool · {toolName}</span>
        <StatusPill status={status} />
      </div>
      <details className="text-xs text-text-secondary">
        <summary className="cursor-pointer select-none hover:text-text-primary">参数 / 结果</summary>
        <pre className="mt-2 overflow-x-auto rounded bg-background/40 p-2 font-mono">
{JSON.stringify({ args, result }, null, 2)}
        </pre>
      </details>
    </div>
  );
};
