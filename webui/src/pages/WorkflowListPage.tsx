import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Bot,
  Brain,
  Clock,
  FileText,
  Layers,
  Pause,
  PlayCircle,
  Plus,
  Search,
  Sparkles,
  Terminal,
  TriangleAlert,
  Trash2,
  Workflow as WorkflowIcon,
  Wrench,
} from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import {
  WorkflowClient,
  emptyWorkflowDraft,
  STEP_KIND_TONE,
  type StepKind,
  type Workflow,
  type WorkflowDraft,
  type WorkflowListResponse,
  type WorkflowStep,
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

type StatusFilter = "all" | "scheduled" | "draft";

/**
 * ``/workflows`` — prototype §ListView 三栏还原:
 *   ├─ 左栏 (260px)  状态/标签过滤
 *   ├─ 中栏 (1fr)   搜索 + 工作流卡片（含 mini-flow 步骤链）
 *   └─ 右栏 (300px) 今日态势 + 模板推荐
 *
 * 创建流程：点击"新建"或选模板 → sessionStorage 暂存 draft → 跳
 * `/workflows/new`。刷新不丢失；stashing 失败（Safari 隐私模式）时退回空 draft。
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
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
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
        if (!cancelled) setTemplates([]);
      } finally {
        if (!cancelled) setTemplatesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  const allTags = useMemo(() => {
    if (!data) return [] as string[];
    const set = new Set<string>();
    for (const wf of data.items) for (const x of wf.tags) set.add(x);
    return Array.from(set).sort();
  }, [data]);

  // 计数拆分：scheduled (有 scheduleRef) / draft (无)。"running" 和
  // "failed" 依赖 stats（后端级聚合），卡片级状态做不到。
  const counts = useMemo(() => {
    const all = data?.items.length ?? 0;
    const scheduled = data?.items.filter((w) => !!w.scheduleRef).length ?? 0;
    const draft = all - scheduled;
    return {
      all,
      scheduled,
      draft,
      running: data?.stats.running ?? 0,
      failed24h: data?.stats.failed24h ?? 0,
    };
  }, [data]);

  const visible = useMemo(() => {
    if (!data) return [] as Workflow[];
    const q = search.trim().toLowerCase();
    return data.items.filter((wf) => {
      if (statusFilter === "scheduled" && !wf.scheduleRef) return false;
      if (statusFilter === "draft" && wf.scheduleRef) return false;
      if (tag && !wf.tags.includes(tag)) return false;
      if (!q) return true;
      return (
        wf.name.toLowerCase().includes(q) ||
        wf.description.toLowerCase().includes(q) ||
        wf.tags.some((x) => x.toLowerCase().includes(q))
      );
    });
  }, [data, search, statusFilter, tag]);

  function stashDraftAndNavigate(draft: WorkflowDraft) {
    try {
      sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
    } catch {
      // Safari private mode — detail page booted an empty draft instead.
    }
    navigate("/workflows/new");
  }

  function handleCreateBlank() {
    stashDraftAndNavigate(emptyWorkflowDraft());
  }

  function handlePickTemplate(tpl: WorkflowTemplate) {
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
        <div className="mx-auto max-w-[1600px] px-6 py-6">
          <div className="grid gap-6 lg:grid-cols-[260px_1fr_300px]">
            <LeftFilter
              counts={counts}
              statusFilter={statusFilter}
              setStatusFilter={setStatusFilter}
              tag={tag}
              setTag={setTag}
              allTags={allTags}
              onCreate={handleCreateBlank}
            />

            <section className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={t("workflow.search")}
                    className="h-10 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 pl-10 pr-3 text-sm outline-none transition-colors focus:border-primary/50"
                  />
                </div>
              </div>

              {error && (
                <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
                  {t("workflow.error.load")}: {error}
                </div>
              )}

              {loading && !data ? (
                <CardListSkeleton />
              ) : visible.length === 0 ? (
                <EmptyState onCreate={handleCreateBlank} />
              ) : (
                <ul className="space-y-4">
                  {visible.map((wf) => (
                    <li key={wf.id}>
                      <WorkflowListCard
                        workflow={wf}
                        onOpen={() => navigate(`/workflows/${wf.id}`)}
                        onDelete={() => setToDelete(wf)}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <RightAside
              counts={counts}
              templates={templates}
              templatesLoading={templatesLoading}
              onPickTemplate={handlePickTemplate}
            />
          </div>
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

// ─── Left filter ────────────────────────────────────────────────────────

interface CountBundle {
  all: number;
  scheduled: number;
  draft: number;
  running: number;
  failed24h: number;
}

function LeftFilter({
  counts,
  statusFilter,
  setStatusFilter,
  tag,
  setTag,
  allTags,
  onCreate,
}: {
  counts: CountBundle;
  statusFilter: StatusFilter;
  setStatusFilter: (v: StatusFilter) => void;
  tag: string;
  setTag: (v: string) => void;
  allTags: string[];
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="gradient-card h-fit space-y-5 rounded-2xl border border-[hsl(var(--border))] p-4">
      <button
        type="button"
        onClick={onCreate}
        className="gradient-primary hover-lift inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-md"
      >
        <Plus className="h-4 w-4" />
        {t("workflow.createNew")}
      </button>

      <div>
        <p className="px-2 text-[10px] uppercase tracking-wider text-muted-foreground">
          {t("workflow.filter.statusTitle")}
        </p>
        <ul className="mt-1 space-y-1 text-sm">
          <StatusRow
            active={statusFilter === "all"}
            onClick={() => setStatusFilter("all")}
            icon={<Layers className="h-3.5 w-3.5" />}
            label={t("workflow.filter.statusAll")}
            count={counts.all}
          />
          <StatusRow
            active={false}
            onClick={() => {
              /* 运行中需要 run-level 过滤，未落地时仅展示计数 */
            }}
            icon={<PlayCircle className="h-3.5 w-3.5 text-emerald-400" />}
            label={t("workflow.filter.statusRunning")}
            count={counts.running}
            tone="emerald"
            disabled
          />
          <StatusRow
            active={statusFilter === "scheduled"}
            onClick={() => setStatusFilter("scheduled")}
            icon={<Clock className="h-3.5 w-3.5 text-primary" />}
            label={t("workflow.filter.statusScheduled")}
            count={counts.scheduled}
          />
          <StatusRow
            active={statusFilter === "draft"}
            onClick={() => setStatusFilter("draft")}
            icon={<Pause className="h-3.5 w-3.5 text-muted-foreground" />}
            label={t("workflow.filter.statusDraft")}
            count={counts.draft}
          />
          <StatusRow
            active={false}
            onClick={() => {
              /* failed 只有 run 维度，这里仅展示 24h 统计 */
            }}
            icon={<TriangleAlert className="h-3.5 w-3.5 text-rose-400" />}
            label={t("workflow.filter.statusFailed")}
            count={counts.failed24h}
            tone="rose"
            disabled
          />
        </ul>
      </div>

      {allTags.length > 0 && (
        <div>
          <p className="px-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            {t("workflow.filter.tagsTitle")}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5 px-1">
            {allTags.map((x) => {
              const active = tag === x;
              return (
                <button
                  key={x}
                  type="button"
                  onClick={() => setTag(active ? "" : x)}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs transition-colors",
                    active
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 hover:border-primary/40",
                  )}
                >
                  #{x}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </aside>
  );
}

function StatusRow({
  active,
  onClick,
  icon,
  label,
  count,
  tone,
  disabled,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count: number;
  tone?: "emerald" | "rose";
  disabled?: boolean;
}) {
  const toneCls =
    tone === "emerald"
      ? "text-emerald-400"
      : tone === "rose"
        ? "text-rose-400"
        : "";
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition-colors",
          active
            ? "border border-primary/30 bg-primary/10 text-primary"
            : "hover:bg-white/5",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <span className={cn("inline-flex items-center gap-2", toneCls)}>
          {icon} {label}
        </span>
        <span className="font-mono text-xs text-muted-foreground">
          {count}
        </span>
      </button>
    </li>
  );
}

// ─── Right aside ────────────────────────────────────────────────────────

function RightAside({
  counts,
  templates,
  templatesLoading,
  onPickTemplate,
}: {
  counts: CountBundle;
  templates: WorkflowTemplate[];
  templatesLoading: boolean;
  onPickTemplate: (tpl: WorkflowTemplate) => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="space-y-4">
      <div className="gradient-card space-y-3 rounded-2xl border border-[hsl(var(--border))] p-5">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">
            {t("workflow.stats.todayTitle")}
          </h4>
          <span className="text-xs text-muted-foreground">
            {t("workflow.stats.live")}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <MiniStat
            label={t("workflow.stats.scheduled")}
            value={counts.scheduled}
            valueCls="text-primary"
          />
          <MiniStat
            label={t("workflow.stats.running")}
            value={counts.running}
            valueCls="text-gradient"
          />
          <MiniStat
            label={t("workflow.stats.total")}
            value={counts.all}
          />
          <MiniStat
            label={t("workflow.stats.failed24h")}
            value={counts.failed24h}
            valueCls={counts.failed24h > 0 ? "text-rose-400" : ""}
          />
        </div>
      </div>

      <div className="gradient-card space-y-3 rounded-2xl border border-[hsl(var(--border))] p-5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h4 className="text-sm font-semibold">
            {t("workflow.templates.title")}
          </h4>
        </div>
        {templatesLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-14 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40"
              />
            ))}
          </div>
        ) : templates.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("workflow.templates.empty")}
          </p>
        ) : (
          <div className="space-y-2">
            {templates.slice(0, 4).map((tpl) => (
              <button
                key={tpl.id}
                type="button"
                onClick={() => onPickTemplate(tpl)}
                className="group w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-2.5 text-left text-sm transition hover:border-primary/40 hover:bg-primary/5"
              >
                <div className="flex items-center gap-2 font-medium">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                  <span className="truncate">{tpl.name}</span>
                </div>
                {tpl.description && (
                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                    {tpl.description}
                  </p>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

function MiniStat({
  label,
  value,
  valueCls,
}: {
  label: string;
  value: number;
  valueCls?: string;
}) {
  return (
    <div className="hover-lift cursor-default rounded-lg bg-[hsl(var(--muted))]/40 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-2xl font-bold tabular-nums text-foreground",
          valueCls,
        )}
      >
        {value}
      </div>
    </div>
  );
}

// ─── Workflow card (with mini-flow) ─────────────────────────────────────

function WorkflowListCard({
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
  const status: StatusFilter = workflow.scheduleRef ? "scheduled" : "draft";
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "gradient-card hover-lift animate-fade-in-up block cursor-pointer rounded-2xl border p-5",
        status === "scheduled"
          ? "border-primary/30"
          : "border-[hsl(var(--border))]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <StatusBadge status={status} />
            <span className="rounded-md bg-[hsl(var(--muted))]/60 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              {workflow.id}
            </span>
            {workflow.tags.slice(0, 3).map((tg) => (
              <span
                key={tg}
                className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-2 py-0.5 text-[10px] text-muted-foreground"
              >
                #{tg}
              </span>
            ))}
          </div>
          <h3 className="truncate text-base font-semibold text-foreground">
            {workflow.name || workflow.id}
          </h3>
          {workflow.description && (
            <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
              {workflow.description}
            </p>
          )}
        </div>
        <button
          type="button"
          aria-label={t("workflow.card.delete")}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-white/5 hover:text-rose-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {workflow.steps.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
          <MiniFlow steps={workflow.steps} />
        </div>
      )}

      <div className="mt-4 grid grid-cols-4 gap-3 text-xs">
        <FactCell
          label={t("workflow.card.stepsLabel")}
          value={String(workflow.steps.length)}
        />
        <FactCell
          label={t("workflow.card.inputsLabel")}
          value={String(workflow.inputs.length)}
        />
        <FactCell
          label={t("workflow.card.scheduleLabel")}
          value={
            workflow.scheduleRef
              ? t("workflow.card.scheduled")
              : t("workflow.card.unscheduled")
          }
          valueCls={
            workflow.scheduleRef ? "text-primary" : "text-muted-foreground"
          }
        />
        <FactCell
          label={t("workflow.card.updatedLabel")}
          value={updated}
          mono={false}
        />
      </div>
    </div>
  );
}

function FactCell({
  label,
  value,
  valueCls,
  mono = true,
}: {
  label: string;
  value: string;
  valueCls?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 truncate text-sm text-foreground",
          mono && "font-mono",
          valueCls,
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: StatusFilter }) {
  const { t } = useTranslation();
  if (status === "scheduled") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5 font-mono text-[10px] text-primary">
        <Clock className="h-3 w-3" /> {t("workflow.badge.scheduled")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-2.5 py-0.5 font-mono text-[10px] text-muted-foreground">
      <FileText className="h-3 w-3" /> {t("workflow.badge.draft")}
    </span>
  );
}

const KIND_ICON: Record<StepKind, React.ComponentType<{ className?: string }>> =
  {
    tool: Wrench,
    script: Terminal,
    agent: Bot,
    llm: Brain,
  };

function MiniFlow({ steps }: { steps: WorkflowStep[] }) {
  const head = steps.slice(0, 5);
  const more = Math.max(0, steps.length - head.length);
  return (
    <>
      {head.map((step, i) => {
        const Icon = KIND_ICON[step.kind];
        const tone = STEP_KIND_TONE[step.kind];
        return (
          <span key={step.id} className="inline-flex items-center gap-1">
            {i > 0 && (
              <ArrowRight className="h-3 w-3 text-muted-foreground" />
            )}
            <span
              className={cn(
                "inline-flex max-w-[120px] items-center gap-1 rounded-md border px-1.5 py-0.5",
                tone.badge,
              )}
              title={step.name || step.ref || step.kind}
            >
              <Icon className="h-3 w-3 shrink-0" />
              <span className="truncate">
                {step.name || step.ref || step.kind}
              </span>
            </span>
          </span>
        );
      })}
      {more > 0 && (
        <span className="text-muted-foreground">+{more}</span>
      )}
    </>
  );
}

// ─── Empty / loading ────────────────────────────────────────────────────

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

function CardListSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, i) => (
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
