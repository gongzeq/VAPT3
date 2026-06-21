/**
 * Threat Intel Overview Page — PRD §7.2 概览页.
 *
 * Displays 5 situation cards + data freshness bar.
 * Each card drills down to the corresponding list page.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Bug,
  Radar,
  Server,
  Ship,
  Shield,
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Clock,
  AlertCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchOverview, type OverviewData } from "@/lib/threat-intel-client";
import { cn } from "@/lib/utils";

export function OverviewPage() {
  const { token } = useClient();
  const navigate = useNavigate();
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const overview = await fetchOverview(token);
        if (!cancelled) setData(overview);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Activity className="h-4 w-4 animate-pulse" />
          加载威胁情报数据…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-red-600">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      </div>
    );
  }

  if (!data) return null;

  // ── Freshness bar ───────────────────────────────────────────────────
  const freshness = data.freshness;
  const hasIssues = freshness.failed_sources.length > 0 || freshness.stale_sources.length > 0;

  return (
    <div className="space-y-6">
      {/* Freshness bar */}
      <div
        className={cn(
          "flex items-center gap-3 rounded-xl border px-4 py-3 text-sm",
          hasIssues
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-emerald-200 bg-emerald-50 text-emerald-800",
        )}
      >
        <Clock className="h-4 w-4 shrink-0" />
        <span>
          {freshness.last_success_at
            ? `最近数据更新: ${new Date(freshness.last_success_at).toLocaleString("zh-CN")}`
            : "尚无数据"}
        </span>
        {freshness.failed_sources.length > 0 && (
          <span className="flex items-center gap-1 text-red-600">
            <AlertCircle className="h-3 w-3" />
            失败: {freshness.failed_sources.join(", ")}
          </span>
        )}
        {freshness.stale_sources.length > 0 && (
          <span className="text-amber-600">
            过期: {freshness.stale_sources.join(", ")}
          </span>
        )}
      </div>

      {/* 5 Situation Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* Card 1: Watched Groups Activity */}
        <OverviewCard
          title="关注组织动态"
          icon={<Shield className="h-5 w-5" />}
          accent="indigo"
          onClick={() => navigate("/threat-intel/groups?watched=true")}
        >
          <div className="space-y-1">
            <div className="text-2xl font-bold text-slate-900">
              {data.watched_groups_activity.total_watched}
              <span className="ml-1 text-sm font-normal text-slate-500">个组织</span>
            </div>
            <div className="text-sm text-slate-600">
              近7天 {data.watched_groups_activity.recent_activity_count} 个组织有新活动
            </div>
            {data.watched_groups_activity.activities.length > 0 && (
              <div className="mt-2 space-y-1">
                {data.watched_groups_activity.activities.slice(0, 3).map((a, i) => (
                  <div key={i} className="flex items-center justify-between text-xs text-slate-500">
                    <span>{a.group_name}</span>
                    <span className="font-medium text-indigo-600">
                      {a.count} 个新{a.activity_type === "new_c2_ip" ? "C2" : a.activity_type === "new_malware" ? "木马" : "漏洞"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </OverviewCard>

        {/* Card 2: High Severity Vulns */}
        <OverviewCard
          title="高危漏洞速览"
          icon={<AlertTriangle className="h-5 w-5" />}
          accent="red"
          onClick={() => navigate("/threat-intel/vulns")}
        >
          <div className="space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-slate-900">
                {data.high_severity_vulns.total}
              </span>
              <span className="text-sm text-slate-500">总数</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-600">近7天 +{data.high_severity_vulns.new_last_7d}</span>
              <TrendIcon trend={data.high_severity_vulns.trend} />
            </div>
            {data.high_severity_vulns.supply_chain_count > 0 && (
              <div className="text-xs text-amber-600">
                供应链相关: {data.high_severity_vulns.supply_chain_count}
              </div>
            )}
          </div>
        </OverviewCard>

        {/* Card 3: Active C2 IPs */}
        <OverviewCard
          title="活跃C2统计"
          icon={<Server className="h-5 w-5" />}
          accent="orange"
          onClick={() => navigate("/threat-intel/ips")}
        >
          <div className="space-y-1">
            <div className="text-2xl font-bold text-slate-900">
              {data.active_c2_ips.total}
              <span className="ml-1 text-sm font-normal text-slate-500">个活跃C2</span>
            </div>
            {data.active_c2_ips.by_group.length > 0 && (
              <div className="mt-2 space-y-1">
                {data.active_c2_ips.by_group.map((g, i) => (
                  <div key={i} className="flex items-center justify-between text-xs text-slate-500">
                    <span>{g.group_name}</span>
                    <span className="font-medium text-orange-600">{g.count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </OverviewCard>

        {/* Card 4: Maritime Events */}
        <OverviewCard
          title="海事安全事件"
          icon={<Ship className="h-5 w-5" />}
          accent="blue"
          onClick={() => navigate("/threat-intel/maritime")}
        >
          <div className="space-y-1">
            <div className="text-2xl font-bold text-slate-900">
              {data.maritime_events.total}
              <span className="ml-1 text-sm font-normal text-slate-500">个事件</span>
            </div>
            <div className="text-sm text-slate-600">
              近7天 {data.maritime_events.recent_count} 个新事件
            </div>
            {data.maritime_events.latest && (
              <div className="mt-2 rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-600">
                {data.maritime_events.latest.title}
              </div>
            )}
          </div>
        </OverviewCard>

        {/* Card 5: Malware Activity */}
        <OverviewCard
          title="木马家族活跃"
          icon={<Bug className="h-5 w-5" />}
          accent="rose"
          onClick={() => navigate("/threat-intel/malware")}
        >
          <div className="space-y-1">
            <div className="text-2xl font-bold text-slate-900">
              {data.malware_activity.total_families}
              <span className="ml-1 text-sm font-normal text-slate-500">个家族</span>
            </div>
            {data.malware_activity.top_families.length > 0 && (
              <div className="mt-2 space-y-1">
                {data.malware_activity.top_families.slice(0, 3).map((f, i) => (
                  <div key={i} className="flex items-center justify-between text-xs text-slate-500">
                    <span>{f.family}</span>
                    <span className="font-medium text-rose-600">{f.group}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </OverviewCard>

        {/* Card 6: Radar (placeholder for P1 graph) */}
        <OverviewCard
          title="威胁雷达"
          icon={<Radar className="h-5 w-5" />}
          accent="violet"
          onClick={() => navigate("/threat-intel/groups")}
        >
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            知识图谱 (P1)
          </div>
        </OverviewCard>
      </div>
    </div>
  );
}

// ── Card Component ─────────────────────────────────────────────────────

const ACCENT_MAP: Record<string, string> = {
  indigo: "border-indigo-200 bg-white hover:border-indigo-300 hover:shadow-md",
  red: "border-red-200 bg-white hover:border-red-300 hover:shadow-md",
  orange: "border-orange-200 bg-white hover:border-orange-300 hover:shadow-md",
  blue: "border-blue-200 bg-white hover:border-blue-300 hover:shadow-md",
  rose: "border-rose-200 bg-white hover:border-rose-300 hover:shadow-md",
  violet: "border-violet-200 bg-white hover:border-violet-300 hover:shadow-md",
};

const ICON_ACCENT: Record<string, string> = {
  indigo: "bg-indigo-50 text-indigo-600",
  red: "bg-red-50 text-red-600",
  orange: "bg-orange-50 text-orange-600",
  blue: "bg-blue-50 text-blue-600",
  rose: "bg-rose-50 text-rose-600",
  violet: "bg-violet-50 text-violet-600",
};

interface OverviewCardProps {
  title: string;
  icon: React.ReactNode;
  accent: string;
  onClick: () => void;
  children: React.ReactNode;
}

function OverviewCard({ title, icon, accent, onClick, children }: OverviewCardProps) {
  return (
    <div
      className={cn(
        "cursor-pointer rounded-xl border p-4 transition-all duration-200",
        ACCENT_MAP[accent] || ACCENT_MAP.indigo,
      )}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter") onClick(); }}
    >
      <div className="mb-3 flex items-center gap-2">
        <div className={cn("flex h-8 w-8 items-center justify-center rounded-lg", ICON_ACCENT[accent] || ICON_ACCENT.indigo)}>
          {icon}
        </div>
        <h3 className="text-sm font-medium text-slate-700">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "up") return <TrendingUp className="h-4 w-4 text-red-500" />;
  if (trend === "down") return <TrendingDown className="h-4 w-4 text-emerald-500" />;
  return <Minus className="h-4 w-4 text-slate-400" />;
}

export default OverviewPage;
