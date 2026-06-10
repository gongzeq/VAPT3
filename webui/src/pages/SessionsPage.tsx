import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  Bug,
  CheckCircle2,
  CheckSquare,
  Crosshair,
  Download,
  History,
  Inbox,
  Key,
  Loader2,
  Play,
  Radar,
  Search,
  ShieldAlert,
  Square,
  Trash2,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSessionsList } from "@/hooks/useSessionsList";
import { useClient } from "@/providers/ClientProvider";
import { deleteSession } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  ReportRow,
  ScanType,
  SessionRow,
  SessionStatus,
} from "@/lib/types";

type StatusFilter = "all" | SessionStatus;
type ScanTypeFilter = "all" | ScanType;
type RangeFilter = "1d" | "7d" | "30d" | "all";

const STATUS_META: Record<
  SessionStatus,
  { labelKey: string; fallback: string; icon: LucideIcon; tone: string }
> = {
  running: {
    labelKey: "sessions.status.running",
    fallback: "进行中",
    icon: Loader2,
    tone: "border-primary/30 bg-primary/10 text-primary",
  },
  finished: {
    labelKey: "sessions.status.finished",
    fallback: "已完成",
    icon: CheckCircle2,
    tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500 dark:text-emerald-400",
  },
  failed: {
    labelKey: "sessions.status.failed",
    fallback: "失败",
    icon: XCircle,
    tone: "border-destructive/30 bg-destructive/10 text-destructive",
  },
  stopped: {
    labelKey: "sessions.status.stopped",
    fallback: "已停止",
    icon: AlertCircle,
    tone: "border-muted-foreground/30 bg-muted/30 text-muted-foreground",
  },
};

const SCAN_TYPE_META: Record<
  ScanType,
  { labelKey: string; fallback: string; icon: LucideIcon }
> = {
  full: { labelKey: "home.scan.full.label", fallback: "全量扫描", icon: Crosshair },
  vuln: { labelKey: "home.scan.vuln.label", fallback: "漏洞扫描", icon: Bug },
  weakpwd: {
    labelKey: "home.scan.weakpwd.label",
    fallback: "弱口令检测",
    icon: Key,
  },
  asset: {
    labelKey: "home.scan.asset.label",
    fallback: "仅资产探测",
    icon: Radar,
  },
  query: {
    labelKey: "sessions.type.query",
    fallback: "安全咨询",
    icon: BookOpen,
  },
};

