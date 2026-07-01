"""Tests for secbot.knowledge.vector_index."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from secbot.knowledge.vector_index import (
    Chunk,
    SimpleVectorIndex,
    _split_by_heading,
    chunk_markdown,
)


# ---------------------------------------------------------------------------
# chunk_markdown
# ---------------------------------------------------------------------------

SAMPLE_MD = """\
# Introduction

This is the intro paragraph.

## Section A

Content of section A with some important security knowledge.

### Subsection A1

Deeper content about SQL injection techniques.

## Section B

Content of section B about XSS attacks and prevention.
"""


class TestSplitByHeading:
    def test_basic_split(self):
        parts = _split_by_heading(SAMPLE_MD)
        headings = [h for h, _ in parts]
        assert "Introduction" in headings
        assert "Section A" in headings
        assert "Section B" in headings

    def test_preserves_body(self):
        parts = _split_by_heading(SAMPLE_MD)
        body_map = {h: b for h, b in parts}
        assert "SQL injection" in body_map.get("Subsection A1", "")

    def test_no_heading_text(self):
        text = "Just plain text without any headings."
        parts = _split_by_heading(text)
        assert len(parts) == 1
        assert parts[0][0] == ""  # empty heading
        assert "plain text" in parts[0][1]

    def test_empty_input(self):
        assert _split_by_heading("") == []


class TestChunkMarkdown:
    def test_basic_chunking(self):
        chunks = chunk_markdown(SAMPLE_MD, source="test.md", chunk_size=100, overlap=20)
        assert len(chunks) >= 1
        assert all(c.source == "test.md" for c in chunks)

    def test_heading_metadata(self):
        chunks = chunk_markdown(SAMPLE_MD, source="test.md", chunk_size=50, overlap=0)
        headings = {c.heading for c in chunks}
        # At least some chunks should carry heading info
        assert len(headings) >= 2

    def test_sequential_chunk_ids(self):
        chunks = chunk_markdown(SAMPLE_MD, source="test.md")
        ids = [c.chunk_id for c in chunks]
        assert ids == list(range(len(ids)))

    def test_empty_input(self):
        chunks = chunk_markdown("", source="empty.md")
        assert chunks == []


# ---------------------------------------------------------------------------
# Chunk serialization
# ---------------------------------------------------------------------------


class TestChunkSerialization:
    def test_roundtrip(self):
        c = Chunk(text="hello", source="a.md", heading="H1", chunk_id=3, embedding=[0.1, 0.2])
        d = c.to_dict()
        restored = Chunk.from_dict(d)
        assert restored.text == "hello"
        assert restored.source == "a.md"
        assert restored.heading == "H1"
        assert restored.chunk_id == 3
        assert restored.embedding == [0.1, 0.2]

    def test_from_dict_missing_heading(self):
        d = {"text": "x", "source": "b.md", "chunk_id": 0, "embedding": []}
        c = Chunk.from_dict(d)
        assert c.heading == ""


# ---------------------------------------------------------------------------
# SimpleVectorIndex
# ---------------------------------------------------------------------------


class TestSimpleVectorIndex:
    def _make_index(self, tmp_path: Path, n_chunks: int = 5, dim: int = 8) -> SimpleVectorIndex:
        """Build an in-memory index with random embeddings for testing."""
        cache = tmp_path / "vector_cache.json"
        idx = SimpleVectorIndex(cache)
        rng = np.random.default_rng(42)
        chunks = []
        for i in range(n_chunks):
            emb = rng.random(dim).tolist()
            chunks.append(Chunk(
                text=f"Chunk {i} about security topic {i}",
                source=f"doc-{i % 2}.md",
                heading=f"Heading {i}",
                chunk_id=i,
                embedding=emb,
            ))
        idx._chunks = chunks
        idx._matrix = np.array([c.embedding for c in chunks], dtype=np.float32)
        return idx

    def test_search_returns_top_k(self, tmp_path: Path):
        idx = self._make_index(tmp_path, n_chunks=10)
        # Query: use the embedding of chunk 0 (should rank highest)
        query = idx._chunks[0].embedding
        results = idx.search(query, top_k=3)
        assert len(results) == 3
        # Top result should be chunk 0 itself (exact match)
        assert results[0]["chunk_id"] == 0
        assert results[0]["score"] > 0.99  # near-perfect cosine match

    def test_search_empty_index(self, tmp_path: Path):
        idx = SimpleVectorIndex(tmp_path / "empty.json")
        results = idx.search([0.1, 0.2, 0.3])
        assert results == []

    def test_search_zero_vector(self, tmp_path: Path):
        idx = self._make_index(tmp_path)
        results = idx.search([0.0] * 8)
        assert results == []

    def test_save_and_load(self, tmp_path: Path):
        idx = self._make_index(tmp_path, n_chunks=5, dim=8)
        idx._save()

        # Load into fresh instance
        idx2 = SimpleVectorIndex(idx.cache_path)
        idx2.load()
        assert idx2.chunk_count == 5
        assert idx2.is_loaded

        # Search should produce same results
        query = idx._chunks[2].embedding
        r1 = idx.search(query, top_k=2)
        r2 = idx2.search(query, top_k=2)
        assert r1[0]["chunk_id"] == r2[0]["chunk_id"]

    def test_load_missing_cache(self, tmp_path: Path):
        idx = SimpleVectorIndex(tmp_path / "nonexistent.json")
        idx.load()
        assert idx.chunk_count == 0
        assert not idx.is_loaded

    def test_get_indexed_sources(self, tmp_path: Path):
        idx = self._make_index(tmp_path, n_chunks=6)
        sources = idx.get_indexed_sources()
        assert sources == {"doc-0.md", "doc-1.md"}

    def test_cache_file_format(self, tmp_path: Path):
        """Verify JSON cache is a list of chunk dicts."""
        idx = self._make_index(tmp_path, n_chunks=3, dim=4)
        idx._save()
        raw = json.loads(idx.cache_path.read_text())
        assert isinstance(raw, list)
        assert len(raw) == 3
        assert "text" in raw[0]
        assert "embedding" in raw[0]

    def test_top_k_larger_than_index(self, tmp_path: Path):
        idx = self._make_index(tmp_path, n_chunks=3)
        results = idx.search([0.5] * 8, top_k=100)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# build() with mocked embedding
# ---------------------------------------------------------------------------


class TestBuild:
    @pytest.mark.asyncio
    async def test_build_scans_and_embeds(self, tmp_path: Path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "test.md").write_text("## XSS\n\nCross-site scripting is dangerous.")

        cache = tmp_path / "vector_cache.json"
        idx = SimpleVectorIndex(cache)

        fake_embeddings = [[0.1] * 8, [0.2] * 8]  # 2 chunks max from this small doc

        with patch(
            "secbot.knowledge.vector_index.embed_texts",
            new_callable=AsyncMock,
            return_value=fake_embeddings,
        ):
            count = await idx.build(
                docs, api_key="test-key", model="test-model",
                chunk_size=200, overlap=0,
            )

        assert count >= 1
        assert cache.exists()
        assert idx.is_loaded

    @pytest.mark.asyncio
    async def test_build_empty_dir(self, tmp_path: Path):
        docs = tmp_path / "empty_docs"
        docs.mkdir()

        cache = tmp_path / "vector_cache.json"
        idx = SimpleVectorIndex(cache)

        count = await idx.build(docs, api_key="test-key")
        assert count == 0
