import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  CalendarClock,
  ChevronRight,
  History,
  ListChecks,
  Loader2,
  Settings2,
} from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { RunDialog } from "@/components/workflow/RunDialog";
import { RunHistoryTab } from "@/components/workflow/RunHistoryTab";
import { ScheduleTab } from "@/components/workflow/ScheduleTab";
import { StepEditor } from "@/components/workflow/StepEditor";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import { BasicTab } from "@/pages/workflow/BasicTab";
import {
  WorkflowHeaderCard,
} from "@/pages/workflow/WorkflowHeaderCard";
import {
  WorkflowClient,
  emptyWorkflowDraft,
  type AgentMeta,
  type ToolMeta,
  type Workflow,
  type WorkflowDraft,
  type WorkflowRun,
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

  // ─── Clone (create copy) ───────────────────────────────────────────
  function handleClone() {
    if (!saved) return;
    const cloned: WorkflowDraft = {
      name: `${saved.name} (副本)`,
      description: saved.description,
      tags: [...saved.tags],
      inputs: JSON.parse(JSON.stringify(saved.inputs)),
      steps: JSON.parse(JSON.stringify(saved.steps)),
      scheduleRef: null,
    };
    try {
      sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(cloned));
    } catch {
      // Safari private mode fallback
    }
    // Force full page reload to ensure the new route mounts fresh and
    // picks up the stashed draft from sessionStorage.
    window.location.href = "/workflows/new";
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
            onClone={handleClone}
            onCancelRun={() =>
              saved ? void client.cancel(saved.id).then(() => setRunRefreshKey((n) => n + 1)) : undefined
            }
          />

          {(loadErr || saveErr || runStartErr) && (
            <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
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
