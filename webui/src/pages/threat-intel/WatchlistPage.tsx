/**
 * Watchlist Management Page — PRD §7.2 关注组织管理.
 */

import { useCallback, useEffect, useState } from "react";
import { StarOff } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchGroups, unwatchGroup, watchGroup, type ThreatGroupSummary } from "@/lib/threat-intel-client";

export function WatchlistPage() {
  const { token } = useClient();
  const [groups, setGroups] = useState<ThreatGroupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchGroups(token, { watched: true, page_size: 100 });
      setGroups(result.items);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const handleUnwatch = async (groupId: string) => {
    await unwatchGroup(token, groupId);
    setGroups((prev) => prev.filter((g) => g.id !== groupId));
  };

  const handleUpdateNote = async (groupId: string, note: string) => {
    await watchGroup(token, groupId, note);
  };

  const filtered = groups.filter((g) =>
    !filter || g.name.toLowerCase().includes(filter.toLowerCase()) ||
    (g.aliases && g.aliases.some((a) => a.toLowerCase().includes(filter.toLowerCase())))
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">关注组织管理</h1>
        <span className="text-sm text-slate-600">共 {groups.length} 个组织</span>
      </div>

      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="搜索组织名称或别名..."
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
      />

      {loading ? (
        <div className="text-slate-400">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="text-slate-400">尚无关注组织</div>
      ) : (
        <div className="space-y-2">
          {filtered.map((g) => (
            <div key={g.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-slate-900">{g.name}</span>
                  {g.aliases && g.aliases.length > 0 && (
                    <span className="ml-2 text-sm text-slate-500">别名: {g.aliases.join(", ")}</span>
                  )}
                </div>
                <button
                  onClick={() => handleUnwatch(g.id)}
                  className="flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1 text-sm text-red-600 hover:bg-red-100"
                >
                  <StarOff className="h-4 w-4" /> 移除
                </button>
              </div>
              <input
                defaultValue=""
                placeholder="添加备注..."
                onBlur={(e) => { if (e.target.value) handleUpdateNote(g.id, e.target.value); }}
                className="mt-2 w-full rounded border border-slate-100 px-2 py-1 text-sm"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default WatchlistPage;
