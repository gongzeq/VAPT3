import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  CalendarClock,
  History,
  Loader2,
  ListChecks,
  Play,
  Save,
  Settings2,
  Workflow as WorkflowIcon,
} from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { InputsEditor } from "@/components/workflow/InputsEditor";
import { RunDialog } from "@/components/workflow/RunDialog";
import { RunHistoryTab } from "@/components/workflow/RunHistoryTab";
import { ScheduleTab } from "@/components/workflow/ScheduleTab";
import { StepEditor } from "@/components/workflow/StepEditor";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import {
  WorkflowClient,
  emptyWorkflowDraft,
  type AgentMeta,
  type ToolMeta,
  type Workflow,
  type WorkflowDraft,
} from "@/lib/workflow-client";
import { DRAFT_STORAGE_KEY } from "@/pages/WorkflowListPage";

type TabKey = "basic" | "steps" | "schedule" | "runs";

/**
 * ``/workflows/:id`` — full editor & run console for a workflow.
 *
 * ``:id === "new"`` drops into creation mode, hydrating from the
 * stashed draft under ``sessionStorage[DRAFT_STORAGE_KEY]`` (set by
 * ``WorkflowListPage``). The first successful save navigates to the
 * persisted id so subsequent edits are updates.
 *
 * Tabs are kept mounted via Tailwind ``hidden`` (per dev-guide), so
 * user edits on one tab survive switching back and forth without a
 * full remount. Tools / agents metadata is fetched once and passed
 * down — each kind form renders its own schema-driven args panel.
 */
