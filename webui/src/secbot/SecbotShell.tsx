import { useState } from "react";

import { AnimatedGridPattern } from "@/components/magicui/animated-grid-pattern";
import { cn } from "@/lib/utils";

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
 *
 * Ocean-tech styling (PR4-R5):
 *   - Top nav is a brand-deep tinted "HUD" bar with an `<AnimatedGridPattern>`
 *     backdrop (respects `motion-reduce` via its own framer-motion transition —
 *     we additionally hide the overlay under `motion-reduce:hidden` to keep a
 *     completely static surface for users who opt out).
 *   - Active tab: primary background + underline glow (brand-deep → primary
 *     gradient). Inactive tabs: brand-light hover tint only, no bg change.
 */
export function SecbotShell({ defaultTab = "chat" as Tab }: { defaultTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(defaultTab);
  return (
    <div className="flex h-screen flex-col bg-background text-text-primary">
      <nav className="relative flex items-center gap-4 overflow-hidden border-b border-[hsl(var(--brand-deep)/0.25)] bg-card px-4 py-2">
        {/* Decorative HUD grid — aria-hidden, motion-safe only */}
        <AnimatedGridPattern
          aria-hidden
          numSquares={18}
          maxOpacity={0.18}
          duration={5}
          className={cn(
            "pointer-events-none absolute inset-0 -z-0",
            "[mask-image:radial-gradient(420px_circle_at_top,white,transparent)]",
            "fill-[hsl(var(--brand-light)/0.35)] stroke-[hsl(var(--brand-deep)/0.25)]",
            "motion-reduce:hidden",
          )}
        />
        {/* brand-deep wash */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-0"
          style={{
            background:
              "linear-gradient(90deg, hsl(var(--brand-deep) / 0.10) 0%, transparent 40%, transparent 60%, hsl(var(--brand-deep) / 0.08) 100%)",
          }}
        />
        <span className="relative z-[1] text-sm font-semibold tracking-wide">
          secbot
        </span>
        <div className="relative z-[1] flex gap-1">
          {TABS.map((t) => {
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                aria-pressed={active}
                className={cn(
                  "relative rounded-md px-3 py-1 text-sm transition",
                  "motion-reduce:transition-none",
                  active
                    ? "bg-primary text-primary-foreground shadow-[0_0_10px_hsl(var(--primary)/0.35)]"
                    : "text-text-secondary hover:bg-[hsl(var(--brand-light)/0.10)] hover:text-text-primary",
                )}
              >
                {t.label}
                {active && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute -bottom-[3px] left-2 right-2 h-[2px] rounded-full bg-gradient-to-r from-[hsl(var(--brand-deep))] via-[hsl(var(--primary))] to-[hsl(var(--brand-light))]"
                  />
                )}
              </button>
            );
          })}
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
