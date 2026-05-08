import { useState } from "react";

import { SecbotThread } from "./SecbotThread";
import { AssetsView } from "./views/AssetsView";
import { ScanHistoryView } from "./views/ScanHistoryView";
import { ReportsView } from "./views/ReportsView";

type Tab = "chat" | "assets" | "scans" | "reports";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "对话" },
  { id: "assets", label: "资产" },
  { id: "scans", label: "扫描历史" },
  { id: "reports", label: "报告" },
];

/**
 * Top-level shell for the secbot WebUI.
 * Hosts the 4 main surfaces:
 *   - chat: conversational orchestrator (assistant-ui Thread + skill UIs)
 *   - assets / scans / reports: read-only operator dashboards backed by REST
 *
 * Routing is intentionally trivial (in-memory tab) — adding react-router only
 * once we need deep links.
 */
export function SecbotShell({ defaultTab = "chat" as Tab }: { defaultTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(defaultTab);
  return (
    <div className="flex h-screen flex-col bg-background text-text-primary">
      <nav className="flex items-center gap-4 border-b border-border bg-card px-4 py-2">
        <span className="text-sm font-semibold tracking-wide">secbot</span>
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`rounded px-3 py-1 text-sm transition ${
                tab === t.id
                  ? "bg-primary text-primary-foreground"
                  : "text-text-secondary hover:bg-background/40 hover:text-text-primary"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>
      <main className="min-h-0 flex-1 overflow-auto">
        {tab === "chat" && <SecbotThread />}
        {tab === "assets" && <AssetsView />}
        {tab === "scans" && <ScanHistoryView />}
        {tab === "reports" && <ReportsView />}
      </main>
    </div>
  );
}
