import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import type { WorkflowTemplate } from "@/lib/workflow-client";

export interface TemplateGalleryProps {
  templates: WorkflowTemplate[];
  loading?: boolean;
  onPick: (template: WorkflowTemplate) => void;
  className?: string;
}

/**
 * Horizontally-scrolling strip of preset workflow templates. Rendered
 * inside the list page above the workflow grid; clicking a card clones
 * the template's embedded draft and hands it to the caller (list page
 * then navigates into the detail editor).
 *
 * Empty/loading states degrade gracefully so the list page can mount
 * the gallery unconditionally without worrying about state shape.
 */
export function TemplateGallery({
  templates,
  loading,
  onPick,
  className,
}: TemplateGalleryProps) {
  const { t } = useTranslation();
  if (!loading && templates.length === 0) {
    return null; // Don't render empty strip to avoid visual clutter.
  }
  return (
    <section
      className={cn(
        "gradient-card animate-fade-in-up rounded-2xl border border-[hsl(var(--border))] p-5",
        className,
      )}
    >
      <header className="mb-3 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold text-foreground">
          {t("workflow.templates.title")}
        </h2>
        <span className="text-xs text-muted-foreground">
          · {t("workflow.templates.subtitle")}
        </span>
      </header>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {loading &&
          templates.length === 0 &&
          Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-24 w-64 shrink-0 animate-pulse rounded-xl border border-border/40 bg-muted/30"
            />
          ))}
        {templates.map((tpl) => (
          <button
            key={tpl.id}
            type="button"
            onClick={() => onPick(tpl)}
            className="group hover-lift flex h-28 w-64 shrink-0 flex-col justify-between rounded-xl border border-[hsl(var(--border))] bg-background/40 p-3 text-left transition-colors hover:border-primary/40"
          >
            <div>
              <p className="truncate text-sm font-medium text-foreground">
                {tpl.name}
              </p>
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {tpl.description}
              </p>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex flex-wrap gap-1 overflow-hidden">
                {tpl.tags.slice(0, 2).map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-border/40 bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <span className="text-xs text-primary opacity-70 transition-opacity group-hover:opacity-100">
                {t("workflow.templates.use")} →
              </span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
