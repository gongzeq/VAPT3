import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { useClient } from "@/providers/ClientProvider";
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
import {
  LeftFilter,
  type StatusFilter,
  type CountBundle,
} from "@/pages/workflow/LeftFilter";
import { WorkflowListCard } from "@/pages/workflow/WorkflowListCard";
import {
  RightAside,
  EmptyState,
  CardListSkeleton,
  FailedRunsDialog,
} from "@/pages/workflow/RightAside";

const DRAFT_STORAGE_KEY = "workflow.pending-draft";

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
  // Token rotates (~every 5min on 401 refresh); read it via a ref so the
  // memoized client isn't rebuilt on rotation (avoids needless refetch).
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const client = useMemo(
    () =>
      new WorkflowClient({
        token: () => tokenRef.current,
        baseUrl: workflowApiBase,
      }),
    [workflowApiBase],
  );

  const [data, setData] = useState<WorkflowListResponse | null>(null);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [tag, setTag] = useState<string>("");
  const [failedOpen, setFailedOpen] = useState(false);
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

  const counts = useMemo((): CountBundle => {
    const all = data?.items.length ?? 0;
    const scheduled = data?.items.filter((w) => !!w.scheduleRef).length ?? 0;
    const manual = all - scheduled;
    return {
      all,
      scheduled,
      manual,
      running: data?.stats.running ?? 0,
      runningIds: data?.stats.runningIds ?? [],
      failed24h: data?.stats.failed24h ?? 0,
    };
  }, [data]);

  const visible = useMemo(() => {
    if (!data) return [] as Workflow[];
    const q = search.trim().toLowerCase();
    return data.items.filter((wf) => {
      if (statusFilter === "scheduled" && !wf.scheduleRef) return false;
      if (statusFilter === "manual" && wf.scheduleRef) return false;
      if (statusFilter === "running" && !counts.runningIds.includes(wf.id)) return false;
      if (tag && !wf.tags.includes(tag)) return false;
      if (!q) return true;
      return (
        wf.name.toLowerCase().includes(q) ||
        wf.description.toLowerCase().includes(q) ||
        wf.tags.some((x) => x.toLowerCase().includes(q))
      );
    });
  }, [data, search, statusFilter, tag, counts.runningIds]);

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
              onOpenFailedRuns={() => setFailedOpen(true)}
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
                <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
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

      <AlertDialog open={!!toDelete} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("workflow.deleteDialog.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("workflow.deleteDialog.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("workflow.deleteDialog.cancel")}</AlertDialogCancel>
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

      <FailedRunsDialog open={failedOpen} onOpenChange={setFailedOpen} client={client} />
    </div>
  );
}

export default WorkflowListPage;

/** Exported so the detail page can pop the same stash. */
export { DRAFT_STORAGE_KEY };
