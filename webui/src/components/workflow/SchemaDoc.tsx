import { useState } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, ChevronDown, ChevronRight } from "lucide-react";

import type { AgentMeta, JsonSchema, ToolMeta } from "@/lib/workflow-client";

/** @description Collapsible schema documentation card for tool/agent. */
export function SchemaDocCard({
  meta,
  scope,
}: {
  meta: ToolMeta | AgentMeta;
  scope: "tool" | "agent";
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const hasInput = !!(
    meta.inputSchema &&
    meta.inputSchema.properties &&
    Object.keys(meta.inputSchema.properties).length > 0
  );
  const hasOutput = !!(
    meta.outputSchema &&
    meta.outputSchema.properties &&
    Object.keys(meta.outputSchema.properties).length > 0
  );

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-primary" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-primary" />
        )}
        <BookOpen className="h-3.5 w-3.5 text-primary" />
        <span className="font-medium text-primary">
          {scope === "tool"
            ? t("workflow.tool.docTitle")
            : t("workflow.agent.docTitle")}
          {meta.title && meta.title !== meta.name ? (
            <span className="ml-1 font-normal text-muted-foreground">
              · {meta.title}
            </span>
          ) : null}
        </span>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {meta.name}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-primary/20 px-3 py-2 text-xs">
          {meta.description && (
            <p className="leading-relaxed text-muted-foreground">
              {meta.description}
            </p>
          )}
          <SchemaDocSection
            title={t("workflow.doc.inputs")}
            schema={hasInput ? meta.inputSchema : undefined}
            emptyHint={t("workflow.doc.inputsEmpty")}
          />
          <SchemaDocSection
            title={t("workflow.doc.outputs")}
            schema={hasOutput ? meta.outputSchema : undefined}
            emptyHint={t("workflow.doc.outputsEmpty")}
          />
        </div>
      )}
    </div>
  );
}

/** @description Section within SchemaDocCard showing input or output properties. */
export function SchemaDocSection({
  title,
  schema,
  emptyHint,
}: {
  title: string;
  schema?: JsonSchema;
  emptyHint: string;
}) {
  const entries = Object.entries(schema?.properties ?? {});
  const required = new Set(schema?.required ?? []);
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      {entries.length === 0 ? (
        <div className="text-xs italic text-muted-foreground/70">
          {emptyHint}
        </div>
      ) : (
        <ul className="space-y-1">
          {entries.map(([k, v]) => (
            <li
              key={k}
              className="rounded-md border border-border/30 bg-background/30 px-2 py-1"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-xs text-primary">{k}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {formatType(v)}
                </span>
                {required.has(k) && (
                  <span className="rounded bg-destructive/20 px-1 text-xs text-destructive">
                    required
                  </span>
                )}
              </div>
              {v.description && (
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {v.description}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** @description Format a JSON schema type as a human-readable string. */
export function formatType(schema: JsonSchema): string {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return `enum(${schema.enum.map(String).join("|")})`;
  }
  if (schema.type === "array") {
    return `array<${schema.items ? formatType(schema.items) : "any"}>`;
  }
  return schema.type ?? "any";
}
