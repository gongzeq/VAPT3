/**
 * Frontend mock data for the `/sessions` history page.
 *
 * Backend `/api/sessions` and `/api/reports` are not yet implemented (see
 * `webui/src/gap/dashboard-data.md`). The hooks at
 * `webui/src/hooks/useSessionsList.ts` and `webui/src/hooks/useReports.ts`
 * fall back to these constants until those endpoints land — at which point
 * the hooks just need to swap their data source.
 */
import type { ReportRow, SessionRow } from "@/lib/types";

const HOUR = 60 * 60 * 1000;
const MINUTE = 60 * 1000;
const NOW = Date.now();

const iso = (offsetMs: number) => new Date(NOW - offsetMs).toISOString();

/** Build a structured mock report. */
function makeReport(
  sessionKey: string,
  id: string,
  title: string,
  format: "html" | "pdf",
  ageMs: number,
  sizeBytes: number,
): ReportRow {
  return {
    id,
    sessionKey,
    title,
    format,
    url: `/api/reports/${id}.${format}`,
    sizeBytes,
    createdAt: iso(ageMs),
  };
}

/** Source-of-truth mock sessions covering all status / scanType combos. */
export const MOCK_SESSIONS: SessionRow[] = [
  {
    key: "websocket:7f3a-finished-full",
    channel: "websocket",
    chatId: "7f3a8b21",
    createdAt: iso(3 * HOUR),
    updatedAt: iso(2 * HOUR),
    title: "全量扫描 · 192.168.1.10:8080",
    preview: "全量扫描已完成，发现 3 项高危漏洞与 1 项弱口令",
    target: "192.168.1.10:8080",
    scanType: "full",
    status: "finished",
    findings: { critical: 1, high: 3, medium: 5, low: 8, total: 17 },
    tokens: { input: 12_300, output: 4_500, cached: 8_200 },
    durationMs: 58 * MINUTE,
    reports: [
      makeReport(
        "websocket:7f3a-finished-full",
        "rpt-7f3a-html",
        "全量扫描报告",
        "html",
        2 * HOUR,
        324_000,
      ),
      makeReport(
        "websocket:7f3a-finished-full",
        "rpt-7f3a-pdf",
        "全量扫描报告 (PDF)",
        "pdf",
        2 * HOUR - 5 * MINUTE,
        612_000,
      ),
    ],
  },
  {
    key: "websocket:b912-running-vuln",
    channel: "websocket",
    chatId: "b9120c44",
    createdAt: iso(45 * MINUTE),
    updatedAt: iso(2 * MINUTE),
    title: "漏洞扫描 · https://shop.example.com",
    preview: "正在执行 OWASP Top 10 漏洞扫描…",
    target: "https://shop.example.com",
    scanType: "vuln",
    status: "running",
    findings: { critical: 0, high: 1, medium: 2, low: 1, total: 4 },
    tokens: { input: 4_200, output: 1_800, cached: 1_100 },
    durationMs: null,
    reports: [],
  },
  {
    key: "websocket:c441-finished-asset",
    channel: "websocket",
    chatId: "c4419f87",
    createdAt: iso(28 * HOUR),
    updatedAt: iso(27 * HOUR),
    title: "资产探测 · 10.0.0.0/24",
    preview: "扫描发现 42 台存活主机已写入 CMDB",
    target: "10.0.0.0/24",
    scanType: "asset",
    status: "finished",
    findings: { critical: 0, high: 0, medium: 0, low: 0, total: 0 },
    tokens: { input: 8_700, output: 2_100, cached: 5_900 },
    durationMs: 22 * MINUTE,
    reports: [
      makeReport(
        "websocket:c441-finished-asset",
        "rpt-c441-html",
        "资产清单报告",
        "html",
        27 * HOUR,
        128_000,
      ),
    ],
  },
  {
    key: "websocket:e09c-failed-weakpwd",
    channel: "websocket",
    chatId: "e09c7d12",
    createdAt: iso(50 * HOUR),
    updatedAt: iso(49 * HOUR),
    title: "弱口令检测 · 172.16.5.20",
    preview: "目标不可达，扫描失败",
    target: "172.16.5.20",
    scanType: "weakpwd",
    status: "failed",
    findings: { critical: 0, high: 0, medium: 0, low: 0, total: 0 },
    tokens: { input: 1_200, output: 400, cached: 0 },
    durationMs: 4 * MINUTE,
    reports: [],
  },
  {
    key: "websocket:1234-stopped-full",
    channel: "websocket",
    chatId: "12345abc",
    createdAt: iso(75 * HOUR),
    updatedAt: iso(74 * HOUR),
    title: "全量扫描 · api.hnscbyhz.com",
    preview: "用户主动停止扫描",
    target: "api.hnscbyhz.com",
    scanType: "full",
    status: "stopped",
    findings: { critical: 0, high: 1, medium: 0, low: 2, total: 3 },
    tokens: { input: 6_400, output: 1_200, cached: 3_200 },
    durationMs: 18 * MINUTE,
    reports: [
      makeReport(
        "websocket:1234-stopped-full",
        "rpt-1234-html",
        "部分结果报告",
        "html",
        74 * HOUR,
        96_000,
      ),
    ],
  },
  {
    key: "websocket:8aa2-finished-vuln",
    channel: "websocket",
    chatId: "8aa28ee0",
    createdAt: iso(96 * HOUR),
    updatedAt: iso(95 * HOUR),
    title: "漏洞扫描 · http://120.76.218.180:9313",
    preview: "发现 5 项漏洞，含 1 项关键 RCE",
    target: "http://120.76.218.180:9313",
    scanType: "vuln",
    status: "finished",
    findings: { critical: 1, high: 2, medium: 1, low: 1, total: 5 },
    tokens: { input: 38_900, output: 12_400, cached: 24_100 },
    durationMs: 1 * HOUR + 12 * MINUTE,
    reports: [
      makeReport(
        "websocket:8aa2-finished-vuln",
        "rpt-8aa2-html",
        "漏洞扫描报告",
        "html",
        95 * HOUR,
        287_000,
      ),
      makeReport(
        "websocket:8aa2-finished-vuln",
        "rpt-8aa2-pdf",
        "漏洞扫描报告 (PDF)",
        "pdf",
        95 * HOUR,
        541_000,
      ),
    ],
  },
  {
    key: "websocket:5d7f-finished-weakpwd",
    channel: "websocket",
    chatId: "5d7f6a12",
    createdAt: iso(120 * HOUR),
    updatedAt: iso(119 * HOUR),
    title: "弱口令检测 · 36.133.100.186",
    preview: "发现 SSH 弱口令账户 admin/admin",
    target: "36.133.100.186",
    scanType: "weakpwd",
    status: "finished",
    findings: { critical: 0, high: 2, medium: 0, low: 0, total: 2 },
    tokens: { input: 5_200, output: 900, cached: 2_700 },
    durationMs: 26 * MINUTE,
    reports: [
      makeReport(
        "websocket:5d7f-finished-weakpwd",
        "rpt-5d7f-html",
        "弱口令检测报告",
        "html",
        119 * HOUR,
        88_000,
      ),
    ],
  },
  {
    key: "websocket:99aa-finished-asset",
    channel: "websocket",
    chatId: "99aabbcc",
    createdAt: iso(168 * HOUR),
    updatedAt: iso(167 * HOUR),
    title: "资产探测 · 117.174.155.199",
    preview: "扫描完成，发现 12 项暴露端口",
    target: "117.174.155.199",
    scanType: "asset",
    status: "finished",
    findings: { critical: 0, high: 0, medium: 1, low: 4, total: 5 },
    tokens: { input: 3_800, output: 600, cached: 1_900 },
    durationMs: 9 * MINUTE,
    reports: [
      makeReport(
        "websocket:99aa-finished-asset",
        "rpt-99aa-html",
        "资产清单",
        "html",
        167 * HOUR,
        64_000,
      ),
    ],
  },
  {
    key: "websocket:q001-finished-query",
    channel: "websocket",
    chatId: "q001sec1",
    createdAt: iso(6 * HOUR),
    updatedAt: iso(5 * HOUR),
    title: "安全法规查询 · 等保2.0三级要求",
    preview: "为用户整理了等保2.0三级的核心要求与合规检查清单",
    target: null,
    scanType: "query",
    status: "finished",
    findings: { critical: 0, high: 0, medium: 0, low: 0, total: 0 },
    tokens: { input: 6_800, output: 3_200, cached: 4_100 },
    durationMs: 12 * MINUTE,
    reports: [],
  },
  {
    key: "websocket:q002-finished-query",
    channel: "websocket",
    chatId: "q002sec2",
    createdAt: iso(52 * HOUR),
    updatedAt: iso(51 * HOUR),
    title: "漏洞分析咨询 · Log4Shell (CVE-2021-44228)",
    preview: "详细分析了 Log4Shell 漏洞的攻击原理、影响范围及修复方案",
    target: null,
    scanType: "query",
    status: "finished",
    findings: { critical: 0, high: 0, medium: 0, low: 0, total: 0 },
    tokens: { input: 9_400, output: 5_600, cached: 6_200 },
    durationMs: 18 * MINUTE,
    reports: [
      makeReport(
        "websocket:q002-finished-query",
        "rpt-q002-html",
        "Log4Shell 漏洞分析报告",
        "html",
        51 * HOUR,
        156_000,
      ),
    ],
  },
];

/** Convenience: aggregate every report across all sessions. */
export const MOCK_REPORTS: ReportRow[] = MOCK_SESSIONS.flatMap(
  (session) => session.reports,
);
