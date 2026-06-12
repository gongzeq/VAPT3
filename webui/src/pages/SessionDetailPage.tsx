import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Brain,
  Bug,
  CheckCircle2,
  Clock,
  Cpu,
  Crosshair,
  Download,
  ExternalLink,
  FileText,
  History,
  Key,
  Layers,
  Loader2,
  MessageSquare,
  Play,
  Radar,
  ShieldAlert,
  StopCircle,
  Trash2,
  Wrench,
  XCircle,
  AlertCircle,
  Inbox,
  type LucideIcon,
} from "lucide-react";

import { Navbar } from "@/components/Navbar";
import { MessageBubble } from "@/components/MessageBubble";
import { Button } from "@/components/ui/button";
import { useSessionsList } from "@/hooks/useSessionsList";
import { useSessionHistory } from "@/hooks/useSessions";
import { useClient } from "@/providers/ClientProvider";
import { cn } from "@/lib/utils";
import type {
  ReportRow,
  ScanType,
  SessionRow,
  SessionStatus,
  UIMessage,
} from "@/lib/types";

// ─── Status / ScanType meta (mirrors SessionsPage) ──────────────────────────

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
  { labelKey: string; fallback: string; icon: LucideIcon; color: string }
> = {
  full: {
    labelKey: "home.scan.full.label",
    fallback: "全量扫描",
    icon: Crosshair,
    color: "text-primary",
  },
  vuln: {
    labelKey: "home.scan.vuln.label",
    fallback: "漏洞扫描",
    icon: Bug,
    color: "text-orange-500 dark:text-orange-400",
  },
  weakpwd: {
    labelKey: "home.scan.weakpwd.label",
    fallback: "弱口令检测",
    icon: Key,
    color: "text-amber-500 dark:text-amber-400",
  },
  asset: {
    labelKey: "home.scan.asset.label",
    fallback: "仅资产探测",
    icon: Radar,
    color: "text-emerald-500 dark:text-emerald-400",
  },
  query: {
    labelKey: "sessions.type.query",
    fallback: "安全咨询",
    icon: BookOpen,
    color: "text-sky-500 dark:text-sky-400",
  },
};

