"""Minimal vector index: markdown chunking + JSON cache + numpy cosine similarity.

Designed for small knowledge bases (a few MB). The entire index fits in a single
JSON file (~15-30 MB) and is loaded into memory on first query.

Architecture:
    docs/*.md  →  chunk by heading  →  embed via OpenAI-compatible API or local model
                                      →  persist to vector_cache.json
                                      →  numpy cosine search at query time

Embedding backends:
    - **remote** (default): OpenAI-compatible /embeddings endpoint
    - **local**: sentence-transformers models (e.g. BAAI/bge-small-zh-v1.5)
      loaded in-process, no external API required.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

# ---------------------------------------------------------------------------
# Offline mode — set BEFORE any huggingface_hub / sentence_transformers import
# so that the env vars are already in place when those libraries read them
# at their own import time.  This prevents network access when the model
# weights are shipped inside the repository.
# ---------------------------------------------------------------------------
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


# ---------------------------------------------------------------------------
# Local model cache (lazy-loaded singletons)
# ---------------------------------------------------------------------------

_LOCAL_MODEL_CACHE: dict[str, Any] = {}

# Default local embedding model (HuggingFace model name)
DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"

# Project-local model directory — checked first so the model travels with
# the repository and doesn't depend on the HuggingFace hub cache.
_LOCAL_MODEL_DIR = Path(__file__).resolve().parent / "models"


def _resolve_model_path(model_name: str) -> str:
    """Resolve a model name to a local directory when possible.

    Priority:
      1. ``knowledge/models/<basename>/`` inside the project (portable).
      2. The original *model_name* (HuggingFace hub id or absolute path).
    """
    basename = model_name.split("/")[-1]
    local_dir = _LOCAL_MODEL_DIR / basename
    if local_dir.is_dir() and (local_dir / "model.safetensors").exists():
        return str(local_dir)
    return model_name


def _get_local_model(model_name: str):
    """Lazily load and cache a sentence-transformers model.

    When a project-local copy exists under ``knowledge/models/<basename>/``,
    it is used directly — no HuggingFace Hub access required.  We also set
    ``HF_HUB_OFFLINE=1`` at import time so sentence-transformers does not
    attempt a network round-trip to check for updates.
    """
    if model_name not in _LOCAL_MODEL_CACHE:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for local embedding. "
                "Install it with: pip install sentence-transformers"
            )
        resolved = _resolve_model_path(model_name)
        logger.info("Loading local embedding model: {} (resolved: {}) ...", model_name, resolved)
        _LOCAL_MODEL_CACHE[model_name] = SentenceTransformer(resolved)
        _dim_fn = getattr(_LOCAL_MODEL_CACHE[model_name], "get_embedding_dimension", None) or _LOCAL_MODEL_CACHE[model_name].get_sentence_embedding_dimension
        logger.info("Local model '{}' loaded (dim={})", model_name, _dim_fn())
    return _LOCAL_MODEL_CACHE[model_name]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# Match markdown headings (## and ### level)
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

_DEFAULT_CHUNK_SIZE = 1200   # target tokens per chunk
_DEFAULT_OVERLAP = 100       # overlap tokens between chunks


@dataclass
class Chunk:
    """A single text chunk with provenance metadata."""

    text: str
    source: str           # relative path from docs_root (e.g. "web-security/xss.md")
    heading: str          # nearest heading above the chunk (or "")
    chunk_id: int         # sequential ID within the source file
    embedding: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "heading": self.heading,
            "chunk_id": self.chunk_id,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Chunk":
        return cls(
            text=d["text"],
            source=d["source"],
            heading=d.get("heading", ""),
            chunk_id=d["chunk_id"],
            embedding=d.get("embedding", []),
        )


def _split_by_heading(text: str) -> list[tuple[str, str]]:
    """Split markdown text by headings, returning [(heading, body), ...].

    Text before the first heading is grouped under an empty heading "".
    """
    parts: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        m = _HEADING_RE.match(line)
        if m:
            # Flush previous section
            if current_lines:
                parts.append((current_heading, "".join(current_lines)))
            current_heading = m.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        parts.append((current_heading, "".join(current_lines)))

    return parts


def chunk_markdown(
    text: str,
    source: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split a markdown document into overlapping chunks, respecting heading boundaries.

    Each chunk carries its nearest heading as metadata for better retrieval context.
    Chunk size is measured in *characters* (≈ 0.5 tokens for CJK, ≈ 0.25 for English).
    """
    sections = _split_by_heading(text)
    chunks: list[Chunk] = []
    chunk_id = 0

    for heading, body in sections:
        if not body.strip():
            continue

        # Split large sections into sub-chunks
        step = max(chunk_size - overlap, 1)
        for start in range(0, len(body), step):
            end = min(start + chunk_size, len(body))
            fragment = body[start:end].strip()
            if not fragment:
                continue
            chunks.append(Chunk(
                text=fragment,
                source=source,
                heading=heading,
                chunk_id=chunk_id,
            ))
            chunk_id += 1
            if end >= len(body):
                break

    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


