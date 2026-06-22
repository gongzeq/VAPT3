/**
 * Review Queue Page — PRD §7.2 低置信度复核队列.
 *
 * Gap Fixes:
 * - §9: Remap action with group selector for IP items
 * - §10: Note input field for each review item
 * - §13: Pagination controls
 */

import { useCallback, useEffect, useState } from "react";
import { Check, X, ExternalLink, Shuffle } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchReviewQueue,
  submitReviewAction,
  fetchGroups,
  type ReviewQueueItem,
  type ThreatGroupSummary,
} from "@/lib/threat-intel-client";

const PAGE_SIZE = 20;

export function ReviewQueuePage() {
  const { token } = useClient();
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [entityType, setEntityType] = useState("ip");
  const [page, setPage] = useState(1);

  // Gap 9: Remap state
  const [showRemap, setShowRemap] = useState<string | null>(null);
  const [remapGroupId, setRemapGroupId] = useState("");
  const [groups, setGroups] = useState<ThreatGroupSummary[]>([]);

  // Gap 10: Note input state
  const [notes, setNotes] = useState<Record<string, string>>({});

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchReviewQueue(token, { type: entityType, page, page_size: PAGE_SIZE });
      setItems(result.items);
      setTotal(result.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, entityType, page]);

  useEffect(() => { load(); }, [load]);

  // Load groups for remap selector
  useEffect(() => {
    fetchGroups(token, { page_size: 200 })
      .then((result) => setGroups(result.items))
      .catch(() => { /* ignore */ });
  }, [token]);

  // Gap 10: handleAction with note support
  const handleAction = async (item: ReviewQueueItem, action: string, extra: Record<string, unknown> = {}) => {
    await submitReviewAction(token, item.id, action, {
      entity_type: item.entity_type,
      note: notes[item.id] || undefined,
      ...extra,
    });
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    setTotal((prev) => prev - 1);
    // Clear note for this item
    setNotes((prev) => {
      const next = { ...prev };
      delete next[item.id];
      return next;
    });
  };

  // Gap 9: Handle remap confirmation
  const handleRemap = async (item: ReviewQueueItem) => {
    if (!remapGroupId) return;
    await handleAction(item, "remap", { new_group_id: remapGroupId });
    setShowRemap(null);
    setRemapGroupId("");
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">低置信度复核队列</h1>
        <span className="text-sm text-slate-600">共 {total} 条待审</span>
      </div>

      <div className="flex gap-2">
        <select
          value={entityType}
          onChange={(e) => { setEntityType(e.target.value); setPage(1); }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="ip">IP地址</option>
          <option value="maritime">海事事件</option>
        </select>
      </div>

      {loading ? (
        <div className="text-slate-400">加载中...</div>
      ) : items.length === 0 ? (
        <div className="text-slate-400">暂无待审核记录</div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <div key={item.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900">{item.label}</span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      置信度: {item.confidence.toFixed(2)}
                    </span>
                  </div>
                  {item.group_name && (
                    <p className="mt-1 text-sm text-slate-500">当前关联: {item.group_name} (来源: {item.source})</p>
                  )}
                  {item.source_refs.length > 0 && item.source_refs[0].url && (
                    <a
                      href={item.source_refs[0].url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 flex items-center gap-1 text-xs text-indigo-600 hover:underline"
                    >
                      <ExternalLink className="h-3 w-3" /> {item.source_refs[0].url}
                    </a>
                  )}
                </div>
                <div className="flex gap-2">
                  {item.entity_type === "ip" ? (
                    <>
                      <button
                        onClick={() => handleAction(item, "confirm_mapping")}
                        className="flex items-center gap-1 rounded bg-green-50 px-3 py-1 text-sm text-green-600 hover:bg-green-100"
                      >
                        <Check className="h-4 w-4" /> 确认关联
                      </button>
                      {/* Gap 9: Remap button */}
                      <button
                        onClick={() => setShowRemap(showRemap === item.id ? null : item.id)}
                        className="flex items-center gap-1 rounded bg-amber-50 px-3 py-1 text-sm text-amber-600 hover:bg-amber-100"
                      >
                        <Shuffle className="h-4 w-4" /> 重新关联
                      </button>
                      <button
                        onClick={() => handleAction(item, "dismiss")}
                        className="flex items-center gap-1 rounded bg-slate-50 px-3 py-1 text-sm text-slate-600 hover:bg-slate-100"
                      >
                        <X className="h-4 w-4" /> 驳回归档
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => handleAction(item, "confirm_event")}
                        className="flex items-center gap-1 rounded bg-green-50 px-3 py-1 text-sm text-green-600 hover:bg-green-100"
                      >
                        <Check className="h-4 w-4" /> 确认事件
                      </button>
                      <button
                        onClick={() => handleAction(item, "dismiss")}
                        className="flex items-center gap-1 rounded bg-slate-50 px-3 py-1 text-sm text-slate-600 hover:bg-slate-100"
                      >
                        <X className="h-4 w-4" /> 驳回
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Gap 9: Remap group selector */}
              {showRemap === item.id && (
                <div className="mt-3 flex items-center gap-2 rounded bg-amber-50 p-3">
                  <select
                    value={remapGroupId}
                    onChange={(e) => setRemapGroupId(e.target.value)}
                    className="flex-1 rounded border border-slate-200 px-3 py-1.5 text-sm"
                  >
                    <option value="">选择组织...</option>
                    {groups.map((g) => (
                      <option key={g.id} value={g.id}>{g.name}</option>
                    ))}
                  </select>
                  <button
                    onClick={() => handleRemap(item)}
                    disabled={!remapGroupId}
                    className="rounded bg-amber-500 px-3 py-1.5 text-sm text-white hover:bg-amber-600 disabled:opacity-40"
                  >
                    确认
                  </button>
                  <button
                    onClick={() => { setShowRemap(null); setRemapGroupId(""); }}
                    className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
                  >
                    取消
                  </button>
                </div>
              )}

              {/* Gap 10: Note input */}
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="text"
                  placeholder="输入备注..."
                  value={notes[item.id] || ""}
                  onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })}
                  className="flex-1 rounded border border-slate-200 px-3 py-1 text-sm"
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Gap 13: Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="rounded border border-slate-200 px-3 py-1 text-sm disabled:opacity-50"
          >
            上一页
          </button>
          <span className="text-sm text-slate-600">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="rounded border border-slate-200 px-3 py-1 text-sm disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}

export default ReviewQueuePage;
