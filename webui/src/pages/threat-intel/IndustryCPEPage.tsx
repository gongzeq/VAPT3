/**
 * Industry CPE Management Page — Gap Fix §2.
 *
 * Admin configuration for maritime/transport CPE entries.
 * Features: list, add, filter by industry_tag, delete.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2, Search } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchIndustryCPEs,
  addIndustryCPE,
  deleteIndustryCPE,
  type IndustryCPEEntry,
} from "@/lib/threat-intel-client";

export function IndustryCPEPage() {
  const { token } = useClient();
  const [items, setItems] = useState<IndustryCPEEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filterTag, setFilterTag] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCpe, setNewCpe] = useState({
    cpe_string: "",
    product_name: "",
    vendor: "",
    industry_tag: "maritime",
    confidence: 0.9,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchIndustryCPEs(token);
      setItems(result.items || []);
      setTotal(result.total || 0);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async () => {
    if (!newCpe.cpe_string || !newCpe.product_name) return;
    try {
      await addIndustryCPE(token, {
        cpe_string: newCpe.cpe_string,
        product_name: newCpe.product_name,
        vendor: newCpe.vendor || undefined,
        industry_tag: newCpe.industry_tag || undefined,
        confidence: newCpe.confidence,
      });
      setShowAddForm(false);
      setNewCpe({
        cpe_string: "",
        product_name: "",
        vendor: "",
        industry_tag: "maritime",
        confidence: 0.9,
      });
      load();
    } catch (e) {
      window.alert(`添加失败: ${(e as Error).message}`);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("确认删除此CPE条目？")) return;
    try {
      await deleteIndustryCPE(token, id);
      load();
    } catch (e) {
      window.alert(`删除失败: ${(e as Error).message}`);
    }
  };

  // Client-side filter
  const filtered = items.filter((item) => {
    if (filterTag && !item.industry_tag.includes(filterTag)) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        item.cpe_string.toLowerCase().includes(q) ||
        item.product_name.toLowerCase().includes(q) ||
        (item.vendor || "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">行业CPE管理</h1>
        <span className="text-sm text-slate-600">共 {total} 条</span>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={filterTag}
          onChange={(e) => setFilterTag(e.target.value)}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="">全部标签</option>
          <option value="maritime">maritime</option>
          <option value="transport">transport</option>
          <option value="scada">scada</option>
          <option value="port">port</option>
        </select>
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索CPE/产品/厂商..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-slate-200 py-2 pl-8 pr-3 text-sm"
          />
        </div>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3 py-2 text-sm text-white hover:bg-indigo-600"
        >
          <Plus className="h-4 w-4" />
          新增CPE
        </button>
      </div>

      {/* Add form */}
      {showAddForm && (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-700">新增行业CPE</h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="text-xs text-slate-500">CPE String *</label>
              <input
                type="text"
                value={newCpe.cpe_string}
                onChange={(e) => setNewCpe({ ...newCpe, cpe_string: e.target.value })}
                placeholder="cpe:2.3:a:vendor:product"
                className="mt-1 w-full rounded border border-slate-200 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500">产品名称 *</label>
              <input
                type="text"
                value={newCpe.product_name}
                onChange={(e) => setNewCpe({ ...newCpe, product_name: e.target.value })}
                placeholder="Product Name"
                className="mt-1 w-full rounded border border-slate-200 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500">厂商</label>
              <input
                type="text"
                value={newCpe.vendor}
                onChange={(e) => setNewCpe({ ...newCpe, vendor: e.target.value })}
                placeholder="Vendor"
                className="mt-1 w-full rounded border border-slate-200 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500">行业标签</label>
              <select
                value={newCpe.industry_tag}
                onChange={(e) => setNewCpe({ ...newCpe, industry_tag: e.target.value })}
                className="mt-1 w-full rounded border border-slate-200 px-3 py-1.5 text-sm"
              >
                <option value="maritime">maritime</option>
                <option value="transport">transport</option>
                <option value="scada">scada</option>
                <option value="port">port</option>
                <option value="maritime/scada">maritime/scada</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500">置信度</label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={newCpe.confidence}
                onChange={(e) => setNewCpe({ ...newCpe, confidence: parseFloat(e.target.value) || 0.9 })}
                className="mt-1 w-full rounded border border-slate-200 px-3 py-1.5 text-sm"
              />
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              onClick={handleAdd}
              disabled={!newCpe.cpe_string || !newCpe.product_name}
              className="rounded-lg bg-indigo-500 px-4 py-1.5 text-sm text-white hover:bg-indigo-600 disabled:opacity-40"
            >
              确认添加
            </button>
            <button
              onClick={() => setShowAddForm(false)}
              className="rounded-lg border border-slate-200 px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="text-slate-400">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="text-slate-400">暂无CPE条目</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-500">
                <th className="px-4 py-3 font-medium">CPE</th>
                <th className="px-4 py-3 font-medium">产品名称</th>
                <th className="px-4 py-3 font-medium">厂商</th>
                <th className="px-4 py-3 font-medium">行业标签</th>
                <th className="px-4 py-3 font-medium">置信度</th>
                <th className="px-4 py-3 font-medium">来源</th>
                <th className="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-700">{item.cpe_string}</td>
                  <td className="px-4 py-2.5 text-slate-700">{item.product_name}</td>
                  <td className="px-4 py-2.5 text-slate-500">{item.vendor || "—"}</td>
                  <td className="px-4 py-2.5">
                    <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      {item.industry_tag}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">{item.confidence.toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-slate-500">{item.source}</td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="inline-flex items-center gap-1 rounded text-red-500 hover:bg-red-50 px-2 py-1 text-xs"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default IndustryCPEPage;