async def embed_texts(
    texts: list[str],
    *,
    api_key: str = "",
    base_url: str | None = None,
    model: str = "text-embedding-3-small",
    batch_size: int = 100,
    local: bool = False,
) -> list[list[float]]:
    """Generate embeddings for a list of texts.

    When *local* is True, uses a local sentence-transformers model (no API call).
    Otherwise calls the OpenAI-compatible /embeddings endpoint in batches.

    Returns a flat list of embedding vectors (same order as *texts*).
    Falls back gracefully on errors: failed batches yield zero-vectors.
    """
    if local:
        return _embed_texts_local(texts, model=model, batch_size=batch_size)

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    all_embeddings: list[list[float]] = []
    # Detect dimension from first successful response
    dim = 1536  # default fallback

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            resp = await client.embeddings.create(
                model=model,
                input=batch,
            )
            batch_embs = [item.embedding for item in resp.data]
            if batch_embs:
                dim = len(batch_embs[0])
            all_embeddings.extend(batch_embs)
        except Exception as exc:
            logger.warning(
                "Embedding batch {}/{} failed ({}), using zero-vectors",
                i // batch_size + 1,
                (len(texts) + batch_size - 1) // batch_size,
                exc,
            )
            all_embeddings.extend([[0.0] * dim for _ in batch])

    return all_embeddings


def _embed_texts_local(
    texts: list[str],
    *,
    model: str = DEFAULT_LOCAL_MODEL,
    batch_size: int = 100,
) -> list[list[float]]:
    """Generate embeddings using a local sentence-transformers model.

    The model is loaded lazily and cached in-process. No external API is called.
    """
    st_model = _get_local_model(model)
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            # sentence-transformers encode returns numpy array (N, dim)
            embeddings = st_model.encode(
                batch,
                normalize_embeddings=True,  # L2 normalize for cosine similarity
                show_progress_bar=False,
            )
            all_embeddings.extend(embeddings.tolist())
        except Exception as exc:
            logger.warning(
                "Local embedding batch {}/{} failed ({}), using zero-vectors",
                i // batch_size + 1,
                (len(texts) + batch_size - 1) // batch_size,
                exc,
            )
            _dim_fn = getattr(st_model, "get_embedding_dimension", None) or st_model.get_sentence_embedding_dimension
            dim = _dim_fn() or 512
            all_embeddings.extend([[0.0] * dim for _ in batch])

    return all_embeddings


# ---------------------------------------------------------------------------
# Vector Index
# ---------------------------------------------------------------------------


