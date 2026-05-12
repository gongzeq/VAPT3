import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getSkill, createSkill, updateSkill } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

interface SkillEditorProps {
  /** If provided, we're editing an existing skill. Otherwise creating new. */
  name?: string;
  onClose: () => void;
}

export function SkillEditor({ name, onClose }: SkillEditorProps) {
  const { token } = useClient();
  const isNew = !name;

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const [formName, setFormName] = useState("");
  const [content, setContent] = useState("");

  const loadSkill = useCallback(() => {
    if (!name) return;
    let cancelled = false;
    setLoading(true);
    getSkill(token, name)
      .then((detail) => {
        if (cancelled) return;
        setFormName(detail.name);
        setContent(detail.content);
      })
      .catch((err) => {
        if (!cancelled) window.alert(`Failed to load skill: ${(err as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [name, token]);

  useEffect(() => { loadSkill(); }, [loadSkill]);

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaved(false);
    try {
      if (isNew) {
        await createSkill(token, { name: formName, content });
      } else {
        await updateSkill(token, name!, { content });
      }
      setSaved(true);
    } catch (err) {
      window.alert(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading skill...
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={onClose}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        Back to list
      </button>

      <h2 className="text-base font-semibold tracking-tight">
        {isNew ? "Create Skill" : `Edit: ${name}`}
      </h2>

      {/* Restart warning banner */}
      {saved && (
        <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 px-4 py-2.5 text-sm text-yellow-200">
          Configuration saved. A service restart is required for changes to take effect.
        </div>
      )}

      <div className="space-y-4">
        {/* Name (only editable on create) */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Skill Name</label>
          <Input
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            disabled={!isNew}
            placeholder="my_skill"
            className="max-w-[320px]"
          />
        </div>

        {/* Content */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            SKILL.md Content
          </label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="h-[400px] w-full rounded-lg border border-border/60 bg-card/80 p-3 font-mono text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            spellCheck={false}
            placeholder="# Skill Name&#10;&#10;Description and instructions for this skill..."
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3 pt-2">
        <Button
          size="sm"
          onClick={handleSave}
          disabled={saving || (isNew && !formName.trim())}
        >
          {saving ? (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Saving...
            </span>
          ) : (
            "Save"
          )}
        </Button>
        <Button size="sm" variant="outline" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
