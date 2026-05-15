import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Activity,
  Bot,
  Brain,
  CalendarClock,
  Check,
  ChevronRight,
  Clock,
  Copy,
  History,
  Loader2,
  ListChecks,
  Play,
  Save,
  Settings2,
  Square,
  Terminal,
  Wrench,
  Zap,
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
  STEP_KIND_TONE,
  WorkflowClient,
  emptyWorkflowDraft,
  type AgentMeta,
  type RunStatus,
  type StepKind,
  type ToolMeta,
  type Workflow,
  type WorkflowDraft,
  type WorkflowRun,
  type WorkflowStep,
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
  // NOTE: We seed via lazy initializer (instead of inside the load
  // effect) so React 18 StrictMode's effect double-invoke can never
  // clobber a template-seeded draft with the empty fallback. The
  // sessionStorage cleanup happens in the effect below.
  const [draft, setDraft] = useState<WorkflowDraft>(() => {
    if (id === "new") {
      try {
        const raw = sessionStorage.getItem(DRAFT_STORAGE_KEY);
        if (raw) return JSON.parse(raw) as WorkflowDraft;
      } catch {
        // ignore — fall through to empty draft
      }
    }
    return emptyWorkflowDraft();
  });
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

  // Most recent run — drives the gradient header card (status / progress
  // / animated flow chart). We poll every 3s whenever the last known
  // status is ``running``; other statuses are terminal, so we stop to
  // avoid pointless traffic. Each save/run bumps ``runRefreshKey`` which
  // re-triggers this effect.
  const [recentRun, setRecentRun] = useState<WorkflowRun | null>(null);
  useEffect(() => {
    if (!saved) {
      setRecentRun(null);
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    const tick = async () => {
      try {
        const res = await client.listRuns(saved.id, 1);
        if (cancelled) return;
        const latest = res.items[0] ?? null;
        setRecentRun(latest);
        if (latest && latest.status === "running") {
          timer = window.setTimeout(tick, 3000);
        }
      } catch {
        // Non-fatal — header falls back to idle state.
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [client, saved, runRefreshKey]);

  // ─── Initial load ────────────────────────────────────────────────
  useEffect(() => {
    if (isNew) {
      // Draft was already seeded by the useState lazy initializer
      // (which runs once per mount, immune to StrictMode effect
      // double-invoke). Just clear the stash so a future "new" tab
      // doesn't accidentally inherit it.
      try {
        sessionStorage.removeItem(DRAFT_STORAGE_KEY);
      } catch {
        // ignore — quota / private mode
      }
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
          {/* Breadcrumb */}
          <nav className="flex items-center gap-2 text-xs text-muted-foreground">
            <button
              type="button"
              onClick={() => navigate("/workflows")}
              className="cursor-pointer hover:text-primary"
            >
              {t("workflow.listTitle")}
            </button>
            <ChevronRight className="h-3 w-3" />
            <span className="truncate text-foreground">
              {draft.name || t("workflow.createNew")}
            </span>
          </nav>

          {/* Header: gradient big card with status / progress / flow animation */}
          <WorkflowHeaderCard
            draft={draft}
            saved={saved}
            recentRun={recentRun}
            savedFlash={savedFlash}
            saving={saving}
            canSave={canSave}
            onRun={() => setRunOpen(true)}
            onSave={() => void handleSave()}
            onCancelRun={() =>
              saved ? void client.cancel(saved.id).then(() => setRunRefreshKey((n) => n + 1)) : undefined
            }
          />

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
                  inputs={draft.inputs}
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

// ─── WorkflowHeaderCard (prototype §Detail header) ───────────────────

const KIND_ICON: Record<StepKind, React.ComponentType<{ className?: string }>> =
  {
    tool: Wrench,
    script: Terminal,
    agent: Bot,
    llm: Brain,
  };

interface HeaderCardProps {
  draft: WorkflowDraft;
  saved: Workflow | null;
  recentRun: WorkflowRun | null;
  savedFlash: boolean;
  saving: boolean;
  canSave: boolean;
  onRun: () => void;
  onSave: () => void;
  onCancelRun: () => void;
}

function WorkflowHeaderCard({
  draft,
  saved,
  recentRun,
  savedFlash,
  saving,
  canSave,
  onRun,
  onSave,
  onCancelRun,
}: HeaderCardProps) {
  const { t } = useTranslation();
  const running = recentRun?.status === "running";
  const steps = draft.steps;

  // Derived "current running step" — first step without a result while
  // the run is still in flight. Used for the current-step banner and
  // to decorate the flow chart node.
  const currentStepIndex = useMemo(() => {
    if (!recentRun || !running) return -1;
    const results = recentRun.stepResults ?? {};
    for (let i = 0; i < steps.length; i += 1) {
      if (!results[steps[i].id]) return i;
    }
    return steps.length;
  }, [recentRun, running, steps]);

  const completedCount = useMemo(() => {
    if (!recentRun) return 0;
    return Object.values(recentRun.stepResults ?? {}).filter(
      (r) => r.status === "ok" || r.status === "skipped",
    ).length;
  }, [recentRun]);

  const elapsed = useMemo(() => {
    if (!recentRun) return "—";
    const end = recentRun.finishedAtMs ?? Date.now();
    return formatDuration(end - recentRun.startedAtMs);
  }, [recentRun]);

  const kindMix = useMemo(() => {
    const set = new Set<StepKind>();
    for (const s of steps) set.add(s.kind);
    return Array.from(set).join(" + ");
  }, [steps]);

  return (
    <div className="gradient-card border-glow animate-fade-in-up space-y-5 rounded-2xl p-6">
      {/* Top row: status + title + actions */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <RunStatusPill status={recentRun?.status ?? null} elapsed={elapsed} />
            {saved && (
              <span className="rounded-md bg-[hsl(var(--muted))]/50 px-2 py-0.5 font-mono text-xs text-muted-foreground">
                {saved.id}
              </span>
            )}
            {draft.tags.slice(0, 4).map((tg) => (
              <span
                key={tg}
                className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] text-primary"
              >
                #{tg}
              </span>
            ))}
            {kindMix && (
              <span className="rounded-full border border-pink-400/40 bg-pink-400/10 px-2 py-0.5 font-mono text-[10px] text-pink-300">
                {kindMix}
              </span>
            )}
          </div>
          <h1 className="truncate text-2xl font-bold text-foreground">
            {draft.name || t("workflow.createNew")}
          </h1>
          {draft.description && (
            <p className="max-w-3xl text-sm text-muted-foreground">
              {draft.description}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {savedFlash && (
            <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300">
              {t("workflow.basic.saved")}
            </span>
          )}
          <button
            type="button"
            disabled={!saved}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors",
              saved
                ? "border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 hover:border-primary/40"
                : "cursor-not-allowed border-border/40 bg-muted/30 text-muted-foreground",
            )}
          >
            <Copy className="h-4 w-4" /> {t("workflow.detail.clone")}
          </button>
          {running ? (
            <button
              type="button"
              onClick={onCancelRun}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/20"
            >
              <Square className="h-4 w-4" /> {t("workflow.detail.cancel")}
            </button>
          ) : (
            <button
              type="button"
              onClick={onSave}
              disabled={!canSave}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-white shadow-md",
                canSave ? "gradient-primary hover-lift" : "cursor-not-allowed bg-muted/40",
              )}
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {saving ? t("workflow.basic.saving") : t("workflow.basic.save")}
            </button>
          )}
          <button
            type="button"
            onClick={onRun}
            disabled={!saved}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-md",
              saved
                ? "gradient-primary hover-lift animate-pulse-glow"
                : "cursor-not-allowed bg-muted/40",
            )}
          >
            <Play className="h-4 w-4" /> {t("workflow.basic.run")}
          </button>
        </div>
      </div>

      {/* 5-col progress stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <ProgressCell
          label={t("workflow.detail.currentStep")}
          value={
            steps.length > 0
              ? `${Math.max(0, Math.min(currentStepIndex + 1, steps.length)) || completedCount} / ${steps.length}`
              : "—"
          }
          tone="primary"
        />
        <ProgressCell
          label={t("workflow.detail.elapsed")}
          value={elapsed}
        />
        <ProgressCell
          label={t("workflow.detail.totalSteps")}
          value={String(steps.length)}
        />
        <ProgressCell
          label={t("workflow.detail.completed")}
          value={String(completedCount)}
          tone="success"
        />
        <ProgressCell
          label={t("workflow.detail.nextRun")}
          value={saved?.scheduleRef ?? t("workflow.card.unscheduled")}
          tone={saved?.scheduleRef ? "primary" : undefined}
        />
      </div>

      {/* Flow chart */}
      {steps.length > 0 && (
        <div className="border-t border-[hsl(var(--border))] pt-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <Activity className="h-3.5 w-3.5 text-primary" />
              {t("workflow.detail.flowTitle")}
              {kindMix && (
                <span className="ml-1 font-mono text-[10px] text-muted-foreground/70">
                  · {kindMix}
                </span>
              )}
            </div>
            <FlowLegend
              completed={completedCount}
              running={running && currentStepIndex >= 0 ? 1 : 0}
              pending={Math.max(0, steps.length - completedCount - (running && currentStepIndex >= 0 ? 1 : 0))}
            />
          </div>

          <div className="flex items-start overflow-x-auto pb-2">
            {steps.map((step, i) => {
              const prevDone = i < completedCount;
              const isCurrent =
                running && i === currentStepIndex;
              const isPending = !prevDone && !isCurrent;
              return (
                <FlowNode
                  key={step.id}
                  step={step}
                  index={i}
                  isLast={i === steps.length - 1}
                  state={
                    prevDone ? "done" : isCurrent ? "running" : isPending ? "pending" : "done"
                  }
                />
              );
            })}
          </div>

          {running && currentStepIndex >= 0 && steps[currentStepIndex] && (
            <div className="mt-4 flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
              <Zap className="h-4 w-4 animate-pulse text-primary" />
              <div className="min-w-0 flex-1 text-xs">
                <span className="font-semibold text-primary">
                  {t("workflow.detail.stepCounter", {
                    current: currentStepIndex + 1,
                    total: steps.length,
                  })}
                </span>
                <span className="text-muted-foreground"> · </span>
                <span className="font-mono text-foreground">
                  {steps[currentStepIndex].kind}:
                  {steps[currentStepIndex].ref || steps[currentStepIndex].id}
                </span>
                <span className="text-muted-foreground"> · {t("workflow.detail.runningHint")}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RunStatusPill({
  status,
  elapsed,
}: {
  status: RunStatus | null;
  elapsed: string;
}) {
  const { t } = useTranslation();
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 font-mono text-xs text-emerald-300">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
        {t("workflow.badge.running")} · {elapsed}
      </span>
    );
  }
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 font-mono text-xs text-emerald-300">
        <Check className="h-3 w-3" /> {t("workflow.runs.status.ok")} · {elapsed}
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-500/40 bg-rose-500/10 px-3 py-1 font-mono text-xs text-rose-300">
        {t("workflow.runs.status.error")} · {elapsed}
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-1 font-mono text-xs text-muted-foreground">
        {t("workflow.runs.status.cancelled")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-1 font-mono text-xs text-muted-foreground">
      <Clock className="h-3 w-3" /> {t("workflow.detail.idle")}
    </span>
  );
}

function ProgressCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "primary" | "success";
}) {
  const toneCls =
    tone === "primary"
      ? "text-primary"
      : tone === "success"
        ? "text-emerald-300"
        : "text-foreground";
  return (
    <div className="rounded-lg bg-[hsl(var(--muted))]/40 p-3">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 truncate font-mono text-sm", toneCls)} title={value}>
        {value}
      </div>
    </div>
  );
}

function FlowLegend({
  completed,
  running,
  pending,
}: {
  completed: number;
  running: number;
  pending: number;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-x-3 font-mono text-[10px] text-muted-foreground">
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 align-middle" />
        {t("workflow.detail.legendDone")} {completed}
      </span>
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary align-middle" />
        {t("workflow.detail.legendRunning")} {running}
      </span>
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/60 align-middle" />
        {t("workflow.detail.legendPending")} {pending}
      </span>
    </div>
  );
}

function FlowNode({
  step,
  index,
  isLast,
  state,
}: {
  step: WorkflowStep;
  index: number;
  isLast: boolean;
  state: "done" | "running" | "pending";
}) {
  const Icon = KIND_ICON[step.kind];
  const tone = STEP_KIND_TONE[step.kind];
  const borderCls =
    state === "done"
      ? "border-emerald-400 bg-emerald-400/15"
      : state === "running"
        ? "border-primary bg-primary/15 flow-node-running animate-pulse-glow"
        : "border-dashed border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30";
  const iconCls =
    state === "done"
      ? "text-emerald-400"
      : state === "running"
        ? "text-primary"
        : "text-muted-foreground";

  return (
    <>
      <div className="flex min-w-[84px] shrink-0 flex-col items-center">
        <div
          className={cn(
            "relative flex h-10 w-10 items-center justify-center rounded-full border-2",
            borderCls,
          )}
        >
          {state === "done" ? (
            <Check className="h-5 w-5 text-emerald-400" />
          ) : (
            <Icon className={cn("h-5 w-5", iconCls)} />
          )}
          {state === "running" && (
            <span className="absolute inset-[-6px] animate-ping rounded-full border border-primary/30" />
          )}
        </div>
        <div
          className={cn(
            "mt-2 max-w-[96px] truncate text-[11px] leading-tight",
            state === "running" ? "font-semibold text-primary" : state === "done" ? "text-foreground" : "text-muted-foreground",
          )}
          title={step.name || step.ref || step.kind}
        >
          {step.name || step.ref || `${step.kind} ${index + 1}`}
        </div>
        <div
          className={cn(
            "mt-0.5 font-mono text-[10px]",
            state === "running" ? "text-primary" : "text-muted-foreground",
          )}
        >
          {tone.label}
        </div>
      </div>
      {!isLast && (
        <div className="flex-1 px-1 pt-5">
          {state === "running" ? (
            <div className="relative h-0.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]/60">
              <div className="flow-progress-bar" />
            </div>
          ) : state === "done" ? (
            <div className="h-0.5 w-full rounded-full bg-emerald-400/60" />
          ) : (
            <div className="h-0 w-full border-t-2 border-dashed border-[hsl(var(--border))]" />
          )}
        </div>
      )}
    </>
  );
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