class SimpleVectorIndex:
    """In-memory vector index backed by a single JSON file.

    Lifecycle:
        1. ``build(docs_dir)`` — scan, chunk, embed, persist
        2. ``load()`` — read JSON into memory (called automatically on first search)
        3. ``search(query_emb)`` — numpy cosine similarity, return Top-K
    """

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None
        self._meta: dict[str, Any] = {}  # model, local, dim

    @property
    def is_loaded(self) -> bool:
        return self._matrix is not None

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def meta(self) -> dict[str, Any]:
        """Index metadata: model name, backend type, embedding dimension."""
        return dict(self._meta)

    @property
    def is_local(self) -> bool:
        """Whether the index was built with a local embedding model."""
        return self._meta.get("local", False)

    @property
    def embedding_dim(self) -> int:
        """Embedding dimension (detected from the first chunk or meta)."""
        if self._meta.get("dim"):
            return int(self._meta["dim"])
        if self._chunks and self._chunks[0].embedding:
            return len(self._chunks[0].embedding)
        return 0

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    async def build(
        self,
        docs_dir: Path,
        *,
        api_key: str = "",
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        overlap: int = _DEFAULT_OVERLAP,
        local: bool = False,
    ) -> int:
        """Scan docs_dir for .md files, chunk them, embed, and persist.

        When *local* is True, uses a local sentence-transformers model instead
        of calling an external API.

        Returns the total number of chunks indexed.
        """
        if not docs_dir.is_dir():
            raise FileNotFoundError(f"docs_dir not found: {docs_dir}")

        all_chunks: list[Chunk] = []
        for md_path in sorted(docs_dir.rglob("*.md")):
            rel = str(md_path.relative_to(docs_dir))
            text = md_path.read_text(encoding="utf-8")
            chunks = chunk_markdown(text, source=rel, chunk_size=chunk_size, overlap=overlap)
            all_chunks.extend(chunks)
            logger.info("Chunked {} → {} chunks", rel, len(chunks))

        if not all_chunks:
            logger.warning("No markdown files found under {}", docs_dir)
            return 0

        # Batch embed all chunks
        texts = [c.text for c in all_chunks]
        backend = "local" if local else "remote"
        logger.info("Embedding {} chunks via {} ({}, backend={}) ...", len(texts), model, backend, backend)
        embeddings = await embed_texts(
            texts, api_key=api_key, base_url=base_url, model=model, local=local,
        )

        for chunk, emb in zip(all_chunks, embeddings):
            chunk.embedding = emb

        self._chunks = all_chunks
        self._matrix = np.array([c.embedding for c in all_chunks], dtype=np.float32)
        # Record metadata so the query handler can use the same backend
        dim = len(all_chunks[0].embedding) if all_chunks else 0
        self._meta = {"model": model, "local": local, "dim": dim}
        self._save()

        logger.info(
            "Vector index built: {} chunks, cache at {}",
            len(all_chunks),
            self.cache_path,
        )
        return len(all_chunks)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """Cosine similarity search. Returns top-K chunks with scores."""
        if not self.is_loaded:
            self.load()

        if self._matrix is None or len(self._chunks) == 0:
            return []

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm < 1e-8:
            return []

        # Cosine similarity
        norms = np.linalg.norm(self._matrix, axis=1)
        scores = (self._matrix @ q) / (norms * q_norm + 1e-8)

        # Top-K
        k = min(top_k, len(self._chunks))
        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        results = []
        for idx in top_indices:
            chunk = self._chunks[idx]
            results.append({
                "text": chunk.text,
                "source": chunk.source,
                "heading": chunk.heading,
                "chunk_id": chunk.chunk_id,
                "score": float(scores[idx]),
            })
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Persist chunks + embeddings + metadata to a single JSON file.

        New format (v2):
            {"meta": {...}, "chunks": [...]}
        Old format (v1, backward-compatible on load):
            [...]  (bare list of chunks)
        """
        payload = {
            "meta": self._meta,
            "chunks": [c.to_dict() for c in self._chunks],
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    def load(self) -> None:
        """Load chunks + embeddings from JSON cache into memory.

        Supports both v1 (bare list) and v2 (dict with meta) formats.
        """
        if not self.cache_path.exists():
            logger.debug("Vector cache not found at {}, index is empty", self.cache_path)
            return

        raw = json.loads(self.cache_path.read_text(encoding="utf-8"))

        # v2 format: {"meta": {...}, "chunks": [...]}
        if isinstance(raw, dict):
            self._meta = raw.get("meta", {})
            chunk_list = raw.get("chunks", [])
        else:
            # v1 format: bare list of chunks
            self._meta = {}
            chunk_list = raw

        self._chunks = [Chunk.from_dict(d) for d in chunk_list]

        if self._chunks and self._chunks[0].embedding:
            self._matrix = np.array(
                [c.embedding for c in self._chunks], dtype=np.float32,
            )
        else:
            self._matrix = None

        logger.debug(
            "Loaded vector index: {} chunks (meta={}) from {}",
            len(self._chunks),
            self._meta,
            self.cache_path,
        )

    # ------------------------------------------------------------------
    # Incremental update helpers
    # ------------------------------------------------------------------

    def get_indexed_sources(self) -> set[str]:
        """Return the set of source files currently in the index."""
        return {c.source for c in self._chunks}

    async def rebuild(
        self,
        docs_dir: Path,
        *,
        api_key: str = "",
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        local: bool = False,
    ) -> int:
        """Full rebuild (delegates to build). Clears old cache first."""
        self._chunks = []
        self._matrix = None
        return await self.build(
            docs_dir, api_key=api_key, base_url=base_url, model=model, local=local,
        )
