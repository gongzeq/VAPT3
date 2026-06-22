/**
 * Layout shell for the Threat Intel workspace.
 *
 * PRD §7.1: the threat intel module uses a **light** visual style
 * (background ``#F5F7FA``) to distinguish it from the dark VAPT console.
 * This layout applies the light background and renders the Navbar + Outlet.
 *
 * Also subscribes to global ``agent_event`` frames for feed failure
 * notifications and shows a dismissible toast.
 */

import { useEffect, useState, useCallback } from "react";
import { Outlet, NavLink } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { LayoutDashboard, Users, GitBranch, Bug, Shield, Eye, FileWarning, ClipboardCheck, Rss, X, AlertCircle } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

interface FeedFailureToast {
  source: string;
  error_message: string;
  run_id: string;
}

const navItems = [
  { to: "/threat-intel", label: "概览", icon: LayoutDashboard, end: true },
  { to: "/threat-intel/groups", label: "威胁组织", icon: Users },
  { to: "/threat-intel/graph", label: "知识图谱", icon: GitBranch },
  { to: "/threat-intel/vulns", label: "漏洞", icon: Shield },
  { to: "/threat-intel/malware", label: "木马样本", icon: Bug },
  { to: "/threat-intel/maritime", label: "海事事件", icon: FileWarning },
  { to: "/threat-intel/watchlist", label: "关注管理", icon: Eye },
  { to: "/threat-intel/review", label: "复核队列", icon: ClipboardCheck },
  { to: "/threat-intel/feeds", label: "Feed运行", icon: Rss },
];

export function ThreatIntelLayout() {
  const { client } = useClient();
  const [toasts, setToasts] = useState<FeedFailureToast[]>([]);

  const dismissToast = useCallback((runId: string) => {
    setToasts((prev) => prev.filter((t) => t.run_id !== runId));
  }, []);

  useEffect(() => {
    const unsub = client.onGlobalAgentEvent((payload, type) => {
      if (type !== "threat_intel_feed_failed") return;
      const data = payload as unknown as FeedFailureToast;
      setToasts((prev) => [...prev, data]);
      // Auto-dismiss after 10 seconds
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.run_id !== data.run_id));
      }, 10_000);
    });
    return unsub;
  }, [client]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Navbar />
      <nav className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1600px] items-center gap-1 px-6 py-2 overflow-x-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-indigo-50 text-indigo-600"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            );
          })}
        </div>
      </nav>
      <main className="mx-auto max-w-[1600px] px-6 py-6">
        <Outlet />
      </main>

      {/* Dismissible toast notifications for feed failures */}
      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-50 space-y-2">
          {toasts.map((toast) => (
            <div
              key={toast.run_id}
              className="flex items-start gap-3 rounded-lg border border-red-200 bg-white px-4 py-3 shadow-lg"
            >
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-900">Feed拉取失败</p>
                <p className="mt-0.5 text-xs text-slate-600">
                  {toast.source} 拉取失败: {toast.error_message}
                </p>
              </div>
              <button
                onClick={() => dismissToast(toast.run_id)}
                className="shrink-0 text-slate-400 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ThreatIntelLayout;
