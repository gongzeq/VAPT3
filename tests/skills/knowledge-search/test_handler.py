"""Tests for the knowledge-search skill handler."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from secbot.skills.types import InvalidSkillArg, SkillContext
from tests.skills.test_handlers import load_handler

# Load handler via the shared utility (handles kebab-case → module import)
handler = load_handler("knowledge-search")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ctx() -> SkillContext:
    return SkillContext(
        scan_id="test-scan",
        scan_dir=Path("/tmp/test-scan"),
    )


_DOCS_DIR = Path(__file__).resolve().parents[3] / "secbot" / "knowledge" / "docs"


# ---------------------------------------------------------------------------
# Keyword search (_grep_search)
# ---------------------------------------------------------------------------


class TestGrepSearch:
    def test_finds_sql_injection(self):
        if not _DOCS_DIR.is_dir():
            pytest.skip("knowledge/docs/ not found")

        hits = handler._grep_search(_DOCS_DIR, "SQL 注入", top_k=5)
        assert len(hits) >= 1
        sources = {h["source"] for h in hits}
        assert any("sql-injection" in s for s in sources)

    def test_finds_xss(self):
        if not _DOCS_DIR.is_dir():
            pytest.skip("knowledge/docs/ not found")

        hits = handler._grep_search(_DOCS_DIR, "XSS 跨站脚本", top_k=5)
        assert len(hits) >= 1

    def test_source_filter(self):
        if not _DOCS_DIR.is_dir():
            pytest.skip("knowledge/docs/ not found")

        hits = handler._grep_search(_DOCS_DIR, "SQL", top_k=10, source_filter="methodologies")
        for h in hits:
            assert h["source"].startswith("methodologies")

    def test_empty_query(self):
        hits = handler._grep_search(Path("/nonexistent"), "", top_k=5)
        assert hits == []

    def test_nonexistent_dir(self):
        hits = handler._grep_search(Path("/nonexistent/path"), "test", top_k=5)
        assert hits == []


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------


class TestExtractTerms:
    def test_basic(self):
        terms = handler._extract_terms("SQL 注入绕过 WAF")
        assert "SQL" in terms
        assert "WAF" in terms

    def test_stopwords_removed(self):
        terms = handler._extract_terms("what is the XSS attack")
        for sw in ["what", "the"]:
            assert sw not in terms

    def test_short_tokens_removed(self):
        terms = handler._extract_terms("a b XSS")
        assert "a" not in terms
        assert "b" not in terms
        assert "XSS" in terms


# ---------------------------------------------------------------------------
# Merge results
# ---------------------------------------------------------------------------


class TestMergeResults:
    def test_deduplication(self):
        keyword = [
            {"source": "a.md", "heading": "H1", "text": "x", "score": 0.9},
            {"source": "b.md", "heading": "H2", "text": "y", "score": 0.8},
        ]
        vector = [
            {"source": "a.md", "heading": "H1", "text": "x", "score": 0.95},
            {"source": "c.md", "heading": "H3", "text": "z", "score": 0.7},
        ]
        merged = handler._merge_results(keyword, vector, top_k=5)
        assert len(merged) == 3
        sources = [m["source"] for m in merged]
        assert sources.count("a.md") == 1

    def test_top_k_cap(self):
        keyword = [{"source": f"a{i}.md", "heading": "", "text": "", "score": 0.5} for i in range(10)]
        merged = handler._merge_results(keyword, [], top_k=3)
        assert len(merged) == 3


# ---------------------------------------------------------------------------
# run() entry point
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_empty_query_raises(self):
        with pytest.raises(InvalidSkillArg):
            await handler.run({"query": ""}, _make_ctx())

    @pytest.mark.asyncio
    async def test_basic_search(self):
        result = await handler.run({"query": "SQL 注入"}, _make_ctx())
        assert result.summary["ok"] is True
        assert result.summary["action"] == "search"
        data = result.summary["data"]
        assert data["total_hits"] >= 0
        assert data["search_mode"] in ("keyword", "vector", "hybrid")

    @pytest.mark.asyncio
    async def test_top_k_respected(self):
        result = await handler.run({"query": "安全", "top_k": 2}, _make_ctx())
        assert len(result.summary["data"]["results"]) <= 2
