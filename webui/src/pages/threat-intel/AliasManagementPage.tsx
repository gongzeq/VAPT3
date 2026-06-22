/**
 * APT Alias Management Page — PRD §7.2 APT别名管理.
 */

import { useCallback, useEffect, useState } from "react";
import { Upload, Plus } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchAptAliases, addAptAlias, batchImportAliases, type AptAliasFull } from "@/lib/threat-intel-client";

export function AliasManagementPage() {
  const { token } = useClient();
  const [aliases, setAliases] = useState<AptAliasFull[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchAptAliases(token);
      setAliases(result.items);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const filtered = aliases.filter((a) =>
    !filter || a.alias_name.toLowerCase().includes(filter.toLowerCase()) ||
    (a.naming_org && a.naming_org.toLowerCase().includes(filter.toLowerCase()))
  );

  const handleBatchImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const lines = text.split("\n").filter((l) => l.trim());
    const entries = lines.slice(1).map((line) => {
      const [alias_name, naming_org, mitre_id, confidence] = line.split(",").map((s) => s.trim());
      return { alias_name, naming_org, mitre_id, confidence: confidence ? parseFloat(confidence) : 0.8 };
    });
    const result = await batchImportAliases(token, entries);
    alert(`导入完成: 新增 ${result.inserted}, 更新 ${result.updated}, 失败 ${result.failed}`);
    load();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">APT别名映射管理</h1>
        <div className="flex gap-2">
          <label className="flex cursor-pointer items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-sm hover:bg-slate-200">
            <Upload className="h-4 w-4" /> 批量导入CSV
            <input type="file" accept=".csv" className="hidden" onChange={handleBatchImport} />
          </label>
          <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1 rounded-lg bg-indigo-500 px-3 py-1.5 text-sm text-white hover:bg-indigo-600">
            <Plus className="h-4 w-4" /> 新增别名
          </button>
        </div>
      </div>

      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="搜索别名或命名机构..."
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
      />

      {showAdd && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            await addAptAlias(token, {
              alias_name: form.get("alias_name") as string,
              naming_org: form.get("naming_org") as string || undefined,
              group_id: form.get("group_id") as string || undefined,
              confidence: parseFloat(form.get("confidence") as string) || 0.8,
            });
            setShowAdd(false);
            load();
          }}
          className="rounded-lg border border-slate-200 bg-white p-4"
        >
          <div className="grid grid-cols-2 gap-3">
            <input name="alias_name" placeholder="别名 *" required className="rounded border px-3 py-1.5 text-sm" />
            <input name="naming_org" placeholder="命名机构" className="rounded border px-3 py-1.5 text-sm" />
            <input name="group_id" placeholder="组织ID" className="rounded border px-3 py-1.5 text-sm" />
            <input name="confidence" type="number" step="0.05" defaultValue="0.8" placeholder="置信度" className="rounded border px-3 py-1.5 text-sm" />
          </div>
          <button type="submit" className="mt-3 rounded-lg bg-indigo-500 px-4 py-1.5 text-sm text-white">保存</button>
        </form>
      )}

      {loading ? (
        <div className="text-slate-400">加载中...</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-2 text-left">别名</th>
                <th className="px-4 py-2 text-left">命名机构</th>
                <th className="px-4 py-2 text-left">组织ID</th>
                <th className="px-4 py-2 text-left">置信度</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id} className="border-b border-slate-100">
                  <td className="px-4 py-2 font-medium">{a.alias_name}</td>
                  <td className="px-4 py-2">{a.naming_org ?? "—"}</td>
                  <td className="px-4 py-2 font-mono text-xs">{a.group_id ?? "—"}</td>
                  <td className="px-4 py-2">{a.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default AliasManagementPage;
