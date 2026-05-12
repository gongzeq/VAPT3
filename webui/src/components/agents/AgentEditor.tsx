import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getAgent, createAgent, updateAgent } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import type { AgentDetail } from "@/lib/api";

interface AgentEditorProps {
  /** If provided, we're editing an existing agent. Otherwise creating new. */
  name?: string;
  onClose: () => void;
}

type EditMode = "form" | "yaml";

export function AgentEditor({ name, onClose }: AgentEditorProps) {
  const { token } = useClient();
  const isNew = !name;

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [editMode, setEditMode] = useState<EditMode>("form");

  // Form fields
  const [formName, setFormName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [scopedSkills, setScopedSkills] = useState<string[]>([]);
  const [skillInput, setSkillInput] = useState("");
  const [yamlContent, setYamlContent] = useState("");

  const loadAgent = useCallback(() => {
    if (!name) return;
    let cancelled = false;
    setLoading(true);
    getAgent(token, name)
      .then((detail: AgentDetail) => {
        if (cancelled) return;
        setFormName(detail.name);
        setDisplayName(detail.display_name);
        setDescription(detail.description);
        setSystemPrompt(detail.system_prompt);
        setScopedSkills(detail.scoped_skills);
        setYamlContent(detail.yaml_content || "");
      })
      .catch((err) => {
        if (!cancelled) window.alert(`Failed to load agent: ${(err as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [name, token]);

  useEffect(() => { loadAgent(); }, [loadAgent]);

  const handleAddSkill = () => {
    const skill = skillInput.trim();
    if (skill && !scopedSkills.includes(skill)) {
      setScopedSkills((prev) => [...prev, skill]);
    }
    setSkillInput("");
  };

  const handleRemoveSkill = (skill: string) => {
    setScopedSkills((prev) => prev.filter((s) => s !== skill));
  };

  const handleSkillKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddSkill();
    }
  };

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaved(false);
    try {
      if (editMode === "yaml" && yamlContent.trim()) {
        // Save as raw YAML
        if (isNew) {
          await createAgent(token, { yaml_content: yamlContent } as Partial<AgentDetail>);
        } else {
          await updateAgent(token, name!, { yaml_content: yamlContent });
        }
      } else {
        // Save individual fields
        const data: Partial<AgentDetail> = {
          name: isNew ? formName : undefined,
          display_name: displayName,
          description,
          system_prompt: systemPrompt,
          scoped_skills: scopedSkills,
        };
        if (isNew) {
          data.name = formName;
          await createAgent(token, data);
        } else {
          await updateAgent(token, name!, data);
        }
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
        Loading agent details...
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
        {isNew ? "Create Agent" : `Edit: ${displayName || name}`}
      </h2>

      {/* Restart warning banner */}
      {saved && (
        <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 px-4 py-2.5 text-sm text-yellow-200">
          Configuration saved. A service restart is required for changes to take effect.
        </div>
      )}

      {/* Form/YAML toggle */}
      <div className="flex gap-1 rounded-lg border border-border/60 bg-card/80 p-1">
        <button
          type="button"
          onClick={() => setEditMode("form")}
          className={cn(
            "rounded-md px-3 py-1 text-xs font-medium transition-colors",
            editMode === "form"
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          Form
        </button>
        <button
          type="button"
          onClick={() => setEditMode("yaml")}
          className={cn(
            "rounded-md px-3 py-1 text-xs font-medium transition-colors",
            editMode === "yaml"
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          YAML
        </button>
      </div>

      {editMode === "yaml" ? (
        <div className="space-y-3">
          <label className="block text-sm font-medium">
            YAML Configuration
          </label>
          <textarea
            value={yamlContent}
            onChange={(e) => setYamlContent(e.target.value)}
            className="h-[400px] w-full rounded-lg border border-border/60 bg-card/80 p-3 font-mono text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            spellCheck={false}
            placeholder="# Paste or edit agent YAML configuration here..."
          />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Name (only editable on create) */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Name (identifier)</label>
            <Input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              disabled={!isNew}
              placeholder="my_agent"
              className="max-w-[320px]"
            />
          </div>

          {/* Display Name */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Display Name</label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="My Agent"
              className="max-w-[320px]"
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Description</label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this agent does"
            />
          </div>

          {/* Scoped Skills */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Scoped Skills</label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {scopedSkills.map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center gap-1 rounded border border-border/60 bg-muted/40 px-2 py-0.5 text-xs"
                >
                  {skill}
                  <button
                    type="button"
                    onClick={() => handleRemoveSkill(skill)}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                onKeyDown={handleSkillKeyDown}
                placeholder="Type skill name and press Enter"
                className="max-w-[280px]"
              />
              <Button size="sm" variant="outline" onClick={handleAddSkill}>
                Add
              </Button>
            </div>
          </div>

          {/* System Prompt */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">System Prompt</label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="h-[240px] w-full rounded-lg border border-border/60 bg-card/80 p-3 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              spellCheck={false}
              placeholder="Enter the system prompt for this agent..."
            />
          </div>
        </div>
      )}

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
