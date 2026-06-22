/**
 * Review Queue Page — PRD §7.2 低置信度复核队列.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, X, ExternalLink } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchReviewQueue, submitReviewAction, type ReviewQueueItem } from "@/lib/threat-intel-client";

export function ReviewQueuePage() {
  const { token } = useClient();
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [entityType, setEntityType] = useState("ip");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchReviewQueue(token, { type: entityType, page, page_size: 20 });
      setItems(result.items);
      setTotal(result.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, entityType, page]);

  useEffect(() => { load(); }, [load]);

  const handleAction = async (item: ReviewQueueItem, action: string) => {
    await submitReviewAction(token, item.id, action, { entity_type: item.entity_type });
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    setTotal((prev) => prev - 1);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">低置信度复核队列</h1>
        <span className="text-sm text-slate-600">共 {total} 条待审</span>
      </div>

      <div className="flex gap-2">
        <select value={entityType} onChange={(e) => { setEntityType(e.target.value); setPage(1); }} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
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
                    <a href={item.source_refs[0].url} target="_blank" rel="noopener noreferrer" className="mt-1 flex items-center gap-1 text-xs text-indigo-600 hover:underline">
                      <ExternalLink className="h-3 w-3" /> {item.source_refs[0].url}
                    </a>
                  )}
                </div>
                <div className="flex gap-2">
                  {item.entity_type === "ip" ? (
                    <>
                      <button onClick={() => handleAction(item, "confirm_mapping")} className="flex items-center gap-1 rounded bg-green-50 px-3 py-1 text-sm text-green-600 hover:bg-green-100">
                        <Check className="h-4 w-4" /> 确认关联
                      </button>
                      <button onClick={() => handleAction(item, "dismiss")} className="flex items-center gap-1 rounded bg-slate-50 px-3 py-1 text-sm text-slate-600 hover:bg-slate-100">
                        <X className="h-4 w-4" /> 驳回归档
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => handleAction(item, "confirm_event")} className="flex items-center gap-1 rounded bg-green-50 px-3 py-1 text-sm text-green-600 hover:bg-green-100">
                        <Check className="h-4 w-4" /> 确认事件
                      </button>
                      <button onClick={() => handleAction(item, "dismiss")} className="flex items-center gap-1 rounded bg-slate-50 px-3 py-1 text-sm text-slate-600 hover:bg-slate-100">
                        <X className="h-4 w-4" /> 驳回
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ReviewQueuePage;