export function WorkflowDetailPage() {
  const { t } = useTranslation();
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token, workflowApiBase } = useClient();
  const client = useMemo(
    () => new WorkflowClient({ token, baseUrl: workflowApiBase }),
    [token, workflowApiBase],
  );
  const isNew = id === "new";

  // Persisted workflow (null until server echoes back an id — used as
  // the source of truth for tabs that need a saved workflow, i.e.
  // schedule / runs).
  const [saved, setSaved] = useState<Workflow | null>(null);
  // Editable draft — form state for basics + steps tabs.
  const [draft, setDraft] = useState<WorkflowDraft>(emptyWorkflowDraft());
  const [loading, setLoading] = useState(!isNew);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("basic");

  // Metadata for step editor dropdowns.
  const [tools, setTools] = useState<ToolMeta[]>([]);
  const [agents, setAgents] = useState<AgentMeta[]>([]);

  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const savedAtRef = useRef<number>(0);
  const [savedFlash, setSavedFlash] = useState(false);

  const [runOpen, setRunOpen] = useState(false);
  const [runStartErr, setRunStartErr] = useState<string | null>(null);
  const [runRefreshKey, setRunRefreshKey] = useState(0);

  // ─── Initial load ────────────────────────────────────────────────
  useEffect(() => {
    if (isNew) {
      // Pop the stashed draft (if any) — list page seeds it when
      // "New" / "From template" is clicked. Fallback to blank.
      let seed: WorkflowDraft = emptyWorkflowDraft();
      try {
        const raw = sessionStorage.getItem(DRAFT_STORAGE_KEY);
        if (raw) {
          seed = JSON.parse(raw) as WorkflowDraft;
          sessionStorage.removeItem(DRAFT_STORAGE_KEY);
        }
      } catch {
        // ignore, fall back to empty draft
      }
      setDraft(seed);
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadErr(null);
      try {
        const wf = await client.get(id);
        if (cancelled) return;
        setSaved(wf);
        setDraft(workflowToDraft(wf));
      } catch (e) {
        if (!cancelled) setLoadErr((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, id, isNew]);

  // ─── Metadata load (parallel, non-blocking) ──────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [toolsRes, agentsRes] = await Promise.all([
          client.listTools(),
          client.listAgents(),
        ]);
        if (cancelled) return;
        setTools(toolsRes.items);
        setAgents(agentsRes.items);
      } catch {
        // Non-fatal — dropdowns just stay empty.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  // ─── Save ────────────────────────────────────────────────────────
  const canSave = draft.name.trim().length > 0 && !saving;

  const handleSave = useCallback(async () => {
    if (!canSave) return;
    setSaving(true);
    setSaveErr(null);
    try {
      const wf = saved
        ? await client.update(saved.id, draft)
        : await client.create(draft);
      setSaved(wf);
      setDraft(workflowToDraft(wf));
      savedAtRef.current = Date.now();
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1500);
      if (isNew) {
        // Swap URL without remounting; tab state stays as-is.
        navigate(`/workflows/${wf.id}`, { replace: true });
      }
    } catch (e) {
      setSaveErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [canSave, client, draft, isNew, navigate, saved]);

  // ─── Run ─────────────────────────────────────────────────────────
  async function handleRun(inputs: Record<string, unknown>) {
    if (!saved) return;
    setRunStartErr(null);
    try {
      await client.run(saved.id, inputs);
      setRunOpen(false);
      // Bump the refresh counter + jump to the runs tab so the user
      // sees the new row immediately.
      setRunRefreshKey((n) => n + 1);
      setTab("runs");
    } catch (e) {
      setRunStartErr((e as Error).message);
      throw e; // Let the dialog keep itself open on failure.
    }
  }

  // ─── Basics tab field updates ────────────────────────────────────
  function updateDraft<K extends keyof WorkflowDraft>(
    key: K,
    value: WorkflowDraft[K],
  ) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  function addTag() {
    const v = tagInput.trim();
    if (!v) return;
    if (draft.tags.includes(v)) {
      setTagInput("");
      return;
    }
    updateDraft("tags", [...draft.tags, v]);
    setTagInput("");
  }

  function removeTag(tag: string) {
    updateDraft(
      "tags",
      draft.tags.filter((t) => t !== tag),
    );
  }

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <Navbar />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1600px] space-y-5 px-6 py-6">
          {/* Header */}
          <div className="animate-fade-in-up flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => navigate("/workflows")}
                className="rounded-lg border border-border/40 p-1.5 text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                aria-label={t("workflow.listTitle")}
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <WorkflowIcon className="h-6 w-6 shrink-0 text-primary" />
              <div className="min-w-0">
                <h1 className="truncate text-xl font-semibold text-foreground">
                  {draft.name || t("workflow.createNew")}
                </h1>
                <p className="truncate text-xs text-muted-foreground">
                  {isNew && !saved
                    ? t("workflow.listSubtitle")
                    : saved?.id}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {savedFlash && (
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300">
                  {t("workflow.basic.saved")}
                </span>
              )}
              <button
                type="button"
                onClick={() => setRunOpen(true)}
                disabled={!saved}
                className={cn(
                  "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-colors",
                  saved
                    ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
                    : "cursor-not-allowed border-border/40 bg-muted/30 text-muted-foreground",
                )}
                title={!saved ? t("workflow.basic.save") : undefined}
              >
                <Play className="h-4 w-4" />
                {t("workflow.basic.run")}
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={!canSave}
                className={cn(
                  "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-md",
                  canSave
                    ? "gradient-primary hover-lift"
                    : "cursor-not-allowed bg-muted/40",
                )}
              >
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                {saving
                  ? t("workflow.basic.saving")
                  : t("workflow.basic.save")}
              </button>
            </div>
          </div>

          {(loadErr || saveErr || runStartErr) && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
              {loadErr && <div>{t("workflow.error.load")}: {loadErr}</div>}
              {saveErr && <div>{t("workflow.error.save")}: {saveErr}</div>}
              {runStartErr && (
                <div>{t("workflow.error.run")}: {runStartErr}</div>
              )}
            </div>
          )}

          {/* Tabs */}
          <div className="flex flex-wrap items-center gap-1 rounded-xl border border-border/40 bg-muted/20 p-1">
            <TabBtn
              active={tab === "basic"}
              icon={<Settings2 className="h-4 w-4" />}
              label={t("workflow.tabs.basic")}
              onClick={() => setTab("basic")}
            />
            <TabBtn
              active={tab === "steps"}
              icon={<ListChecks className="h-4 w-4" />}
              label={t("workflow.tabs.steps")}
              onClick={() => setTab("steps")}
            />
            <TabBtn
              active={tab === "schedule"}
              icon={<CalendarClock className="h-4 w-4" />}
              label={t("workflow.tabs.schedule")}
              onClick={() => setTab("schedule")}
              disabled={!saved}
            />
            <TabBtn
              active={tab === "runs"}
              icon={<History className="h-4 w-4" />}
              label={t("workflow.tabs.runs")}
              onClick={() => setTab("runs")}
              disabled={!saved}
            />
          </div>

          {/* Body — keep panels mounted so edits survive tab switches. */}
          {loading ? (
            <div className="flex items-center gap-2 rounded-2xl border border-border/40 bg-muted/20 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("workflow.loading")}
            </div>
          ) : (
            <>
              <section
                className={cn(
                  "animate-fade-in-up",
                  tab !== "basic" && "hidden",
                )}
                aria-hidden={tab !== "basic"}
              >
                <BasicTab
                  draft={draft}
                  tagInput={tagInput}
                  setTagInput={setTagInput}
                  onAddTag={addTag}
                  onRemoveTag={removeTag}
                  onField={updateDraft}
                />
              </section>

              <section
                className={cn(
                  "animate-fade-in-up",
                  tab !== "steps" && "hidden",
                )}
                aria-hidden={tab !== "steps"}
              >
                <StepEditor
                  steps={draft.steps}
                  onChange={(next) => updateDraft("steps", next)}
                  tools={tools}
                  agents={agents}
                />
              </section>

              <section
                className={cn(
                  "animate-fade-in-up",
                  tab !== "schedule" && "hidden",
                )}
                aria-hidden={tab !== "schedule"}
              >
                {saved ? (
                  <ScheduleTab
                    workflow={saved}
                    client={client}
                    onUpdated={(next) => {
                      setSaved(next);
                      setDraft(workflowToDraft(next));
                    }}
                  />
                ) : (
                  <SaveFirstHint />
                )}
              </section>

              <section
                className={cn(
                  "animate-fade-in-up",
                  tab !== "runs" && "hidden",
                )}
                aria-hidden={tab !== "runs"}
              >
                {saved ? (
                  <RunHistoryTab
                    workflow={saved}
                    client={client}
                    refreshKey={runRefreshKey}
                  />
                ) : (
                  <SaveFirstHint />
                )}
              </section>
            </>
          )}
        </div>
      </main>

      <RunDialog
        workflow={saved}
        open={runOpen}
        onOpenChange={setRunOpen}
        onSubmit={handleRun}
      />
    </div>
  );
}

