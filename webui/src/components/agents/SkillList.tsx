import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { listSkills, deleteSkill } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";
import type { SkillInfo } from "@/lib/api";

interface SkillListProps {
  onEdit: (name: string) => void;
  onCreate: () => void;
}

export function SkillList({ onEdit, onCreate }: SkillListProps) {
  const { token } = useClient();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSkills(token)
      .then((data) => {
        if (!cancelled) setSkills(data);
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
    if (!window.confirm(`Delete skill "${name}"? This cannot be undone.`)) return;
    try {
      await deleteSkill(token, name);
      setSkills((prev) => prev.filter((s) => s.name !== name));
    } catch (err) {
      window.alert(`Delete failed: ${(err as Error).message}`);
    }
  };

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading skills...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-xl border border-border/60 bg-card/80 p-4">
        <p className="text-sm">
          Failed to load skills: <span className="font-mono text-xs">{error}</span>
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
          {skills.length} skill{skills.length !== 1 ? "s" : ""} registered
        </p>
        <Button size="sm" variant="outline" onClick={onCreate} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          New Skill
        </Button>
      </div>

      <div className="overflow-hidden rounded-xl border border-border/60 bg-card/80">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs font-medium text-muted-foreground">
              <th className="px-3 py-2.5">Name</th>
              <th className="px-3 py-2.5">Description</th>
              <th className="px-3 py-2.5">Directory</th>
              <th className="px-3 py-2.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {skills.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                  No skills configured yet.
                </td>
              </tr>
            ) : (
              skills.map((skill) => (
                <tr
                  key={skill.name}
                  className="transition-colors hover:bg-accent/30"
                >
                  <td className="px-3 py-2.5 font-medium">{skill.name}</td>
                  <td className="max-w-[280px] truncate px-3 py-2.5 text-muted-foreground">
                    {skill.description || "—"}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                    {skill.source_dir || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="inline-flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => onEdit(skill.name)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        onClick={() => handleDelete(skill.name)}
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
