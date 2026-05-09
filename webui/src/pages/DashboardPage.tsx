import { useTranslation } from "react-i18next";
import { Navbar } from "@/components/Navbar";

/**
 * /dashboard — placeholder until PR5 lands the full ECharts + KPI layout
 * (R4.3). For now we render the shared Navbar + a "coming soon" card so the
 * route is reachable and the visual chrome (sticky h-16 backdrop-blur) is
 * already validated.
 */
export function DashboardPage() {
  const { t } = useTranslation();
  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar title={t("nav.dashboard", { defaultValue: "大屏" })} />
      <main className="container py-6 space-y-6">
        <div className="rounded-xl border border-border/40 bg-card p-8 text-center text-sm text-muted-foreground">
          {t("page.dashboard.placeholder", {
            defaultValue: "Dashboard 即将上线（PR5 · R4.3）",
          })}
        </div>
      </main>
    </div>
  );
}

export default DashboardPage;