export default WorkflowDetailPage;

// ─── Subcomponents (page-local) ──────────────────────────────────────

function TabBtn({
  active,
  icon,
  label,
  onClick,
  disabled,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors",
        disabled
          ? "cursor-not-allowed text-muted-foreground/50"
          : active
            ? "bg-primary/15 text-primary"
            : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function SaveFirstHint() {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border border-dashed border-border/40 bg-muted/20 p-6 text-sm text-muted-foreground">
      {t("workflow.basic.save")} → {t("workflow.tabs.schedule")} /{" "}
      {t("workflow.tabs.runs")}
    </div>
  );
}

const FIELD_CLASS =
  "h-10 w-full rounded-xl border border-[hsl(var(--border))] bg-background/40 px-3 text-sm outline-none transition-colors focus:border-primary/50";

function BasicTab({
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
  onField: <K extends keyof WorkflowDraft>(
    key: K,
    value: WorkflowDraft[K],
  ) => void;
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
        <InputsEditor
          value={draft.inputs}
          onChange={(next) => onField("inputs", next)}
        />
      </div>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────

function workflowToDraft(wf: Workflow): WorkflowDraft {
  // Strip server-owned fields so subsequent PUT/POST payloads match
  // the ``WorkflowDraft`` contract (api-spec §1).
  const { id, createdAtMs, updatedAtMs, ...rest } = wf;
  void id;
  void createdAtMs;
  void updatedAtMs;
  return { ...rest };
}
