import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  CalendarClock,
  PlayCircle,
  Plus,
  Search,
  Trash2,
  Workflow as WorkflowIcon,
} from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { TemplateGallery } from "@/components/workflow/TemplateGallery";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import {
  WorkflowClient,
  emptyWorkflowDraft,
  type Workflow,
  type WorkflowDraft,
  type WorkflowListResponse,
  type WorkflowTemplate,
} from "@/lib/workflow-client";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const DRAFT_STORAGE_KEY = "workflow.pending-draft";

/**
 * ``/workflows`` — landing page for the workflow builder.
 *
 * Three surfaces stack vertically:
 *   1. Stats header (running / scheduled / failed24h)
 *   2. Template gallery (clone-to-draft entry point)
 *   3. Workflow grid with search + tag filter
 *
 * Creation flow: pressing "New" or picking a template stashes the draft
 * under ``sessionStorage[DRAFT_STORAGE_KEY]`` and navigates to
 * ``/workflows/new``. The detail page then either loads the stashed
 * draft (on ``/new``) or fetches via id. We keep the draft in storage
 * rather than route state so a refresh doesn't lose it.
 */
export function WorkflowListPage() {
  const { t } = useTranslation();
  const { token, workflowApiBase } = useClient();
  const navigate = useNavigate();
  const client = useMemo(
    () => new WorkflowClient({ token, baseUrl: workflowApiBase }),
    [token, workflowApiBase],
  );

  const [data, setData] = useState<WorkflowListResponse | null>(null);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState<string>("");
  const [toDelete, setToDelete] = useState<Workflow | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadList = useMemo(
    () => async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await client.list();
        setData(res);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await client.listTemplates();
        if (!cancelled) setTemplates(res.items);
      } catch {
        // Template endpoint failure is non-fatal — hide the gallery.
        if (!cancelled) setTemplates([]);
      } finally {
        if (!cancelled) setTemplatesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  // Aggregate the tag universe across workflows so the filter can
  // present every tag in use. The empty string represents "no filter".
  const allTags = useMemo(() => {
    if (!data) return [] as string[];
    const set = new Set<string>();
    for (const wf of data.items) for (const t of wf.tags) set.add(t);
    return Array.from(set).sort();
  }, [data]);

  const visible = useMemo(() => {
    if (!data) return [] as Workflow[];
    const q = search.trim().toLowerCase();
    return data.items.filter((wf) => {
      if (tag && !wf.tags.includes(tag)) return false;
      if (!q) return true;
      return (
        wf.name.toLowerCase().includes(q) ||
        wf.description.toLowerCase().includes(q) ||
        wf.tags.some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [data, search, tag]);

  function stashDraftAndNavigate(draft: WorkflowDraft) {
    try {
      sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
    } catch {
      // Safari private mode etc. — fall through; detail page will boot
      // an empty draft instead of the intended template.
    }
    navigate("/workflows/new");
  }

  function handleCreateBlank() {
    stashDraftAndNavigate(emptyWorkflowDraft());
  }

  function handlePickTemplate(tpl: WorkflowTemplate) {
    // Deep-clone the template's embedded draft so edits never mutate
    // the gallery copy (which may still live in React state).
    const cloned: WorkflowDraft = JSON.parse(JSON.stringify(tpl.workflow));
    cloned.name = cloned.name || tpl.name;
    stashDraftAndNavigate(cloned);
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await client.remove(toDelete.id);
      setToDelete(null);
      await loadList();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <Navbar />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1600px] space-y-6 px-6 py-6">
          {/* Header row */}
          <div className="animate-fade-in-up flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="flex items-center gap-2 text-2xl font-semibold text-foreground">
                <WorkflowIcon className="h-6 w-6 text-primary" />
                {t("workflow.listTitle")}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("workflow.listSubtitle")}
              </p>
            </div>
            <button
              type="button"
              onClick={handleCreateBlank}
              className="gradient-primary hover-lift inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-md"
            >
              <Plus className="h-4 w-4" />
              {t("workflow.createNew")}
            </button>
          </div>

          {/* Stats */}
          <div className="animate-fade-in-up grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard
              tone="primary"
              icon={<PlayCircle className="h-4 w-4" />}
              label={t("workflow.stats.running")}
              value={data?.stats.running ?? 0}
            />
            <StatCard
              tone="emerald"
              icon={<CalendarClock className="h-4 w-4" />}
              label={t("workflow.stats.scheduled")}
              value={data?.stats.scheduled ?? 0}
            />
            <StatCard
              tone="rose"
              icon={<AlertCircle className="h-4 w-4" />}
              label={t("workflow.stats.failed24h")}
              value={data?.stats.failed24h ?? 0}
            />
          </div>

          <TemplateGallery
            templates={templates}
            loading={templatesLoading}
            onPick={handlePickTemplate}
          />

          {/* Filter bar */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("workflow.search")}
                className="h-10 w-full rounded-xl border border-[hsl(var(--border))] bg-background/40 pl-10 pr-3 text-sm outline-none transition-colors focus:border-primary/50"
              />
            </div>
            {allTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {t("workflow.filterTag")}
                </span>
                <TagChip
                  active={tag === ""}
                  label={t("workflow.filterAll")}
                  onClick={() => setTag("")}
                />
                {allTags.map((x) => (
                  <TagChip
                    key={x}
                    active={tag === x}
                    label={x}
                    onClick={() => setTag(tag === x ? "" : x)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Body */}
          {error && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
              {t("workflow.error.load")}: {error}
            </div>
          )}
          {loading && !data ? (
            <GridSkeleton />
          ) : visible.length === 0 ? (
            <EmptyState onCreate={handleCreateBlank} />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visible.map((wf) => (
                <WorkflowCard
                  key={wf.id}
                  workflow={wf}
                  onOpen={() => navigate(`/workflows/${wf.id}`)}
                  onDelete={() => setToDelete(wf)}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      <AlertDialog
        open={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("workflow.deleteDialog.title")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("workflow.deleteDialog.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t("workflow.deleteDialog.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                void confirmDelete();
              }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t("workflow.deleteDialog.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default WorkflowListPage;

// ─── Subcomponents (page-local) ─────────────────────────────────────────

function StatCard({
  tone,
  icon,
  label,
  value,
}: {
  tone: "primary" | "emerald" | "rose";
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  const toneCls =
    tone === "primary"
      ? "text-primary border-primary/30"
      : tone === "emerald"
        ? "text-emerald-400 border-emerald-500/30"
        : "text-rose-400 border-rose-500/30";
  return (
    <div className="gradient-card flex items-center gap-4 rounded-2xl border border-[hsl(var(--border))] p-4">
      <div
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-xl border bg-background/40",
          toneCls,
        )}
      >
        {icon}
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold tabular-nums text-foreground">
          {value}
        </p>
      </div>
    </div>
  );
}

function TagChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs transition-colors",
        active
          ? "border-primary/50 bg-primary/10 text-primary"
          : "border-border/40 bg-muted/30 text-muted-foreground hover:border-primary/30",
      )}
    >
      {label}
    </button>
  );
}

function WorkflowCard({
  workflow,
  onOpen,
  onDelete,
}: {
  workflow: Workflow;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { t, i18n } = useTranslation();
  const updated = new Date(workflow.updatedAtMs).toLocaleString(
    i18n.resolvedLanguage || "zh-CN",
  );
  return (
    <div className="gradient-card hover-lift group flex flex-col gap-3 rounded-2xl border border-[hsl(var(--border))] p-5 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={onOpen}
          className="min-w-0 flex-1 text-left"
        >
          <h3 className="truncate text-base font-semibold text-foreground transition-colors group-hover:text-primary">
            {workflow.name || workflow.id}
          </h3>
          {workflow.description && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {workflow.description}
            </p>
          )}
        </button>
        <button
          type="button"
          aria-label={t("workflow.card.delete")}
          onClick={onDelete}
          className="shrink-0 rounded-lg border border-border/40 p-1.5 text-muted-foreground transition-colors hover:border-rose-500/50 hover:text-rose-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        {workflow.tags.map((tag) => (
          <span
            key={tag}
            className="rounded-full border border-border/40 bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground"
          >
            {tag}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {t("workflow.card.steps", { count: workflow.steps.length })}
        </span>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5",
            workflow.scheduleRef
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              : "border-border/40 bg-muted/30",
          )}
        >
          {workflow.scheduleRef
            ? t("workflow.card.scheduled")
            : t("workflow.card.unscheduled")}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">
          {t("workflow.card.updated", { time: updated })}
        </span>
        <button
          type="button"
          onClick={onOpen}
          className="rounded-lg border border-primary/40 bg-primary/10 px-3 py-1 text-xs text-primary transition-colors hover:bg-primary/15"
        >
          {t("workflow.card.open")}
        </button>
      </div>
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border/40 bg-muted/20 py-16">
      <WorkflowIcon className="h-8 w-8 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">{t("workflow.empty")}</p>
      <button
        type="button"
        onClick={onCreate}
        className="gradient-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-md"
      >
        <Plus className="h-4 w-4" />
        {t("workflow.createNew")}
      </button>
    </div>
  );
}

function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-2xl border border-border/40 bg-muted/30"
        />
      ))}
    </div>
  );
}

/** Exported so the detail page can pop the same stash. */
export { DRAFT_STORAGE_KEY };