function formatDuration(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms) || ms <= 0) return "—";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rs = seconds % 60;
  if (minutes < 60) return rs ? `${minutes}m ${rs}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rm = minutes % 60;
  return rm ? `${hours}h ${rm}m` : `${hours}h`;
}

function ReportCell({ reports }: { reports: ReportRow[] }) {
  const { t } = useTranslation();
  if (reports.length === 0) {
    return (
      <span className="inline-flex h-8 w-full items-center justify-center gap-1 rounded-md border border-border/40 bg-muted/20 text-[11px] font-medium text-muted-foreground/60">
        <Download className="h-3 w-3 opacity-40" />
        {t("sessions.actions.noReportGenerated", { defaultValue: "未生成报告" })}
      </span>
    );
  }
  const report = reports[0];
  return (
    <a
      href={report.url}
      download
      className="inline-flex h-8 w-full items-center justify-center gap-1 rounded-md border border-primary/30 bg-primary/5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10"
    >
      <Download className="h-3 w-3" />
      {t("sessions.actions.downloadReport", { defaultValue: "下载报告" })}
    </a>
  );
}

function formatRelativeTime(
  iso: string | null,
  now: number,
  locale: string,
): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diffMs = t - now;
  const absMs = Math.abs(diffMs);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (absMs < minute) return rtf.format(Math.round(diffMs / 1000), "second");
  if (absMs < hour) return rtf.format(Math.round(diffMs / minute), "minute");
  if (absMs < day) return rtf.format(Math.round(diffMs / hour), "hour");
  if (absMs < 30 * day) return rtf.format(Math.round(diffMs / day), "day");
  return new Date(t).toLocaleDateString(locale);
}

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function StatusBadge({ status }: { status: SessionStatus }) {
  const { t } = useTranslation();
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        meta.tone,
      )}
    >
      <Icon
        className={cn(
          "h-3 w-3",
          status === "running" && "animate-spin",
        )}
      />
      {t(meta.labelKey, { defaultValue: meta.fallback })}
    </span>
  );
}

function ScanTypeChip({ scanType }: { scanType: ScanType | null }) {
  const { t } = useTranslation();
  if (!scanType) {
    return <span className="text-xs text-muted-foreground/60">—</span>;
  }
  const meta = SCAN_TYPE_META[scanType];
  const Icon = meta.icon;
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/30 px-2 py-0.5 text-[11px] text-muted-foreground">
      <Icon className="h-3 w-3 text-primary" />
      {t(meta.labelKey, { defaultValue: meta.fallback })}
    </span>
  );
}

function FindingsCell({ row }: { row: SessionRow }) {
  const { findings } = row;
  if (findings.total === 0) {
    return <span className="text-xs text-muted-foreground/60">—</span>;
  }
  return (
    <div className="flex items-center gap-1.5">
      {findings.critical > 0 && (
        <span className="inline-flex items-center gap-0.5 rounded bg-destructive/15 px-1.5 py-0.5 text-[11px] font-semibold text-destructive">
          <ShieldAlert className="h-3 w-3" /> {findings.critical}
        </span>
      )}
      {findings.high > 0 && (
        <span className="rounded bg-orange-500/15 px-1.5 py-0.5 text-[11px] font-semibold text-orange-500 dark:text-orange-400">
          H {findings.high}
        </span>
      )}
      {findings.medium > 0 && (
        <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-semibold text-amber-500 dark:text-amber-400">
          M {findings.medium}
        </span>
      )}
      {findings.low > 0 && (
        <span className="rounded bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground">
          L {findings.low}
        </span>
      )}
      <span className="text-[11px] text-muted-foreground/70">
        / {findings.total}
      </span>
    </div>
  );
}

function TokensCell({ row }: { row: SessionRow }) {
  const { tokens } = row;
  const totalIn = tokens.input;
  const cacheRate =
    totalIn > 0 ? Math.round((tokens.cached / totalIn) * 100) : 0;
  return (
    <div className="flex flex-col gap-0.5 text-[11px] text-muted-foreground tabular-nums">
      <span>
        ↓ <span className="text-foreground/90">{compactNumber(tokens.input)}</span>
        <span className="px-1 text-muted-foreground/50">·</span>
        ↑ <span className="text-foreground/90">{compactNumber(tokens.output)}</span>
      </span>
      <span className="text-muted-foreground/70">
        Cache {totalIn > 0 ? `${cacheRate}%` : "—"}
      </span>
    </div>
  );
}

function inRange(iso: string | null, range: RangeFilter): boolean {
  if (range === "all") return true;
  if (!iso) return false;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return true;
  const days = range === "1d" ? 1 : range === "7d" ? 7 : 30;
  return Date.now() - t <= days * 24 * 60 * 60 * 1000;
}

/**
 * `/sessions` — Structured history of every scan session and its
 * generated reports. Replaces the old left Sidebar list.
 */
export function SessionsPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { sessions, loading, refresh } = useSessionsList();
  const { token } = useClient();
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [scanFilter, setScanFilter] = useState<ScanTypeFilter>("all");
  const [rangeFilter, setRangeFilter] = useState<RangeFilter>("7d");
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [localSessions, setLocalSessions] = useState<SessionRow[] | null>(null);
  const now = Date.now();
  const locale = i18n.resolvedLanguage ?? "zh-CN";

  // Source of truth: once we delete locally we override; otherwise use hook data.
  const sessions_ = localSessions ?? sessions;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sessions_.filter((row) => {
      if (statusFilter !== "all" && row.status !== statusFilter) return false;
      if (scanFilter !== "all" && row.scanType !== scanFilter) return false;
      if (!inRange(row.createdAt, rangeFilter)) return false;
      if (!q) return true;
      const haystack = [row.title, row.target, row.chatId, row.preview]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [sessions_, query, statusFilter, scanFilter, rangeFilter]);

  const toggleSelect = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedKeys((prev) => {
      if (prev.size === filtered.length) return new Set();
      return new Set(filtered.map((r) => r.key));
    });
  };

  const handleDeleteSession = useCallback((key: string) => {
    // Optimistic: remove from UI immediately
    setLocalSessions((prev) =>
      (prev ?? sessions).filter((s) => s.key !== key),
    );
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
    // Persist: call backend API to actually delete the session file
    deleteSession(tokenRef.current, key).catch((err) => {
      console.error("Failed to delete session", key, err);
      // Rollback: refresh from server to restore the deleted session
      refresh();
      setLocalSessions(null);
    });
  }, [sessions, refresh]);

  const handleBatchDelete = useCallback(() => {
    if (selectedKeys.size === 0) return;
    const keys = [...selectedKeys];
    // Optimistic: remove from UI immediately
    setLocalSessions((prev) =>
      (prev ?? sessions).filter((s) => !selectedKeys.has(s.key)),
    );
    setSelectedKeys(new Set());
    // Persist: call backend API for each session
    Promise.all(keys.map((k) => deleteSession(tokenRef.current, k))).catch(
      (err) => {
        console.error("Batch delete failed", err);
        refresh();
        setLocalSessions(null);
      },
    );
  }, [selectedKeys, sessions, refresh]);

  const handleOpenSession = (key: string) => {
    navigate(`/session/${encodeURIComponent(key)}`);
  };

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <Navbar />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6 px-6 py-8">
          {/* Page header */}
          <header className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <History className="h-3.5 w-3.5" />
              {t("sessions.page.breadcrumb", { defaultValue: "导航 / 历史会话" })}
            </div>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                  {t("sessions.page.title", { defaultValue: "历史会话" })}
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t("sessions.page.subtitle", {
                    defaultValue: "全部会话的结构化记录与产出报告",
                  })}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => navigate("/")}
                  className="gap-1.5"
                >
                  <Play className="h-4 w-4" />
                  {t("sessions.page.newScan", { defaultValue: "发起新扫描" })}
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleBatchDelete}
                  disabled={selectedKeys.size === 0}
                  className="gap-1.5"
                >
                  <Trash2 className="h-4 w-4" />
                  {t("sessions.actions.batchDelete", { defaultValue: "批量删除" })}
                  {selectedKeys.size > 0 && (
                    <span className="ml-0.5 rounded bg-destructive-foreground/20 px-1.5 text-[10px] font-semibold">
                      {selectedKeys.size}
                    </span>
                  )}
                </Button>
              </div>
            </div>
          </header>

          {/* Filters */}
          <div className="flex flex-col gap-3 rounded-2xl border border-border/60 bg-card/40 p-3 sm:flex-row sm:flex-wrap sm:items-center">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("sessions.filter.searchPlaceholder", {
                  defaultValue: "搜索目标 / 会话 ID / 标题",
                })}
                className="h-9 pl-9"
              />
            </div>
            <Select
              value={statusFilter}
              onValueChange={(value) => setStatusFilter(value as StatusFilter)}
            >
              <SelectTrigger className="h-9 w-[140px]">
                <SelectValue
                  placeholder={t("sessions.filter.status", {
                    defaultValue: "状态",
                  })}
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t("sessions.filter.allStatuses", { defaultValue: "全部状态" })}
                </SelectItem>
                <SelectItem value="running">
                  {t("sessions.status.running", { defaultValue: "进行中" })}
                </SelectItem>
                <SelectItem value="finished">
                  {t("sessions.status.finished", { defaultValue: "已完成" })}
                </SelectItem>
                <SelectItem value="failed">
                  {t("sessions.status.failed", { defaultValue: "失败" })}
                </SelectItem>
                <SelectItem value="stopped">
                  {t("sessions.status.stopped", { defaultValue: "已停止" })}
                </SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={scanFilter}
              onValueChange={(value) => setScanFilter(value as ScanTypeFilter)}
            >
              <SelectTrigger className="h-9 w-[140px]">
                <SelectValue
                  placeholder={t("sessions.filter.sessionType", {
                    defaultValue: "会话类型",
                  })}
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t("sessions.filter.allScans", { defaultValue: "全部类型" })}
                </SelectItem>
                <SelectItem value="full">
                  {t("home.scan.full.label", { defaultValue: "全量扫描" })}
                </SelectItem>
                <SelectItem value="vuln">
                  {t("home.scan.vuln.label", { defaultValue: "漏洞扫描" })}
                </SelectItem>
                <SelectItem value="weakpwd">
                  {t("home.scan.weakpwd.label", { defaultValue: "弱口令检测" })}
                </SelectItem>
                <SelectItem value="asset">
                  {t("home.scan.asset.label", { defaultValue: "仅资产探测" })}
                </SelectItem>
                <SelectItem value="query">
                  {t("sessions.type.query", { defaultValue: "安全咨询" })}
                </SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={rangeFilter}
              onValueChange={(value) => setRangeFilter(value as RangeFilter)}
            >
              <SelectTrigger className="h-9 w-[140px]">
                <SelectValue
                  placeholder={t("sessions.filter.range", {
                    defaultValue: "时间范围",
                  })}
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1d">
                  {t("sessions.filter.range1d", { defaultValue: "近 1 天" })}
                </SelectItem>
                <SelectItem value="7d">
                  {t("sessions.filter.range7d", { defaultValue: "近 7 天" })}
                </SelectItem>
                <SelectItem value="30d">
                  {t("sessions.filter.range30d", { defaultValue: "近 30 天" })}
                </SelectItem>
                <SelectItem value="all">
                  {t("sessions.filter.rangeAll", { defaultValue: "全部时间" })}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-2xl border border-border/60 bg-card/30">
            {/* Header row */}
            <div className="hidden grid-cols-[40px_minmax(0,3fr)_120px_120px_minmax(0,2fr)_130px_100px_90px_90px_36px] items-center gap-3 border-b border-border/60 bg-muted/20 px-4 py-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground md:grid">
              <button
                type="button"
                onClick={toggleSelectAll}
                disabled={filtered.length === 0}
                className="flex items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-40"
                aria-label={t("sessions.actions.selectAll", { defaultValue: "全选" })}
              >
                {filtered.length > 0 && selectedKeys.size === filtered.length ? (
                  <CheckSquare className="h-4 w-4 text-primary" />
                ) : (
                  <Square className="h-4 w-4" />
                )}
              </button>
              <span>{t("sessions.column.session", { defaultValue: "会话 / 目标" })}</span>
              <span>{t("sessions.column.status", { defaultValue: "状态" })}</span>
              <span>{t("sessions.column.sessionType", { defaultValue: "会话类型" })}</span>
              <span>{t("sessions.column.findings", { defaultValue: "发现" })}</span>
              <span>{t("sessions.column.tokens", { defaultValue: "Tokens" })}</span>
              <span>{t("sessions.column.duration", { defaultValue: "耗时" })}</span>
              <span />
              <span />
              <span />
            </div>

            {/* Rows */}
            {loading ? (
              <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("sessions.loading", { defaultValue: "正在加载历史会话…" })}
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
                <div className="rounded-full bg-muted/40 p-4 text-muted-foreground">
                  <Inbox className="h-8 w-8" />
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {t("sessions.empty.title", {
                      defaultValue: "暂无会话记录",
                    })}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("sessions.empty.subtitle", {
                      defaultValue: "调整筛选条件或返回主页发起一次新扫描",
                    })}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => navigate("/")}
                  className="gap-1.5"
                >
                  <Play className="h-3.5 w-3.5" />
                  {t("sessions.empty.cta", { defaultValue: "发起新扫描" })}
                </Button>
              </div>
            ) : (
              <ul className="divide-y divide-border/40">
                {filtered.map((row) => (
                  <li
                    key={row.key}
                    className={cn(
                      "grid grid-cols-1 gap-3 px-4 py-4 transition-colors hover:bg-muted/20",
                      "md:grid-cols-[40px_minmax(0,3fr)_120px_120px_minmax(0,2fr)_130px_100px_90px_90px_36px] md:items-center",
                      selectedKeys.has(row.key) && "bg-primary/5",
                    )}
                  >
                    {/* checkbox */}
                    <button
                      type="button"
                      onClick={() => toggleSelect(row.key)}
                      className="flex items-center justify-center text-muted-foreground hover:text-foreground"
                      aria-label={t("sessions.actions.selectSession", { defaultValue: "选择此会话" })}
                    >
                      {selectedKeys.has(row.key) ? (
                        <CheckSquare className="h-4 w-4 text-primary" />
                      ) : (
                        <Square className="h-4 w-4" />
                      )}
                    </button>
                    {/* session / target */}
                    <div className="min-w-0">
                      <button
                        type="button"
                        onClick={() => handleOpenSession(row.key)}
                        className="block w-full truncate text-left text-sm font-medium text-foreground hover:text-primary"
                      >
                        {row.title || row.target || row.preview || t("chat.fallbackTitle", { id: row.chatId.slice(0, 6) })}
                      </button>
                      <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                        {row.target ? (
                          <>
                            <span className="truncate font-mono">
                              {row.target}
                            </span>
                            <span aria-hidden>·</span>
                          </>
                        ) : row.preview && (row.title || row.preview) !== row.preview ? (
                          <>
                            <span className="truncate">
                              {row.preview}
                            </span>
                            <span aria-hidden>·</span>
                          </>
                        ) : null}
                        <span>
                          {formatRelativeTime(row.createdAt, now, locale)}
                        </span>
                      </div>
                    </div>
                    <div className="md:hidden">
                      <span className="text-[10px] uppercase text-muted-foreground/70">
                        {t("sessions.column.status", { defaultValue: "状态" })}
                      </span>
                    </div>
                    <StatusBadge status={row.status} />
                    <ScanTypeChip scanType={row.scanType} />
                    <FindingsCell row={row} />
                    <TokensCell row={row} />
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {formatDuration(row.durationMs)}
                    </span>
                    {/* Action column 1: Open */}
                    <div className="flex items-center">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 w-full px-2.5 text-xs"
                        onClick={() => handleOpenSession(row.key)}
                      >
                        <ArrowUpRight className="mr-1 h-3.5 w-3.5" />
                        {t("sessions.actions.openSession", {
                          defaultValue: "打开",
                        })}
                      </Button>
                    </div>
                    {/* Action column 2: Report */}
                    <div className="flex items-center">
                      <ReportCell reports={row.reports} />
                    </div>
                    {/* Action column 3: Delete */}
                    <div className="flex items-center justify-center">
                      <button
                        type="button"
                        onClick={() => handleDeleteSession(row.key)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-destructive/10 hover:text-destructive"
                        aria-label={t("sessions.actions.deleteSession", { defaultValue: "删除会话" })}
                        title={t("sessions.actions.deleteSession", { defaultValue: "删除会话" })}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default SessionsPage;
