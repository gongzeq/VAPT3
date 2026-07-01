#!/usr/bin/env python3
"""Test knowledge search: keyword (string match) + vector (semantic) retrieval.

Usage:
    python scripts/test_knowledge_search.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# The skill directory uses a hyphen in its name ("knowledge-search") which
# cannot be imported as a normal Python package. Load the handler module
# directly via importlib, mirroring how secbot/agent/tools/skill.py does it.
_HANDLER_PATH = PROJECT_ROOT / "secbot" / "skills" / "knowledge-search" / "handler.py"
_spec = importlib.util.spec_from_file_location("kb_handler", _HANDLER_PATH)
_kb_module = importlib.util.module_from_spec(_spec)
spec_loader = _spec.loader
assert spec_loader is not None
spec_loader.exec_module(_kb_module)

_grep_search = _kb_module._grep_search
_vector_search = _kb_module._vector_search
_merge_results = _kb_module._merge_results
run = _kb_module.run

from secbot.skills.types import SkillContext, SkillResult
from secbot.knowledge.vector_index import SimpleVectorIndex, embed_texts, DEFAULT_LOCAL_MODEL

DOCS_DIR = PROJECT_ROOT / "secbot" / "knowledge" / "docs"
VECTOR_CACHE = PROJECT_ROOT / "secbot" / "knowledge" / "vector_cache.json"

# ── Helpers ──────────────────────────────────────────────────────────────

def print_section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

def print_results(results: list[dict], mode: str) -> None:
    if not results:
        print(f"  [{mode}] ❌ 无结果")
        return
    print(f"  [{mode}] ✅ 命中 {len(results)} 条:")
    for i, r in enumerate(results, 1):
        source = r.get("source", "?")
        heading = r.get("heading", "")
        score = r.get("score", 0.0)
        match_type = r.get("match_type", mode)
        hit_count = r.get("hit_count", "")
        text_preview = r.get("text", "")[:120].replace("\n", " ")
        print(f"    {i}. [{match_type}] source={source} | heading={heading} | score={score:.4f} | hits={hit_count}")
        print(f"       text: {text_preview}...")
    print()


# ── Test 1: Keyword (string match) search ────────────────────────────────

def test_keyword_search() -> None:
    print_section("测试1: 字符串匹配 (Keyword Search)")

    test_queries = [
        "SQL 注入",
        "XSS 跨站脚本",
        "渗透测试方法论",
        "信息收集",
        "网络安全法",
    ]

    for q in test_queries:
        print(f"  查询: \"{q}\"")
        t0 = time.monotonic()
        hits = _grep_search(DOCS_DIR, q, top_k=3)
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  耗时: {elapsed:.1f}ms | 命中: {len(hits)} 条")
        print_results(hits, "keyword")
        print("-" * 50)


# ── Test 2: Vector (semantic) search ─────────────────────────────────────

async def test_vector_search() -> None:
    print_section("测试2: 向量语义检索 (Vector Search)")

    # Use paraphrase / synonym queries that keyword search might miss
    test_queries = [
        "数据库注入攻击怎么防御",
        "网页脚本劫持用户cookie",
        "pentest recon methodology",
        "个人信息保护相关法律条文",
        "WAF绕过技术",
    ]

    for q in test_queries:
        print(f"  查询: \"{q}\"")
        t0 = time.monotonic()
        hits = await _vector_search(q, top_k=3)
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  耗时: {elapsed:.1f}ms | 命中: {len(hits)} 条")
        print_results(hits, "vector")
        print("-" * 50)


# ── Test 3: Full handler (hybrid: keyword + vector) ──────────────────────

async def test_full_handler() -> None:
    print_section("测试3: 完整 Handler (Hybrid: keyword + vector)")

    test_cases = [
        {"query": "什么是SQL注入", "top_k": 5},
        {"query": "XSS攻击的防御方法", "top_k": 5},
        {"query": "如何进行Web渗透测试", "top_k": 5},
        {"query": "数据安全法有哪些规定", "top_k": 3, "source_filter": "regulations"},
    ]

    from pathlib import Path as _P
    ctx = SkillContext(scan_id="test-scan", scan_dir=_P("/tmp/secbot-test"))

    for tc in test_cases:
        print(f"  查询: {tc}")
        t0 = time.monotonic()
        result: SkillResult = await run(tc, ctx)
        elapsed = (time.monotonic() - t0) * 1000

        summary = result.summary
        data = summary.get("data", {})
        results = data.get("results", [])
        search_mode = data.get("search_mode", "?")
        total_hits = data.get("total_hits", 0)
        elapsed_ms = summary.get("elapsed_ms", 0)

        print(f"  耗时: {elapsed:.1f}ms (handler报告: {elapsed_ms}ms)")
        print(f"  搜索模式: {search_mode} | 总命中: {total_hits}")
        print_results(results, search_mode)
        print("-" * 50)


# ── Test 4: Edge cases ──────────────────────────────────────────────────

async def test_edge_cases() -> None:
    print_section("测试4: 边界情况")

    from pathlib import Path as _P
    ctx = SkillContext(scan_id="test-scan", scan_dir=_P("/tmp/secbot-test"))

    # Empty query → should raise InvalidSkillArg
    print("  [4a] 空查询 (应报错)")
    try:
        await run({"query": ""}, ctx)
        print("  ❌ 未报错")
    except Exception as e:
        print(f"  ✅ 正确报错: {type(e).__name__}: {e}")
    print()

    # Non-existent topic
    print("  [4b] 不存在的主题: '量子计算加密'")
    result = await run({"query": "量子计算加密", "top_k": 3}, ctx)
    data = result.summary.get("data", {})
    print(f"  搜索模式: {data.get('search_mode')} | 命中: {data.get('total_hits')}")
    if data.get("results"):
        for r in data["results"]:
            print(f"    - {r['source']} | score={r.get('score', 0):.4f} | type={r.get('match_type')}")
    else:
        print("  ✅ 无结果（符合预期）")
    print()

    # Source filter test
    print("  [4c] source_filter='web-security' 查询 '注入'")
    result = await run({"query": "注入", "top_k": 3, "source_filter": "web-security"}, ctx)
    data = result.summary.get("data", {})
    results = data.get("results", [])
    all_web = all(r["source"].startswith("web-security") for r in results)
    print(f"  搜索模式: {data.get('search_mode')} | 命中: {len(results)}")
    print(f"  所有结果均来自 web-security: {'✅' if all_web else '❌'}")
    for r in results:
        print(f"    - {r['source']} | heading={r.get('heading', '')}")
    print()


# ── Main ─────────────────────────────────────────────────────────────────

async def main() -> None:
    print_section("网络安全知识库检索测试")
    print(f"  文档目录: {DOCS_DIR}")
    print(f"  向量缓存: {VECTOR_CACHE} ({VECTOR_CACHE.stat().st_size / 1024 / 1024:.1f} MB)")

    # Verify vector index loads
    idx = SimpleVectorIndex(VECTOR_CACHE)
    idx.load()
    print(f"  向量索引: {idx.chunk_count} chunks | dim={idx.embedding_dim} | local={idx.is_local}")
    print(f"  模型: {idx.meta.get('model', '?')}")

    test_keyword_search()
    await test_vector_search()
    await test_full_handler()
    await test_edge_cases()

    print_section("测试完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
