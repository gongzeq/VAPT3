import { useTranslation } from "react-i18next";

import { InputsEditor } from "@/components/workflow/InputsEditor";
import type { WorkflowDraft } from "@/lib/workflow-client";

const FIELD_CLASS =
  "h-10 w-full rounded-xl border border-[hsl(var(--border))] bg-background/40 px-3 text-sm outline-none transition-colors focus:border-primary/50";

/** @description Basic info tab for workflow editing (name, tags, description, inputs). */
export function BasicTab({
  draft,
  tagInput,
  setTagInput,
  onAddTag,
  onRemoveTag,
  onField,
}: {
  draft: WorkflowDraft;
  tagInput: string;
  setTagInput: (v: string) => void;
  onAddTag: () => void;
  onRemoveTag: (tag: string) => void;
  onField: <K extends keyof WorkflowDraft>(key: K, value: WorkflowDraft[K]) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-5">
      <div className="gradient-card space-y-4 rounded-2xl border border-[hsl(var(--border))] p-5">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">
              {t("workflow.basic.name")}
            </span>
            <input
              type="text"
              value={draft.name}
              onChange={(e) => onField("name", e.target.value)}
              placeholder={t("workflow.basic.namePlaceholder")}
              className={FIELD_CLASS}
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">
              {t("workflow.basic.tags")}
            </span>
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[hsl(var(--border))] bg-background/40 p-2">
              {draft.tags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => onRemoveTag(tag)}
                  className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs text-primary transition-colors hover:bg-primary/20"
                >
                  {tag}
                  <span aria-hidden>×</span>
                </button>
              ))}
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    onAddTag();
                  } else if (
                    e.key === "Backspace" &&
                    tagInput === "" &&
                    draft.tags.length
                  ) {
                    onRemoveTag(draft.tags[draft.tags.length - 1]);
                  }
                }}
                onBlur={onAddTag}
                placeholder={t("workflow.basic.tagsPlaceholder")}
                className="flex-1 bg-transparent px-1 py-0.5 text-xs outline-none"
              />
            </div>
          </label>
        </div>
        <label className="block space-y-1 text-sm">
          <span className="text-xs text-muted-foreground">
            {t("workflow.basic.description")}
          </span>
          <textarea
            value={draft.description}
            onChange={(e) => onField("description", e.target.value)}
            placeholder={t("workflow.basic.descriptionPlaceholder")}
            rows={3}
            className="w-full rounded-xl border border-[hsl(var(--border))] bg-background/40 px-3 py-2 text-sm outline-none transition-colors focus:border-primary/50"
          />
        </label>
      </div>

      <div className="gradient-card rounded-2xl border border-[hsl(var(--border))] p-5">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              {t("workflow.basic.inputs")}
            </h3>
            <p className="text-xs text-muted-foreground">
              {t("workflow.basic.inputsHelp")}
            </p>
          </div>
        </div>
        <InputsEditor value={draft.inputs} onChange={(next) => onField("inputs", next)} />
      </div>
    </div>
  );
}
