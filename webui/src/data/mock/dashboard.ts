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

// ─── ECharts: Risk Trend (7 / 30 / 90 day) ───────────────────────────────────

export interface TrendPoint {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export const riskTrend7: TrendPoint[] = [
  { date: "05-03", critical: 2, high: 8, medium: 14, low: 22 },
  { date: "05-04", critical: 3, high: 10, medium: 12, low: 20 },
  { date: "05-05", critical: 1, high: 7, medium: 16, low: 25 },
  { date: "05-06", critical: 4, high: 12, medium: 11, low: 19 },
  { date: "05-07", critical: 2, high: 9, medium: 15, low: 23 },
  { date: "05-08", critical: 5, high: 14, medium: 13, low: 21 },
  { date: "05-09", critical: 3, high: 11, medium: 17, low: 24 },
];

export const riskTrend30: TrendPoint[] = [
  { date: "4/10", critical: 5, high: 8, medium: 35, low: 120 },
  { date: "4/11", critical: 8, high: 12, medium: 42, low: 135 },
  { date: "4/12", critical: 6, high: 10, medium: 38, low: 128 },
  { date: "4/13", critical: 9, high: 14, medium: 45, low: 142 },
  { date: "4/14", critical: 11, high: 16, medium: 52, low: 158 },
  { date: "4/15", critical: 7, high: 13, medium: 48, low: 148 },
  { date: "4/16", critical: 10, high: 15, medium: 55, low: 165 },
  { date: "4/17", critical: 12, high: 18, medium: 62, low: 178 },
  { date: "4/18", critical: 9, high: 14, medium: 58, low: 168 },
  { date: "4/19", critical: 8, high: 13, medium: 54, low: 160 },
  { date: "4/20", critical: 11, high: 17, medium: 68, low: 185 },
  { date: "4/21", critical: 13, high: 20, medium: 72, low: 195 },
  { date: "4/22", critical: 10, high: 16, medium: 65, low: 180 },
  { date: "4/23", critical: 9, high: 15, medium: 60, low: 172 },
  { date: "4/24", critical: 12, high: 19, medium: 75, low: 205 },
  { date: "4/25", critical: 14, high: 22, medium: 82, low: 220 },
  { date: "4/26", critical: 11, high: 18, medium: 78, low: 210 },
  { date: "4/27", critical: 10, high: 17, medium: 72, low: 200 },
  { date: "4/28", critical: 13, high: 21, medium: 85, low: 225 },
  { date: "4/29", critical: 15, high: 24, medium: 88, low: 240 },
  { date: "4/30", critical: 12, high: 20, medium: 82, low: 225 },
  { date: "5/1", critical: 11, high: 19, medium: 78, low: 215 },
  { date: "5/2", critical: 14, high: 23, medium: 90, low: 245 },
  { date: "5/3", critical: 16, high: 26, medium: 95, low: 260 },
  { date: "5/4", critical: 13, high: 22, medium: 88, low: 240 },
  { date: "5/5", critical: 12, high: 21, medium: 85, low: 232 },
  { date: "5/6", critical: 15, high: 25, medium: 92, low: 258 },
  { date: "5/7", critical: 17, high: 28, medium: 98, low: 272 },
  { date: "5/8", critical: 14, high: 24, medium: 90, low: 250 },
  { date: "5/9", critical: 14, high: 24, medium: 87, low: 245 },
];

export const riskTrend90: TrendPoint[] = [
  ...riskTrend30,
  ...riskTrend30.map((d, i) => ({
    ...d,
    date: `2/${i + 10}`,
    critical: Math.max(1, d.critical - ((i * 3) % 5)),
    high: Math.max(3, d.high - ((i * 5) % 8)),
    medium: Math.max(10, d.medium - ((i * 7) % 15)),
    low: Math.max(30, d.low - ((i * 11) % 40)),
  })),
  ...riskTrend30.map((d, i) => ({
    ...d,
    date: `3/${i + 10}`,
    critical: Math.max(1, d.critical - ((i * 2) % 3)),
    high: Math.max(3, d.high - ((i * 3) % 6)),
    medium: Math.max(10, d.medium - ((i * 5) % 10)),
    low: Math.max(30, d.low - ((i * 7) % 30)),
  })),
];

// ─── ECharts: Vulnerability Type Distribution (pie) ──────────────────────────

export interface VulnSlice {
  name: string;
  value: number;
}

export const vulnDistribution: VulnSlice[] = [
  { name: "注入", value: 34 },
  { name: "认证缺陷", value: 28 },
  { name: "XSS", value: 22 },
  { name: "配置错误", value: 14 },
  { name: "敏感数据暴露", value: 9 },
  { name: "其他", value: 6 },
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

// ─── ECharts: Asset Cluster (stacked bar) ────────────────────────────────────

export interface AssetClusterItem {
  name: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export const assetCluster: AssetClusterItem[] = [
  { name: "CRM", critical: 3, high: 5, medium: 12, low: 35 },
  { name: "ERP", critical: 2, high: 4, medium: 8, low: 28 },
  { name: "官网", critical: 5, high: 8, medium: 15, low: 42 },
  { name: "OA", critical: 1, high: 3, medium: 10, low: 30 },
  { name: "支付", critical: 4, high: 7, medium: 18, low: 38 },
  { name: "大数据", critical: 2, high: 5, medium: 14, low: 32 },
  { name: "BI", critical: 1, high: 2, medium: 9, low: 25 },
  { name: "内部工具", critical: 2, high: 4, medium: 11, low: 29 },
];

// ─── Recent Reports (table) ──────────────────────────────────────────────────

export type ReportStatus = "已发布" | "待审核" | "编辑中";

export interface ReportItem {
  id: string;
  title: string;
  type: string;
  highCount: number;
  status: ReportStatus;
  severity: "critical" | "high" | "medium" | "low";
  timestamp: string;
  target: string;
}

export const recentReports: ReportItem[] = [
  {
    id: "RPT-2026-0509-014",
    title: "DC-IDC-A 段月报",
    type: "合规月报",
    highCount: 7,
    status: "已发布",
    severity: "critical",
    timestamp: "2026-05-09",
    target: "DC-IDC-A",
  },
  {
    id: "RPT-2026-0509-013",
    title: "CVE-2024-3094 影响清单",
    type: "CVE 排查",
    highCount: 3,
    status: "待审核",
    severity: "high",
    timestamp: "2026-05-09",
    target: "全局",
  },
  {
    id: "RPT-2026-0508-028",
    title: "弱口令巡检 Q2-W19",
    type: "周巡检",
    highCount: 0,
    status: "已发布",
    severity: "medium",
    timestamp: "2026-05-08",
    target: "内网",
  },
  {
    id: "RPT-2026-0508-027",
    title: "研发内网端口暴露",
    type: "资产探测",
    highCount: 2,
    status: "编辑中",
    severity: "high",
    timestamp: "2026-05-08",
    target: "研发网",
  },
  {
    id: "RPT-2026-0507-015",
    title: "公网资产渗透测试",
    type: "渗透报告",
    highCount: 5,
    status: "已发布",
    severity: "critical",
    timestamp: "2026-05-07",
    target: "公网",
  },
];
