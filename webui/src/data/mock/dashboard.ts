/**
 * Mock data for DashboardPage (PR5 / R4.3).
 *
 * All numbers are deterministic (no Math.random) so tests and screenshots
 * stay stable across renders. When the real backend lands, these exports
 * will be swapped for hook-driven fetches against /api/dashboard/*.
 */

// ─── KPI Cards ────────────────────────────────────────────────────────────────

export interface KpiItem {
  label: string;
  value: number | string;
  /** Lucide icon name hint — consumer maps to component. */
  icon: string;
  /** Semantic color key (maps to Tailwind). */
  color: "ocean" | "emerald" | "amber" | "rose" | "violet" | "slate";
  /** Optional delta vs last period. Positive = up. */
  delta?: number;
}

export const kpiCards: KpiItem[] = [
  { label: "活跃任务", value: 12, icon: "Activity", color: "ocean", delta: 3 },
  { label: "已完成扫描", value: 847, icon: "CheckCircle2", color: "emerald", delta: 24 },
  { label: "高危漏洞", value: 36, icon: "ShieldAlert", color: "rose", delta: -5 },
  { label: "资产总量", value: "1,204", icon: "Server", color: "violet", delta: 18 },
  { label: "待处理告警", value: 9, icon: "AlertTriangle", color: "amber", delta: 2 },
  { label: "智能体在线", value: 5, icon: "Bot", color: "slate", delta: 0 },
];

// ─── ECharts: Risk Trend (7-day) ──────────────────────────────────────────────

export interface TrendPoint {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export const riskTrend: TrendPoint[] = [
  { date: "05-03", critical: 2, high: 8, medium: 14, low: 22 },
  { date: "05-04", critical: 3, high: 10, medium: 12, low: 20 },
  { date: "05-05", critical: 1, high: 7, medium: 16, low: 25 },
  { date: "05-06", critical: 4, high: 12, medium: 11, low: 19 },
  { date: "05-07", critical: 2, high: 9, medium: 15, low: 23 },
  { date: "05-08", critical: 5, high: 14, medium: 13, low: 21 },
  { date: "05-09", critical: 3, high: 11, medium: 17, low: 24 },
];

// ─── ECharts: Asset Distribution (pie) ───────────────────────────────────────

export interface AssetSlice {
  name: string;
  value: number;
}

export const assetDistribution: AssetSlice[] = [
  { name: "Web 应用", value: 342 },
  { name: "API 端点", value: 289 },
  { name: "数据库", value: 156 },
  { name: "服务器", value: 231 },
  { name: "网络设备", value: 98 },
  { name: "其他", value: 88 },
];

// ─── Recent Reports ──────────────────────────────────────────────────────────

export interface ReportItem {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  timestamp: string;
  target: string;
}

export const recentReports: ReportItem[] = [
  {
    id: "rpt-001",
    title: "生产 CRM SQL 注入",
    severity: "critical",
    timestamp: "2026-05-09 14:32",
    target: "crm.internal.corp",
  },
  {
    id: "rpt-002",
    title: "CDN 配置泄露敏感路径",
    severity: "high",
    timestamp: "2026-05-09 11:18",
    target: "cdn.example.com",
  },
  {
    id: "rpt-003",
    title: "Jenkins 未鉴权接口暴露",
    severity: "high",
    timestamp: "2026-05-08 22:45",
    target: "ci.internal.corp:8080",
  },
  {
    id: "rpt-004",
    title: "Redis 弱口令",
    severity: "medium",
    timestamp: "2026-05-08 19:10",
    target: "10.0.3.21:6379",
  },
  {
    id: "rpt-005",
    title: "SSL 证书即将过期",
    severity: "low",
    timestamp: "2026-05-08 16:55",
    target: "*.example.com",
  },
];
