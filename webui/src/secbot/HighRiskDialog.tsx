interface ConfirmPayload {
  scan_id: string;
  skill: string;
  args: Record<string, unknown>;
  estimated_impact?: string;
  network_egress?: string;
}

/**
 * Destructive AlertDialog used by the orchestrator's HighRiskGate.
 * Wired into runtime.ts via a custom event channel — the runtime emits
 * `confirm_request`, the dialog resolves with approve/deny back over WS.
 */
export function HighRiskDialog({
  payload,
  onApprove,
  onDeny,
}: {
  payload: ConfirmPayload | null;
  onApprove: () => void;
  onDeny: () => void;
}) {
  if (!payload) return null;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-md border border-severity-critical/40 bg-popover p-5 shadow-xl">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-2xl text-severity-critical">⚠</span>
          <h2 className="text-base font-semibold">确认执行高危操作</h2>
        </div>
        <dl className="mb-4 space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-text-secondary">Skill</dt>
            <dd className="font-mono">{payload.skill}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-text-secondary">Scan</dt>
            <dd className="font-mono text-xs">{payload.scan_id}</dd>
          </div>
          {payload.network_egress && (
            <div className="flex justify-between gap-3">
              <dt className="text-text-secondary">网络出口</dt>
              <dd>{payload.network_egress}</dd>
            </div>
          )}
          {payload.estimated_impact && (
            <div>
              <dt className="text-text-secondary">预估影响</dt>
              <dd className="mt-0.5">{payload.estimated_impact}</dd>
            </div>
          )}
          <div>
            <dt className="text-text-secondary">参数</dt>
            <dd>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-background/40 p-2 font-mono text-xs">
{JSON.stringify(payload.args, null, 2)}
              </pre>
            </dd>
          </div>
        </dl>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onDeny}
            className="rounded border border-border px-3 py-1.5 text-sm hover:bg-card"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onApprove}
            className="rounded bg-severity-critical px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            确认执行
          </button>
        </div>
      </div>
    </div>
  );
}
