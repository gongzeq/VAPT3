import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { listAgents, deleteAgent } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";
import type { AgentInfo } from "@/lib/api";

interface AgentListProps {
  onEdit: (name: string) => void;
  onCreate: () => void;
}

export function AgentList({ onEdit, onCreate }: AgentListProps) {
  const { token } = useClient();
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAgents(token)
      .then((data) => {
        if (!cancelled) setAgents(data);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [token]);

  useEffect(() => load(), [load]);

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete agent "${name}"? This cannot be undone.`)) return;
    try {
      await deleteAgent(token, name);
      setAgents((prev) => prev.filter((a) => a.name !== name));
    } catch (err) {
      window.alert(`Delete failed: ${(err as Error).message}`);
    }
  };

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading agents...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border border-border/60 bg-card/80 p-4">
        <p className="text-sm">
          Failed to load agents: <span className="font-mono text-xs">{error}</span>
        </p>
        <Button size="sm" variant="outline" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {agents.length} agent{agents.length !== 1 ? "s" : ""} registered
        </p>
        <Button size="sm" variant="outline" onClick={onCreate} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          New Agent
        </Button>
      </div>

      <div className="overflow-hidden rounded-xl border border-border/60 bg-card/80">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs font-medium text-muted-foreground">
              <th className="px-3 py-2.5">Name</th>
              <th className="px-3 py-2.5">Description</th>
              <th className="px-3 py-2.5">Skills</th>
              <th className="px-3 py-2.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {agents.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                  No agents configured yet.
                </td>
              </tr>
            ) : (
              agents.map((agent) => (
                <tr
                  key={agent.name}
                  className="transition-colors hover:bg-accent/30"
                >
                  <td className="px-3 py-2.5 font-medium">
                    <span className="inline-flex items-center gap-1.5 flex-wrap">
                      {agent.display_name || agent.name}
                      {agent.display_name && agent.display_name !== agent.name && (
                        <span className="text-xs text-muted-foreground">
                          ({agent.name})
                        </span>
                      )}
                      {/* PR3 offline badge — hidden when the backend marks
                          the agent as available (either every binary is on
                          PATH, or the registry was loaded without a skills
                          root and defaults to true). */}
                      {agent.available === false && (
                        <span
                          className="rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-300"
                          title={
                            agent.missing_binaries && agent.missing_binaries.length > 0
                              ? `离线：本机缺少 ${agent.missing_binaries.join(", ")}`
                              : "离线：部分依赖不可用"
                          }
                        >
                          离线
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="max-w-[280px] truncate px-3 py-2.5 text-muted-foreground">
                    {agent.description || "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {agent.scoped_skills.length > 0
                        ? agent.scoped_skills.map((skill) => (
                            <span
                              key={skill}
                              className="rounded border border-border/60 bg-muted/40 px-1.5 py-0.5 text-xs text-muted-foreground"
                            >
                              {skill}
                            </span>
                          ))
                        : <span className="text-xs text-muted-foreground">—</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="inline-flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => onEdit(agent.name)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        onClick={() => handleDelete(agent.name)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