// ─── Helpers ────────────────────────────────────────────────────────────────

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

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[i]}`;
}

function formatDateTime(iso: string | null, locale: string): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ─── Sub-components ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: SessionStatus }) {
  const { t } = useTranslation();
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium",
        meta.tone,
      )}
    >
      <Icon
        className={cn("h-3.5 w-3.5", status === "running" && "animate-spin")}
      />
      {t(meta.labelKey, { defaultValue: meta.fallback })}
    </span>
  );
}

function ScanTypeBadge({ scanType }: { scanType: ScanType | null }) {
  const { t } = useTranslation();
  if (!scanType) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/20 px-3 py-1 text-xs text-muted-foreground">
        —
      </span>
    );
  }
  const meta = SCAN_TYPE_META[scanType];
  const Icon = meta.icon;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/20 px-3 py-1 text-xs text-muted-foreground">
      <Icon className={cn("h-3.5 w-3.5", meta.color)} />
      {t(meta.labelKey, { defaultValue: meta.fallback })}
    </span>
  );
}

interface KpiCardProps {
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: string;
}

function KpiCard({ icon: Icon, label, value, sub, tone }: KpiCardProps) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border/60 bg-card/40 p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className={cn("h-3.5 w-3.5", tone ?? "text-muted-foreground")} />
        {label}
      </div>
      <div className="text-xl font-semibold tracking-tight text-foreground">
        {value}
      </div>
      {sub ? (
        <div className="text-[11px] text-muted-foreground/70">{sub}</div>
      ) : null}
    </div>
  );
}

function FindingsBreakdown({ row }: { row: SessionRow }) {
  const { t } = useTranslation();
  const { findings } = row;
  if (findings.total === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-muted-foreground">
        <CheckCircle2 className="h-8 w-8 text-emerald-500/60" />
        <p className="text-sm">{t("sessionDetail.findings.none", { defaultValue: "未发现安全问题" })}</p>
      </div>
    );
  }

  const severityLevels: Array<{
    key: "critical" | "high" | "medium" | "low";
    label: string;
    tone: string;
    barTone: string;
  }> = [
    {
      key: "critical",
      label: t("sessionDetail.findings.critical", { defaultValue: "严重" }),
      tone: "text-destructive",
      barTone: "bg-destructive",
    },
    {
      key: "high",
      label: t("sessionDetail.findings.high", { defaultValue: "高危" }),
      tone: "text-orange-500 dark:text-orange-400",
      barTone: "bg-orange-500",
    },
    {
      key: "medium",
      label: t("sessionDetail.findings.medium", { defaultValue: "中危" }),
      tone: "text-amber-500 dark:text-amber-400",
      barTone: "bg-amber-500",
    },
    {
      key: "low",
      label: t("sessionDetail.findings.low", { defaultValue: "低危" }),
      tone: "text-muted-foreground",
      barTone: "bg-muted-foreground/50",
    },
  ];

  const max = Math.max(...severityLevels.map((s) => findings[s.key]), 1);

  return (
    <div className="flex flex-col gap-3">
      {severityLevels.map((sev) => {
        const count = findings[sev.key];
        const pct = Math.round((count / max) * 100);
        return (
          <div key={sev.key} className="flex items-center gap-3">
            <span
              className={cn(
                "w-10 text-right text-xs font-medium tabular-nums",
                sev.tone,
              )}
            >
              {sev.label}
            </span>
            <div className="relative h-5 flex-1 overflow-hidden rounded-full bg-muted/30">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  sev.barTone,
                  count === 0 && "opacity-0",
                )}
                style={{ width: `${Math.max(pct, count > 0 ? 4 : 0)}%` }}
              />
              <span className="absolute inset-0 flex items-center px-2 text-[11px] font-semibold tabular-nums text-foreground/80">
                {count}
              </span>
            </div>
          </div>
        );
      })}
      <div className="mt-1 flex items-center justify-end gap-1 text-xs text-muted-foreground">
        <ShieldAlert className="h-3.5 w-3.5" />
        <span className="font-medium tabular-nums">{findings.total}</span>
        {t("sessionDetail.findings.totalSuffix", { defaultValue: "项发现" })}
      </div>
    </div>
  );
}

function ReportList({ reports }: { reports: ReportRow[] }) {
  const { t } = useTranslation();
  if (reports.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-muted-foreground">
        <FileText className="h-8 w-8 text-muted-foreground/40" />
        <p className="text-sm">
          {t("sessionDetail.reports.none", { defaultValue: "未生成报告" })}
        </p>
      </div>
    );
  }
  return (
    <ul className="flex flex-col gap-2">
      {reports.map((report) => (
        <li
          key={report.id}
          className="flex items-center gap-3 rounded-lg border border-border/50 bg-background/40 px-3 py-2.5 transition-colors hover:border-primary/30 hover:bg-primary/5"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">
              {report.title}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {report.format.toUpperCase()} · {formatBytes(report.sizeBytes)}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" className="h-8 gap-1 px-2.5 text-xs" asChild>
              <a href={report.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-3.5 w-3.5" />
                {t("sessionDetail.reports.open", { defaultValue: "打开" })}
              </a>
            </Button>
            <Button variant="outline" size="sm" className="h-8 gap-1 px-2.5 text-xs" asChild>
              <a href={report.url} download>
                <Download className="h-3.5 w-3.5" />
                {t("sessionDetail.reports.download", { defaultValue: "下载" })}
              </a>
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function TimelineItem({
  icon: Icon,
  label,
  time,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  time: string;
  tone?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
          tone ?? "border-border/60 bg-muted/20 text-muted-foreground",
        )}
      >
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-foreground">{label}</p>
        <p className="text-[11px] text-muted-foreground">{time}</p>
      </div>
    </div>
  );
}

function SessionTimeline({
  row,
  locale,
  isQuery,
}: {
  row: SessionRow;
  locale: string;
  isQuery: boolean;
}) {
  const { t } = useTranslation();
  const events: Array<{
    icon: LucideIcon;
    label: string;
    time: string;
    tone?: string;
  }> = [];

  events.push({
    icon: Play,
    label: t("sessionDetail.timeline.sessionCreated", {
      defaultValue: "会话创建",
    }),
    time: formatDateTime(row.createdAt, locale),
    tone: "border-primary/30 bg-primary/10 text-primary",
  });

  if (row.status === "running") {
    events.push({
      icon: Loader2,
      label: isQuery
        ? t("sessionDetail.timeline.processing", {
            defaultValue: "正在处理…",
          })
        : t("sessionDetail.timeline.scanning", {
            defaultValue: "正在扫描…",
          }),
      time: t("sessionDetail.timeline.inProgress", {
        defaultValue: "进行中",
      }),
      tone: "border-primary/30 bg-primary/10 text-primary",
    });
  }

  if (row.status === "finished") {
    events.push({
      icon: CheckCircle2,
      label: isQuery
        ? t("sessionDetail.timeline.queryCompleted", {
            defaultValue: "会话完成",
          })
        : t("sessionDetail.timeline.completed", {
            defaultValue: "扫描完成",
          }),
      time: formatDateTime(row.updatedAt, locale),
      tone:
        "border-emerald-500/30 bg-emerald-500/10 text-emerald-500 dark:text-emerald-400",
    });
  }

  if (row.status === "failed") {
    events.push({
      icon: XCircle,
      label: isQuery
        ? t("sessionDetail.timeline.queryFailed", {
            defaultValue: "会话失败",
          })
        : t("sessionDetail.timeline.failed", {
            defaultValue: "扫描失败",
          }),
      time: formatDateTime(row.updatedAt, locale),
      tone: "border-destructive/30 bg-destructive/10 text-destructive",
    });
  }

  if (row.status === "stopped") {
    events.push({
      icon: AlertCircle,
      label: t("sessionDetail.timeline.stopped", {
        defaultValue: "用户停止",
      }),
      time: formatDateTime(row.updatedAt, locale),
      tone: "border-muted-foreground/30 bg-muted/20 text-muted-foreground",
    });
  }

  if (row.reports.length > 0) {
    events.push({
      icon: FileText,
      label: t("sessionDetail.timeline.reportGenerated", {
        defaultValue: `${row.reports.length} 份报告已生成`,
      }),
      time: formatDateTime(row.reports[0].createdAt, locale),
      tone: "border-primary/30 bg-primary/10 text-primary",
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {events.map((event, idx) => (
        <TimelineItem key={idx} {...event} />
      ))}
    </div>
  );
}

// ─── Message classification ──────────────────────────────────────────────────

type MessageCategory = "all" | "tools" | "errors" | "thinking" | "respond";

const ERROR_KEYWORDS = [
  "error",
  "exception",
  "traceback",
  "failed",
  "failure",
  "失败",
  "错误",
  "异常",
];

function isErrorMessage(msg: UIMessage): boolean {
  // 思考类消息不应归入错误列表，即使内容中包含错误关键词
  if (msg.kind === "agent_event" && msg.agentEvent) {
    const t = msg.agentEvent.type;
    if (t === "thought" || t === "orchestrator_plan" || t === "blackboard_entry")
      return false;
  }
  if (msg.kind === "agent_event" && msg.agentEvent) {
    const evt = msg.agentEvent;
    if (evt.type === "llm_retry") return true;
    if (evt.type === "tool_call" && (evt.tool_status === "error" || evt.status === "error"))
      return true;
    if (evt.type === "high_risk_confirm") return true;
  }
  if (msg.toolCalls?.some((tc) => tc.tool_status === "error" || tc.status === "error"))
    return true;
  const lower = msg.content.toLowerCase();
  return ERROR_KEYWORDS.some((kw) => lower.includes(kw));
}

function isToolMessage(msg: UIMessage): boolean {
  if (msg.kind === "trace") return true;
  if (msg.toolCalls && msg.toolCalls.length > 0) return true;
  if (msg.kind === "agent_event" && msg.agentEvent) {
    const t = msg.agentEvent.type;
    if (
      t === "tool_call" ||
      t === "subagent_spawned" ||
      t === "subagent_done" ||
      t === "subagent_status" ||
      t === "asset_pushed"
    )
      return true;
  }
  return false;
}

function isThinkingMessage(msg: UIMessage): boolean {
  if (msg.kind === "agent_event" && msg.agentEvent) {
    const t = msg.agentEvent.type;
    if (t === "thought" || t === "orchestrator_plan" || t === "blackboard_entry")
      return true;
  }
  return false;
}

function isRespondMessage(msg: UIMessage): boolean {
  return msg.role === "assistant" && (msg.kind === "message" || !msg.kind);
}

function classifyMessages(
  messages: UIMessage[],
): Record<MessageCategory, UIMessage[]> {
  return {
    all: messages,
    tools: messages.filter(isToolMessage),
    errors: messages.filter(isErrorMessage),
    thinking: messages.filter(isThinkingMessage),
    respond: messages.filter(isRespondMessage),
  };
}

interface CategoryTabMeta {
  key: MessageCategory;
  icon: LucideIcon;
  labelKey: string;
  fallback: string;
  tone: string;
  activeTone: string;
}

const CATEGORY_TABS: CategoryTabMeta[] = [
  {
    key: "all",
    icon: Layers,
    labelKey: "sessionDetail.messages.catAll",
    fallback: "全部",
    tone: "text-muted-foreground",
    activeTone: "bg-primary/10 text-primary border-primary/40",
  },
  {
    key: "tools",
    icon: Wrench,
    labelKey: "sessionDetail.messages.catTools",
    fallback: "工具调用",
    tone: "text-blue-500 dark:text-blue-400",
    activeTone:
      "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/40",
  },
  {
    key: "errors",
    icon: AlertTriangle,
    labelKey: "sessionDetail.messages.catErrors",
    fallback: "错误",
    tone: "text-destructive",
    activeTone:
      "bg-destructive/10 text-destructive border-destructive/40",
  },
  {
    key: "thinking",
    icon: Brain,
    labelKey: "sessionDetail.messages.catThinking",
    fallback: "思考过程",
    tone: "text-violet-500 dark:text-violet-400",
    activeTone:
      "bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/40",
  },
  {
    key: "respond",
    icon: MessageSquare,
    labelKey: "sessionDetail.messages.catRespond",
    fallback: "响应输出",
    tone: "text-emerald-500 dark:text-emerald-400",
    activeTone:
      "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/40",
  },
];

function SessionMessagesPanel({ sessionKey }: { sessionKey: string }) {
  const { t } = useTranslation();
  const { messages, loading } = useSessionHistory(sessionKey);
  const [activeTab, setActiveTab] = useState<MessageCategory>("all");

  const classified = useMemo(() => classifyMessages(messages), [messages]);
  const activeMessages = classified[activeTab];
  // Auto-expand all collapsible entries when a specific category is active,
  // so users see full detail immediately upon clicking a filter tab.
  const defaultExpanded = activeTab !== "all";

  return (
    <div className="flex flex-col rounded-2xl border border-border/60 bg-card/30 overflow-hidden">
      {/* ── Tab bar ──────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 border-b border-border/40 px-4 py-2.5 overflow-x-auto scrollbar-none">
        {CATEGORY_TABS.map((tab) => {
          const Icon = tab.icon;
          const count = classified[tab.key].length;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all duration-150",
                isActive
                  ? tab.activeTone
                  : cn(
                      "border-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                      !isActive && count === 0 && "opacity-50",
                    ),
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t(tab.labelKey, { defaultValue: tab.fallback })}
              <span
                className={cn(
                  "min-w-[18px] rounded px-1 text-center text-[10px] font-semibold tabular-nums",
                  isActive ? "opacity-90" : "bg-muted/50",
                )}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── Content area ────────────────────────────────────── */}
      <div className="max-h-[600px] overflow-y-auto scrollbar-thin [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-muted-foreground/20 [&::-webkit-scrollbar-track]:bg-transparent">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("sessionDetail.messages.loading", {
              defaultValue: "加载会话记录…",
            })}
          </div>
        ) : activeMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
            <div className="rounded-full bg-muted/30 p-3 text-muted-foreground/50">
              <MessageSquare className="h-6 w-6" />
            </div>
            <p className="text-sm text-muted-foreground">
              {activeTab === "all"
                ? t("sessionDetail.messages.empty", {
                    defaultValue: "暂无会话记录",
                  })
                : t("sessionDetail.messages.emptyCategory", {
                    defaultValue: "该分类下暂无记录",
                  })}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4 p-5">
            {activeMessages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} defaultExpanded={defaultExpanded} />
            ))}
          </div>
        )}
      </div>

      {/* ── Footer stats ────────────────────────────────────── */}
      {messages.length > 0 && (
        <div className="flex items-center justify-between border-t border-border/30 px-5 py-2.5 text-[11px] text-muted-foreground">
          <span>
            {t("sessionDetail.messages.totalCount", {
              defaultValue: "共 {{count}} 条记录",
              count: messages.length,
            })}
          </span>
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Wrench className="h-3 w-3 text-blue-500/70" />
              {classified.tools.length}
            </span>
            <span className="flex items-center gap-1">
              <AlertTriangle className="h-3 w-3 text-destructive/70" />
              {classified.errors.length}
            </span>
            <span className="flex items-center gap-1">
              <Brain className="h-3 w-3 text-violet-500/70" />
              {classified.thinking.length}
            </span>
            <span className="flex items-center gap-1">
              <MessageSquare className="h-3 w-3 text-emerald-500/70" />
              {classified.respond.length}
            </span>
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

/**
 * `/session/:key` — Structured detail page for a single scan session,
 * showing findings breakdown, token statistics, generated reports and
 * a session timeline.
 */
export function SessionDetailPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { key } = useParams<{ key: string }>();
  const { sessions, loading } = useSessionsList();
  const { client } = useClient();
  const locale = i18n.resolvedLanguage ?? "zh-CN";

  const row = useMemo(
    () => sessions.find((s) => s.key === decodeURIComponent(key ?? "")) ?? null,
    [sessions, key],
  );

  // ── Loading ─────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex h-screen w-full flex-col overflow-hidden">
        <Navbar />
        <main className="flex flex-1 items-center justify-center">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("sessionDetail.loading", { defaultValue: "加载会话详情…" })}
          </div>
        </main>
      </div>
    );
  }

  // ── Not found ───────────────────────────────────────────────────────
  if (!row) {
    return (
      <div className="flex h-screen w-full flex-col overflow-hidden">
        <Navbar />
        <main className="flex flex-1 items-center justify-center">
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="rounded-full bg-muted/40 p-4 text-muted-foreground">
              <Inbox className="h-8 w-8" />
            </div>
            <p className="text-sm font-medium text-foreground">
              {t("sessionDetail.notFound.title", {
                defaultValue: "未找到该会话",
              })}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("sessionDetail.notFound.subtitle", {
                defaultValue: "该会话可能已被删除或不存在",
              })}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/sessions")}
              className="gap-1.5"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              {t("sessionDetail.backToList", {
                defaultValue: "返回历史会话",
              })}
            </Button>
          </div>
        </main>
      </div>
    );
  }

  // ── Derived values ──────────────────────────────────────────────────
  const isQuery = row.scanType === "query";
  const cacheRate =
    row.tokens.input > 0
      ? Math.round((row.tokens.cached / row.tokens.input) * 100)
      : 0;
  const cacheTone =
    cacheRate > 80
      ? "text-emerald-500"
      : cacheRate >= 50
        ? "text-amber-500"
        : "text-destructive";

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      <Navbar />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-6 py-8">
          {/* ── Breadcrumb & Actions ──────────────────────────────── */}
          <div className="flex flex-col gap-3">
            <button
              type="button"
              onClick={() => navigate("/sessions")}
              className="inline-flex w-fit items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              {t("sessionDetail.backToList", {
                defaultValue: "返回历史会话",
              })}
            </button>

            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold tracking-tight text-foreground">
                    {row.title || row.chatId.slice(0, 8)}
                  </h1>
                  <StatusBadge status={row.status} />
                  <ScanTypeBadge scanType={row.scanType} />
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {row.target ? (
                    <span className="rounded bg-muted/30 px-1.5 py-0.5 font-mono text-[11px]">
                      {row.target}
                    </span>
                  ) : null}
                  <span aria-hidden>·</span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {formatDateTime(row.createdAt, locale)}
                  </span>
                  <span aria-hidden>·</span>
                  <span>{formatDuration(row.durationMs)}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() =>
                    navigate(`/?session=${encodeURIComponent(row.key)}`)
                  }
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  {t("sessionDetail.openChat", {
                    defaultValue: "打开对话",
                  })}
                  <ArrowUpRight className="h-3 w-3" />
                </Button>
                {row.status === "running" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5 text-amber-500 hover:bg-amber-500/10 hover:text-amber-600 dark:text-amber-400 dark:hover:text-amber-300"
                    onClick={() => client.stopChat(row.chatId)}
                  >
                    <StopCircle className="h-3.5 w-3.5" />
                    {t("sessionDetail.interrupt", {
                      defaultValue: "中断会话",
                    })}
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t("sessionDetail.delete", { defaultValue: "删除" })}
                </Button>
              </div>
            </div>
          </div>

          {/* ── KPI Cards ─────────────────────────────────────────── */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {isQuery ? (
              <KpiCard
                icon={BookOpen}
                label={t("sessionDetail.kpi.sessionType", {
                  defaultValue: "会话类型",
                })}
                value={
                  <span className="flex items-center gap-1.5">
                    <BookOpen className="h-4 w-4 text-sky-500 dark:text-sky-400" />
                    {t("sessions.type.query", { defaultValue: "安全咨询" })}
                  </span>
                }
                sub={
                  <span className="text-sky-500/80 dark:text-sky-400/80">
                    {t("sessionDetail.kpi.queryHint", {
                      defaultValue: "知识查询 / 安全咨询",
                    })}
                  </span>
                }
                tone="text-sky-500 dark:text-sky-400"
              />
            ) : (
              <KpiCard
                icon={ShieldAlert}
                label={t("sessionDetail.kpi.findings", {
                  defaultValue: "安全发现",
                })}
                value={
                  <span className="tabular-nums">{row.findings.total}</span>
                }
                sub={
                  row.findings.total > 0 ? (
                    <span className="flex flex-wrap gap-1.5">
                      {row.findings.critical > 0 && (
                        <span className="text-destructive">
                          C:{row.findings.critical}
                        </span>
                      )}
                      {row.findings.high > 0 && (
                        <span className="text-orange-500 dark:text-orange-400">
                          H:{row.findings.high}
                        </span>
                      )}
                      {row.findings.medium > 0 && (
                        <span className="text-amber-500 dark:text-amber-400">
                          M:{row.findings.medium}
                        </span>
                      )}
                      {row.findings.low > 0 && (
                        <span className="text-muted-foreground">
                          L:{row.findings.low}
                        </span>
                      )}
                    </span>
                  ) : null
                }
                tone={
                  row.findings.critical > 0
                    ? "text-destructive"
                    : row.findings.high > 0
                      ? "text-orange-500"
                      : "text-emerald-500"
                }
              />
            )}
            <KpiCard
              icon={Cpu}
              label={t("sessionDetail.kpi.tokens", {
                defaultValue: "Token 用量",
              })}
              value={
                <span className="tabular-nums">
                  ↓{compactNumber(row.tokens.input)}{" "}
                  <span className="text-muted-foreground/50">·</span>{" "}
                  ↑{compactNumber(row.tokens.output)}
                </span>
              }
              sub={
                <span className="tabular-nums">
                  Total:{" "}
                  {compactNumber(row.tokens.input + row.tokens.output)}
                </span>
              }
              tone="text-primary"
            />
            <KpiCard
              icon={History}
              label={t("sessionDetail.kpi.cacheRate", {
                defaultValue: "缓存命中率",
              })}
              value={
                <span className={cn("tabular-nums", cacheTone)}>
                  {row.tokens.input > 0 ? `${cacheRate}%` : "—"}
                </span>
              }
              sub={
                <span className="tabular-nums">
                  Cached: {compactNumber(row.tokens.cached)}
                </span>
              }
              tone={cacheTone}
            />
            <KpiCard
              icon={Clock}
              label={t("sessionDetail.kpi.duration", {
                defaultValue: "耗时",
              })}
              value={formatDuration(row.durationMs)}
              sub={
                row.status === "running" ? (
                  <span className="flex items-center gap-1 text-primary">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {t("sessionDetail.kpi.running", {
                      defaultValue: "进行中",
                    })}
                  </span>
                ) : null
              }
              tone="text-muted-foreground"
            />
          </div>

          {/* ── Conversation Content (classified by type) ────────── */}
          <section>
            <div className="mb-3 flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-medium text-foreground">
                {t("sessionDetail.section.messages", {
                  defaultValue: "会话记录",
                })}
              </h2>
            </div>
            <SessionMessagesPanel sessionKey={row.key} />
          </section>

          {/* ── Main Grid: Left + Right ───────────────────────────── */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_360px]">
            {/* ── Left column ─────────────────────────────────── */}
            <div className="flex flex-col gap-6">
              {/* Findings breakdown — only for scan sessions */}
              {!isQuery && (
                <section className="rounded-2xl border border-border/60 bg-card/30">
                  <div className="flex items-center gap-2 border-b border-border/40 px-5 py-3">
                    <ShieldAlert className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium text-foreground">
                      {t("sessionDetail.section.findings", {
                        defaultValue: "安全发现详情",
                      })}
                    </h2>
                  </div>
                  <div className="p-5">
                    <FindingsBreakdown row={row} />
                  </div>
                </section>
              )}

              {/* Session Timeline */}
              <section className="rounded-2xl border border-border/60 bg-card/30">
                <div className="flex items-center gap-2 border-b border-border/40 px-5 py-3">
                  <History className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-medium text-foreground">
                    {t("sessionDetail.section.timeline", {
                      defaultValue: "会话时间线",
                    })}
                  </h2>
                </div>
                <div className="p-5">
                  <SessionTimeline row={row} locale={locale} isQuery={isQuery} />
                </div>
              </section>

              {/* Session Info */}
              <section className="rounded-2xl border border-border/60 bg-card/30">
                <div className="flex items-center gap-2 border-b border-border/40 px-5 py-3">
                  <MessageSquare className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-medium text-foreground">
                    {t("sessionDetail.section.info", {
                      defaultValue: "会话信息",
                    })}
                  </h2>
                </div>
                <div className="p-5">
                  <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("sessionDetail.info.sessionKey", {
                          defaultValue: "会话 Key",
                        })}
                      </dt>
                      <dd className="mt-0.5 truncate font-mono text-xs text-foreground/80">
                        {row.key}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("sessionDetail.info.chatId", {
                          defaultValue: "Chat ID",
                        })}
                      </dt>
                      <dd className="mt-0.5 font-mono text-xs text-foreground/80">
                        {row.chatId}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("sessionDetail.info.channel", {
                          defaultValue: "通道",
                        })}
                      </dt>
                      <dd className="mt-0.5 text-xs text-foreground/80">
                        {row.channel}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {isQuery
                          ? t("sessionDetail.info.topic", {
                              defaultValue: "查询主题",
                            })
                          : t("sessionDetail.info.target", {
                              defaultValue: "扫描目标",
                            })}
                      </dt>
                      <dd className="mt-0.5 font-mono text-xs text-foreground/80">
                        {row.target ?? (isQuery ? t("sessionDetail.info.noTopic", { defaultValue: "—" }) : "—")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("sessionDetail.info.createdAt", {
                          defaultValue: "创建时间",
                        })}
                      </dt>
                      <dd className="mt-0.5 text-xs text-foreground/80">
                        {formatDateTime(row.createdAt, locale)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        {t("sessionDetail.info.updatedAt", {
                          defaultValue: "最后更新",
                        })}
                      </dt>
                      <dd className="mt-0.5 text-xs text-foreground/80">
                        {formatDateTime(row.updatedAt, locale)}
                      </dd>
                    </div>
                  </dl>
                  {row.preview ? (
                    <div className="mt-4 border-t border-border/30 pt-3">
                      <dt className="text-xs text-muted-foreground">
                        {t("sessionDetail.info.preview", {
                          defaultValue: "会话摘要",
                        })}
                      </dt>
                      <dd className="mt-1 text-sm leading-relaxed text-foreground/70">
                        {row.preview}
                      </dd>
                    </div>
                  ) : null}
                </div>
              </section>
            </div>

            {/* ── Right column ────────────────────────────────── */}
            <div className="flex flex-col gap-6">
              {/* Reports */}
              <section className="rounded-2xl border border-border/60 bg-card/30">
                <div className="flex items-center gap-2 border-b border-border/40 px-5 py-3">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-medium text-foreground">
                    {t("sessionDetail.section.reports", {
                      defaultValue: "生成报告",
                    })}
                  </h2>
                  {row.reports.length > 0 && (
                    <span className="ml-auto rounded bg-primary/10 px-1.5 text-[10px] font-semibold text-primary">
                      {row.reports.length}
                    </span>
                  )}
                </div>
                <div className="p-5">
                  <ReportList reports={row.reports} />
                </div>
              </section>

              {/* Token Breakdown */}
              <section className="rounded-2xl border border-border/60 bg-card/30">
                <div className="flex items-center gap-2 border-b border-border/40 px-5 py-3">
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-medium text-foreground">
                    {t("sessionDetail.section.tokenBreakdown", {
                      defaultValue: "Token 明细",
                    })}
                  </h2>
                </div>
                <div className="p-5">
                  <div className="flex flex-col gap-3">
                    {/* Input tokens */}
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">
                        {t("sessionDetail.tokens.input", {
                          defaultValue: "输入 Tokens",
                        })}
                      </span>
                      <span className="font-mono font-medium tabular-nums text-foreground">
                        {row.tokens.input.toLocaleString()}
                      </span>
                    </div>
                    {/* Output tokens */}
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">
                        {t("sessionDetail.tokens.output", {
                          defaultValue: "输出 Tokens",
                        })}
                      </span>
                      <span className="font-mono font-medium tabular-nums text-foreground">
                        {row.tokens.output.toLocaleString()}
                      </span>
                    </div>
                    {/* Cached tokens */}
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">
                        {t("sessionDetail.tokens.cached", {
                          defaultValue: "缓存 Tokens",
                        })}
                      </span>
                      <span className="font-mono font-medium tabular-nums text-foreground">
                        {row.tokens.cached.toLocaleString()}
                      </span>
                    </div>
                    {/* Divider */}
                    <div className="border-t border-border/30" />
                    {/* Total */}
                    <div className="flex items-center justify-between text-sm font-medium">
                      <span className="text-foreground">
                        {t("sessionDetail.tokens.total", {
                          defaultValue: "总计",
                        })}
                      </span>
                      <span className="font-mono tabular-nums text-foreground">
                        {(
                          row.tokens.input + row.tokens.output
                        ).toLocaleString()}
                      </span>
                    </div>
                    {/* Cache rate bar */}
                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>
                          {t("sessionDetail.tokens.cacheRate", {
                            defaultValue: "缓存命中率",
                          })}
                        </span>
                        <span
                          className={cn("font-medium tabular-nums", cacheTone)}
                        >
                          {row.tokens.input > 0 ? `${cacheRate}%` : "—"}
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted/30">
                        <div
                          className={cn(
                            "h-full rounded-full transition-all duration-500",
                            cacheRate > 80
                              ? "bg-emerald-500"
                              : cacheRate >= 50
                                ? "bg-amber-500"
                                : "bg-destructive",
                          )}
                          style={{
                            width: `${Math.max(cacheRate, row.tokens.input > 0 ? 2 : 0)}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default SessionDetailPage;
