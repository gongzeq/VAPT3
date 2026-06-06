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
    <div className="my-2 rounded-lg border-l-4 border-alert-warning bg-alert-warning/10 p-3">
      <div className="flex items-center gap-2 mb-1">
        <Lightbulb className="h-4 w-4 text-alert-warning" />
        <span className="text-xs font-semibold text-alert-warning">
          {entry.agent_name}
        </span>
        <span className="text-xs text-muted-foreground ml-auto">{timeStr}</span>
      </div>
      <p className="text-sm text-foreground">{entry.text}</p>
    </div>
  );
}
