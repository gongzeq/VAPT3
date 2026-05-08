/**
 * Common helpers for skill renderers (severity badges, status pills,
 * link to the raw log).
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info";

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

const SEVERITY_BG: Record<Severity, string> = {
  critical: "bg-severity-critical/15 text-severity-critical border-severity-critical/40",
  high: "bg-severity-high/15 text-severity-high border-severity-high/40",
  medium: "bg-severity-medium/15 text-severity-medium border-severity-medium/40",
  low: "bg-severity-low/15 text-severity-low border-severity-low/40",
  info: "bg-severity-info/15 text-severity-info border-severity-info/40",
};

export function SeverityBadge({ level }: { level: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${SEVERITY_BG[level]}`}
    >
      {SEVERITY_LABEL[level]}
    </span>
  );
}

export function SeveritySummary({ counts }: { counts: Partial<Record<Severity, number>> }) {
  const order: Severity[] = ["critical", "high", "medium", "low", "info"];
  return (
    <div className="flex flex-wrap gap-1.5">
      {order.map((sev) => {
        const n = counts[sev] ?? 0;
        if (!n) return null;
        return (
          <span
            key={sev}
            className={`rounded border px-1.5 py-0.5 text-xs ${SEVERITY_BG[sev]}`}
          >
            {SEVERITY_LABEL[sev]} · {n}
          </span>
        );
      })}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const cls =
    status === "ok"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
      : status === "error"
        ? "bg-red-500/15 text-red-300 border-red-500/40"
        : "bg-slate-500/15 text-slate-300 border-slate-500/40";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] ${cls}`}>
      {status}
    </span>
  );
}

export function RawLogLink({ scanId, skill }: { scanId?: string; skill: string }) {
  if (!scanId) return null;
  return (
    <a
      className="text-xs text-primary hover:underline"
      href={`/api/scans/${scanId}/raw/${skill}.log`}
      target="_blank"
      rel="noreferrer"
    >
      查看原始日志 ↗
    </a>
  );
}
