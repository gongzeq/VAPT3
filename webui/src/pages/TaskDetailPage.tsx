import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Navbar } from "@/components/Navbar";

/**
 * /tasks/:id — placeholder until PR6 wraps SecbotShell into the TaskDetail
 * surface (R4.4). The route already accepts the `:id` param so future work
 * just plugs in mock data + the existing Asset/Reports/ScanHistory tabs.
 */
export function TaskDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar
        title={t("page.taskDetail.title", {
          defaultValue: "任务详情",
        })}
      />
      <main className="container py-6 space-y-6">
        <div className="rounded-xl border border-border/40 bg-card p-8 text-sm text-muted-foreground">
          <p>
            {t("page.taskDetail.placeholder", {
              defaultValue: "任务详情即将上线（PR6 · R4.4）",
            })}
          </p>
          <p className="mt-2 font-mono text-xs">
            taskId: {id ?? "<none>"}
          </p>
        </div>
      </main>
    </div>
  );
}

export default TaskDetailPage;
