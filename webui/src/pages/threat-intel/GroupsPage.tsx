/**
 * Threat Intel Groups List Page — PRD §7.2 威胁组织列表页.
 *
 * Search + Watchlist filter + card grid.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search, Star, StarOff, ChevronLeft, ChevronRight } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchGroups,
  watchGroup,
  unwatchGroup,
  type ThreatGroupSummary,
} from "@/lib/threat-intel-client";
import { cn } from "@/lib/utils";

export function GroupsPage() {
  const { token } = useClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [groups, setGroups] = useState<ThreatGroupSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const q = searchParams.get("q") ?? "";
  const watched = searchParams.get("watched") === "true";
  const page = parseInt(searchParams.get("page") ?? "1", 10);

  const loadGroups = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchGroups(token, {
        q: q || undefined,
        watched: watched || undefined,
        page,
        page_size: 20,
      });
      setGroups(result.items);
      setTotal(result.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, q, watched, page]);

  useEffect(() => { loadGroups(); }, [loadGroups]);

  const handleSearch = (value: string) => {
    const params = new URLSearchParams(searchParams);
    if (value) params.set("q", value);
    else params.delete("q");
    params.delete("page");
    setSearchParams(params);
  };

  const toggleWatched = () => {
    const params = new URLSearchParams(searchParams);
    if (watched) params.delete("watched");
    else params.set("watched", "true");
    params.delete("page");
    setSearchParams(params);
  };

  const handleToggleWatch = async (e: React.MouseEvent, groupId: string, isWatched: boolean) => {
    e.stopPropagation();
    try {
      if (isWatched) {
        await unwatchGroup(token, groupId);
      } else {
        await watchGroup(token, groupId);
      }
      loadGroups();
    } catch (err) {
      window.alert(`操作失败: ${(err as Error).message}`);
    }
  };

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="space-y-4">
      {/* Header + Search */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-900">威胁组织</h1>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="搜索组织名称 / 别名…"
              value={q}
              onChange={(e) => handleSearch(e.target.value)}
              className="h-9 w-64 rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-700 placeholder:text-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <button
            type="button"
            onClick={toggleWatched}
            className={cn(
              "flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm transition-colors",
              watched
                ? "border-amber-300 bg-amber-50 text-amber-700"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
            )}
          >
            {watched ? <Star className="h-4 w-4 fill-amber-400 text-amber-400" /> : <StarOff className="h-4 w-4" />}
            {watched ? "已关注" : "全部"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex h-40 items-center justify-center text-sm text-slate-400">
          加载中…
        </div>
      )}

      {/* Group Cards */}
      {!loading && !error && (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {groups.map((g) => (
              <div
                key={g.id}
                onClick={() => navigate(`/threat-intel/groups/${g.id}`)}
                className="cursor-pointer rounded-xl border border-slate-200 bg-white p-4 transition-all hover:border-indigo-300 hover:shadow-md"
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") navigate(`/threat-intel/groups/${g.id}`); }}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="font-semibold text-slate-900">{g.name}</h3>
                    {g.aliases.length > 0 && (
                      <p className="mt-0.5 text-xs text-slate-500">
                        {g.aliases.slice(0, 3).join(" · ")}
                        {g.aliases.length > 3 && ` +${g.aliases.length - 3}`}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={(e) => handleToggleWatch(e, g.id, g.is_watched)}
                    className="shrink-0 rounded-md p-1 transition-colors hover:bg-slate-100"
                    aria-label={g.is_watched ? "取消关注" : "关注"}
                  >
                    {g.is_watched ? (
                      <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
                    ) : (
                      <StarOff className="h-4 w-4 text-slate-300" />
                    )}
                  </button>
                </div>
                {g.description && (
                  <p className="mt-2 line-clamp-2 text-xs text-slate-500">{g.description}</p>
                )}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {g.mitre_id && (
                    <span className="rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
                      {g.mitre_id}
                    </span>
                  )}
                  {g.origin_country && (
                    <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      {g.origin_country}
                    </span>
                  )}
                  {g.target_sectors.slice(0, 2).map((s) => (
                    <span key={s} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Empty state */}
          {groups.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400">
              <p className="text-sm">暂无威胁组织数据</p>
              <p className="mt-1 text-xs">请先执行 Feed 拉取或等待定时任务</p>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => {
                  const params = new URLSearchParams(searchParams);
                  params.set("page", String(page - 1));
                  setSearchParams(params);
                }}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="text-sm text-slate-500">
                {page} / {totalPages}
              </span>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => {
                  const params = new URLSearchParams(searchParams);
                  params.set("page", String(page + 1));
                  setSearchParams(params);
                }}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 disabled:opacity-40"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default GroupsPage;
