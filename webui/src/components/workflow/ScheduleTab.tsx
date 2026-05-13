import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Save, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  type ScheduleKind,
  type SchedulePayload,
  type Workflow,
  type WorkflowClient,
  type WorkflowInput,
} from "@/lib/workflow-client";
import { WORKFLOW_FIELD_CLASS } from "@/components/workflow/InputsEditor";

const DEFAULT_TZ = "Asia/Shanghai";

export interface ScheduleTabProps {
  workflow: Workflow;
  client: WorkflowClient;
  onUpdated: (next: Workflow) => void;
}

/**
 * Schedule editor. The backend exposes three ``kind`` values (api-spec
 * §2.3); the UI keeps them radio-selectable so the user can round-trip
 * between cron / every / at without losing inputs.
 *
 * Save / detach both hit the REST surface and bubble the returned
 * :class:`Workflow` to the parent so the page can rerender with the
 * freshly persisted ``scheduleRef``.
 */
export function ScheduleTab({ workflow, client, onUpdated }: ScheduleTabProps) {
  const { t } = useTranslation();

  const hasSchedule = !!workflow.scheduleRef;

  const [enabled, setEnabled] = useState<boolean>(hasSchedule);
  const [kind, setKind] = useState<ScheduleKind>("cron");
  const [cronExpr, setCronExpr] = useState("0 9 * * *");
  const [tz, setTz] = useState(DEFAULT_TZ);
  const [everyMs, setEveryMs] = useState<number>(60_000);
  const [atMs, setAtMs] = useState<number>(Date.now() + 3600_000);
  const [inputValues, setInputValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [detaching, setDetaching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Reset the local form whenever we edit a different workflow. We do
  // not prefetch the existing schedule payload (api does not expose it
  // by id today — only the stored ``scheduleRef``); the form always
  // boots with sensible defaults when scheduling is fresh.
  useEffect(() => {
    setEnabled(hasSchedule);
    setSaved(false);
    setError(null);
  }, [workflow.id, hasSchedule]);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const payload: SchedulePayload = {
        kind,
        enabled: true,
        inputs: materializeInputs(workflow.inputs, inputValues),
        cronExpr: kind === "cron" ? cronExpr : null,
        tz: kind === "cron" ? tz : null,
        everyMs: kind === "every" ? everyMs : null,
        atMs: kind === "at" ? atMs : null,
      };
      const next = await client.attachSchedule(workflow.id, payload);
      onUpdated(next);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function detach() {
    setDetaching(true);
    setError(null);
    try {
      const next = await client.detachSchedule(workflow.id);
      onUpdated(next);
      setEnabled(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDetaching(false);
    }
  }

  return (
    <section className="space-y-4">
      <header className="flex items-center gap-2">
        <CalendarClock className="h-5 w-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">
          {t("workflow.schedule.title")}
        </h2>
        <span
          className={cn(
            "ml-auto rounded-full border px-3 py-1 text-xs",
            hasSchedule
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-border/40 bg-muted/30 text-muted-foreground",
          )}
        >
          {hasSchedule
            ? t("workflow.card.scheduled")
            : t("workflow.card.unscheduled")}
        </span>
      </header>

      <div className="gradient-card rounded-2xl border border-[hsl(var(--border))] p-5 space-y-4">
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          {t("workflow.schedule.enabled")}
        </label>

        {enabled && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs text-muted-foreground">
                {t("workflow.schedule.kind")}
              </span>
              {(["cron", "every", "at"] as ScheduleKind[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setKind(k)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs transition-colors",
                    kind === k
                      ? "border-primary/50 bg-primary/10 text-primary"
                      : "border-border/40 bg-muted/30 text-muted-foreground hover:border-primary/30",
                  )}
                >
                  {t(
                    k === "cron"
                      ? "workflow.schedule.kindCron"
                      : k === "every"
                        ? "workflow.schedule.kindEvery"
                        : "workflow.schedule.kindAt",
                  )}
                </button>
              ))}
            </div>

            {kind === "cron" && (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <label className="flex flex-col gap-1 text-xs md:col-span-2">
                  <span className="text-muted-foreground">
                    {t("workflow.schedule.cronExpr")}
                  </span>
                  <input
                    value={cronExpr}
                    onChange={(e) => setCronExpr(e.target.value)}
                    className={cn(WORKFLOW_FIELD_CLASS, "font-mono")}
                  />
                  <span className="text-[11px] text-muted-foreground opacity-70">
                    {t("workflow.schedule.cronHelp")}
                  </span>
                </label>
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-muted-foreground">
                    {t("workflow.schedule.tz")}
                  </span>
                  <input
                    value={tz}
                    onChange={(e) => setTz(e.target.value)}
                    className={WORKFLOW_FIELD_CLASS}
                  />
                </label>
              </div>
            )}

            {kind === "every" && (
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">
                  {t("workflow.schedule.everyMs")}
                </span>
                <input
                  type="number"
                  min="1000"
                  value={everyMs}
                  onChange={(e) => setEveryMs(Number(e.target.value) || 0)}
                  className={WORKFLOW_FIELD_CLASS}
                />
              </label>
            )}

            {kind === "at" && (
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">
                  {t("workflow.schedule.atMs")}
                </span>
                <input
                  type="number"
                  value={atMs}
                  onChange={(e) => setAtMs(Number(e.target.value) || 0)}
                  className={WORKFLOW_FIELD_CLASS}
                />
              </label>
            )}

            {workflow.inputs.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">
                  {t("workflow.schedule.inputs")}
                </p>
                <InputsMatrix
                  inputs={workflow.inputs}
                  values={inputValues}
                  onChange={setInputValues}
                />
              </div>
            )}
          </>
        )}

        {error && (
          <p className="text-xs text-rose-300">
            {t("workflow.error.schedule")}: {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t border-border/30 pt-4">
          <button
            type="button"
            onClick={() => void save()}
            disabled={!enabled || saving}
            className="gradient-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-md disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {t("workflow.schedule.save")}
          </button>
          {hasSchedule && (
            <button
              type="button"
              onClick={() => void detach()}
              disabled={detaching}
              className="inline-flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300 transition-colors hover:bg-rose-500/20 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              {t("workflow.schedule.detach")}
            </button>
          )}
          {saved && (
            <span className="text-xs text-emerald-300">
              ✓ {t("workflow.schedule.saved")}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

function InputsMatrix({
  inputs,
  values,
  onChange,
}: {
  inputs: WorkflowInput[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {inputs.map((input) => (
        <label key={input.name} className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">
            {input.label || input.name}
            {input.required && <span className="ml-1 text-rose-400">*</span>}
          </span>
          <input
            value={values[input.name] ?? ""}
            onChange={(e) =>
              onChange({ ...values, [input.name]: e.target.value })
            }
            className={WORKFLOW_FIELD_CLASS}
          />
        </label>
      ))}
    </div>
  );
}

function materializeInputs(
  schema: WorkflowInput[],
  raw: Record<string, string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const spec of schema) {
    const text = raw[spec.name];
    if (text === undefined || text === "") {
      if (spec.default !== undefined && spec.default !== null) {
        out[spec.name] = spec.default;
      }
      continue;
    }
    if (spec.type === "int") {
      const n = Number(text);
      out[spec.name] = Number.isFinite(n) ? Math.trunc(n) : text;
    } else if (spec.type === "bool") {
      out[spec.name] =
        text.toLowerCase() === "true" || text === "1" || text === "yes";
    } else {
      out[spec.name] = text;
    }
  }
  return out;
}
