import { Lightbulb } from "lucide-react";
import type { BlackboardEntry } from "../lib/types";

interface BlackboardCardProps {
  entry: BlackboardEntry;
}

export function BlackboardCard({ entry }: BlackboardCardProps) {
  const timeStr = entry.timestamp
    ? new Date(entry.timestamp * 1000).toLocaleTimeString()
    : "";

  return (
    <div className="my-2 rounded-lg border-l-4 border-amber-500 bg-amber-500/10 p-3">
      <div className="flex items-center gap-2 mb-1">
        <Lightbulb className="h-4 w-4 text-amber-500" />
        <span className="text-xs font-semibold text-amber-400">
          {entry.agent_name}
        </span>
        <span className="text-xs text-zinc-500 ml-auto">{timeStr}</span>
      </div>
      <p className="text-sm text-zinc-200">{entry.text}</p>
    </div>
  );
}
