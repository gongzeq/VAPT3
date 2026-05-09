import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Clock,
  Globe,
  ShieldAlert,
  Timer,
  Users,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { TaskStatusBadge } from "@/components/TaskStatusBadge";
import { cn } from "@/lib/utils";
import { demoTask, type TaskFinding, type TaskModule } from "@/data/mock/task-detail";

// ─── Severity helpers ─────────────────────────────────────────────────────────

const SEVERITY_BORDER: Record<TaskFinding["severity"], string> = {
  critical: "border-l-rose-500",
  high: "border-l-orange-400",
  medium: "border-l-amber-400",
  low: "border-l-sky-400",
};

const SEVERITY_BADGE: Record<TaskFinding["severity"], string> = {
  critical: "bg-rose-500/20 text-rose-300",
  high: "bg-orange-400/20 text-orange-300",
  medium: "bg-amber-400/20 text-amber-300",
  low: "bg-sky-400/20 text-sky-300",
};

const CATEGORY_LABEL: Record<TaskFinding["category"], string> = {
  cve: "CVE",
  weak_password: "弱口令",
  misconfig: "配置缺陷",
  exposure: "信息泄露",
};

// ─── Info Card ────────────────────────────────────────────────────────────────

function InfoCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border/40 bg-card p-4 flex items-start gap-3">
      <Icon className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-0.5 text-sm font-medium text-foreground truncate">
          {value}
        </p>
      </div>
    </div>
  );
}

// ─── Module Progress Row ──────────────────────────────────────────────────────

function ModuleRow({ mod }: { mod: TaskModule }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border/40 p-3 hover:bg-accent/30 transition-colors">
      <div className="flex items-center gap-3 min-w-0">
        <TaskStatusBadge status={mod.status} />
        <span className="text-sm font-medium text-foreground truncate">
          {mod.name}
        </span>
        <span className="hidden sm:inline text-xs text-muted-foreground font-mono">
          {mod.agent}
        </span>
      </div>
      <div className="flex items-center gap-4 shrink-0">
        <span className="text-xs text-muted-foreground">
          {mod.startedAt}
          {mod.endedAt && ` → ${mod.endedAt}`}
        </span>
        {mod.findingsCount > 0 && (
          <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
            {mod.findingsCount} 发现
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Page Component ───────────────────────────────────────────────────────────

/**
 * /tasks/:id — Task detail surface (template §7.4).
 *
 * PR6 renders the demo task from mock data. When :id !== "demo", shows a
 * not-found hint. Real data will come from /api/scans/{id} once the backend
 * lands (gap doc covers the contract).
 */
export function TaskDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();

  // Only "demo" has data in PR6
  const task = id === "demo" ? demoTask : null;

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar
        title={
          task ? (
            <span className="flex items-center gap-3">
              {t("page.taskDetail.title", { defaultValue: "任务详情" })}
              {task && <TaskStatusBadge status={task.status} />}
            </span>
          ) : (
            t("page.taskDetail.title", { defaultValue: "任务详情" })
          )
        }
      />

      <main className="container flex-1 overflow-y-auto py-6 space-y-6">
        {!task ? (
          <div className="rounded-xl border border-border/40 bg-card p-8 text-center text-sm text-muted-foreground">
            {t("page.taskDetail.notFound", {
              defaultValue: `任务 "${id}" 不存在。试试 /tasks/demo 查看示例。`,
            })}
          </div>
        ) : (
          <>
            {/* ── Task Info Grid ── */}
            <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <InfoCard icon={Globe} label="目标" value={task.target} />
              <InfoCard icon={Calendar} label="创建时间" value={task.createdAt} />
              <InfoCard icon={Timer} label="耗时" value={task.duration} />
              <InfoCard icon={Users} label="使用智能体" value={`${task.agentsUsed} 个`} />
            </section>

            {/* ── Stats Row ── */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="rounded-xl border border-border/40 bg-card p-4 text-center">
                <p className="text-2xl font-bold text-foreground font-mono">
                  {task.totalFindings}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">总发现</p>
              </div>
              <div className="rounded-xl border border-border/40 bg-card p-4 text-center">
                <p className="text-2xl font-bold text-rose-400 font-mono">
                  {task.criticalCount}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">严重</p>
              </div>
              <div className="rounded-xl border border-border/40 bg-card p-4 text-center">
                <p className="text-2xl font-bold text-orange-400 font-mono">
                  {task.highCount}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">高危</p>
              </div>
              <div className="rounded-xl border border-border/40 bg-card p-4 text-center">
                <p className="text-2xl font-bold text-emerald-400 font-mono">
                  {task.modules.filter((m) => m.status === "completed").length}/
                  {task.modules.length}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">模块完成</p>
              </div>
            </section>

            {/* ── Module Progress ── */}
            <section className="rounded-xl border border-border/40 bg-card p-4">
              <h3 className="mb-3 text-sm font-semibold text-foreground flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                {t("page.taskDetail.modules", { defaultValue: "模块进度" })}
              </h3>
              <div className="space-y-2">
                {task.modules.map((mod) => (
                  <ModuleRow key={mod.agent} mod={mod} />
                ))}
              </div>
            </section>

            {/* ── Findings Table ── */}
            <section className="rounded-xl border border-border/40 bg-card p-4">
              <h3 className="mb-3 text-sm font-semibold text-foreground flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-muted-foreground" />
                {t("page.taskDetail.findings", { defaultValue: "安全发现" })}
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted-foreground border-b border-border/40">
                      <th className="py-2 pr-4 text-left font-medium">漏洞</th>
                      <th className="py-2 pr-4 text-left font-medium">严重度</th>
                      <th className="py-2 pr-4 text-left font-medium">类型</th>
                      <th className="py-2 pr-4 text-left font-medium">目标</th>
                      <th className="py-2 text-left font-medium">发现时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {task.findings.map((f) => (
                      <tr
                        key={f.id}
                        className={cn(
                          "border-l-4 hover:bg-accent/30 transition-colors",
                          SEVERITY_BORDER[f.severity],
                        )}
                      >
                        <td className="py-2.5 pr-4 font-medium text-foreground max-w-[240px] truncate">
                          {f.title}
                        </td>
                        <td className="py-2.5 pr-4">
                          <span
                            className={cn(
                              "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                              SEVERITY_BADGE[f.severity],
                            )}
                          >
                            {f.severity}
                          </span>
                        </td>
                        <td className="py-2.5 pr-4 text-muted-foreground">
                          {CATEGORY_LABEL[f.category]}
                        </td>
                        <td className="py-2.5 pr-4 font-mono text-xs text-muted-foreground">
                          {f.target}
                        </td>
                        <td className="py-2.5 text-xs text-muted-foreground">
                          {f.foundAt}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default TaskDetailPage;
