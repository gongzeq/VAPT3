"""knowledge-search handler: grep + vector fallback for secbot knowledge base.

Searches ``secbot/knowledge/docs/`` using keyword matching (Python ``re``) as
the primary strategy, with an optional vector-index fallback when keyword hits
are insufficient and a pre-built ``vector_cache.json`` exists.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DOCS_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "docs"
_VECTOR_CACHE = Path(__file__).resolve().parents[2] / "knowledge" / "vector_cache.json"

# ---------------------------------------------------------------------------
# Keyword search
# ---------------------------------------------------------------------------

# Characters that break regex syntax — escaped before compilation
_REGEX_UNSAFE = re.compile(r"[\\^$.*+?{}\[\]()|]")


def _safe_pattern(term: str) -> str:
    """Escape a user-supplied term for use as a regex literal."""
    return _REGEX_UNSAFE.sub(r"\\\g<0>", term)


def _extract_terms(query: str) -> list[str]:
    """Split a natural-language query into searchable keywords.

    Handles Chinese question patterns (strips prefixes like “什么是”) and
    CJK-Latin boundaries (splits “防御SQL注入” → “防御” + “SQL注入”).
    """
    # Remove code-fence markers and backticks
    cleaned = query.replace("`", "").strip()

    # Strip common Chinese question prefixes (longest-match first)
    _CN_PREFIXES = [
        "什么是", "什么叫", "解释一下", "介绍一下", "讲解一下",
        "请解释", "请介绍", "请讲解", "解释", "讲解", "了解",
        "学习", "如何", "怎样", "怎么", "为什么", "请问",
    ]
    for prefix in sorted(_CN_PREFIXES, key=len, reverse=True):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    cleaned = cleaned.strip()

    # Split on whitespace
    raw = cleaned.split()

    # Also split on CJK↔Latin boundaries so terms like “防御SQL注入”
    # become “防御” + “SQL注入”. Uses zero-width assertions at the
    # transition between CJK (\u4e00-\u9fff) and non-CJK characters.
    _CJK_BOUNDARY = re.compile(
        r"(?<=[\u4e00-\u9fff])(?=[^\u4e00-\u9fff])"
        r"|(?<=[^\u4e00-\u9fff])(?=[\u4e00-\u9fff])"
    )
    split_terms: list[str] = []
    for t in raw:
        parts = _CJK_BOUNDARY.split(t)
        split_terms.extend(p for p in parts if p)
    raw = split_terms

    terms: list[str] = []
    _STOP = frozenset({"的", "了", "在", "是", "和", "与", "或", "怎么", "如何",
                       "什么", "为什么", "the", "a", "an", "is", "are", "how",
                       "what", "why", "in", "on", "of", "and", "or", "to", "for"})
    for t in raw:
        t = t.strip(".,;:!?\"'()")
        if len(t) < 2 or t.lower() in _STOP:
            continue
        terms.append(t)
    return terms


def _grep_search(
    docs_dir: Path,
    query: str,
    *,
    top_k: int = 5,
    source_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Scan all .md files under docs_dir for keyword matches.

    Returns a list of result dicts sorted by relevance (hit count per section).
    """
    if not docs_dir.is_dir():
        return []

    terms = _extract_terms(query)
    if not terms:
        # Fall back to using the raw query as a single term
        terms = [query.strip()] if query.strip() else []
    if not terms:
        return []

    # Build a combined regex (case-insensitive, OR-joined)
    patterns = [_safe_pattern(t) for t in terms]
    combined = re.compile("|".join(patterns), re.IGNORECASE)

    # Collect per-section hits
    hits: list[dict[str, Any]] = []

    for md_path in sorted(docs_dir.rglob("*.md")):
        rel = str(md_path.relative_to(docs_dir))
        if source_filter and not rel.startswith(source_filter):
            continue

        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        current_heading = ""
        section_lines: list[str] = []
        section_start = 0

        def _flush() -> None:
            body = "\n".join(section_lines)
            if not body.strip():
                return
            matches = combined.findall(body)
            if matches:
                score = len(matches) / max(len(body.split()), 1) * 100
                hits.append({
                    "text": body[:2000],  # cap to avoid context bloat
                    "source": rel,
                    "heading": current_heading,
                    "line": section_start + 1,
                    "score": round(min(score, 1.0), 4),
                    "match_type": "keyword",
                    "hit_count": len(matches),
                })

        for i, line in enumerate(lines):
            heading_m = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading_m:
                _flush()
                current_heading = heading_m.group(2).strip()
                section_lines = [line]
                section_start = i
            else:
                section_lines.append(line)

        _flush()  # last section

    # Sort by hit_count descending, then score descending
    hits.sort(key=lambda h: (h["hit_count"], h["score"]), reverse=True)
    return hits[:top_k]


# ---------------------------------------------------------------------------
# Vector fallback
# ---------------------------------------------------------------------------


async def _vector_search(
    query: str,
    *,
    top_k: int = 5,
    source_filter: str | None = None,
    cache_path: Path = _VECTOR_CACHE,
) -> list[dict[str, Any]]:
    """Semantic similarity search using the pre-built vector index.

    Returns empty list when the cache doesn't exist or embedding API fails.
    """
    if not cache_path.exists():
        logger.debug("Vector cache not found at {}, skipping vector search", cache_path)
        return []

    from secbot.knowledge.vector_index import SimpleVectorIndex

    idx = SimpleVectorIndex(cache_path)
    idx.load()

    if not idx.is_loaded:
        return []

    # We need an embedding for the query — use the same backend that built the index
    try:
        from secbot.knowledge.vector_index import embed_texts

        use_local = idx.is_local
        model_name = idx.meta.get("model", "text-embedding-3-small")

        if use_local:
            # Local embedding: no API key needed
            logger.debug("Using local embedding for query (model={})", model_name)
            query_embs = await embed_texts(
                [query],
                model=model_name,
                local=True,
            )
        else:
            # Remote API embedding
            from secbot.config.schema import Config
            cfg = Config.load()
            provider = cfg.llm.get_provider()
            if not provider or not provider.api_key:
                logger.debug("No API key available for query embedding, skipping vector search")
                return []

            query_embs = await embed_texts(
                [query],
                api_key=provider.api_key,
                base_url=provider.api_base,
                model=model_name,
            )

        if not query_embs or all(v == 0.0 for v in query_embs[0]):
            return []

        results = idx.search(query_embs[0], top_k=top_k * 2)

        # Apply source filter
        if source_filter:
            results = [r for r in results if r["source"].startswith(source_filter)]

        # Add match_type and cap
        for r in results[:top_k]:
            r["match_type"] = "vector"
            r.pop("chunk_id", None)

        return results[:top_k]

    except Exception as exc:
        logger.warning("Vector search failed: {}", exc)
        return []


# ---------------------------------------------------------------------------
# Merge & deduplicate
# ---------------------------------------------------------------------------


def _merge_results(
    keyword_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Merge keyword and vector results, deduplicating by (source, heading)."""
    seen: set[tuple[str, str]] = set()
    merged: list[dict[str, Any]] = []

    # Keyword hits first (higher confidence)
    for hit in keyword_hits:
        key = (hit["source"], hit.get("heading", ""))
        if key not in seen:
            seen.add(key)
            merged.append(hit)

    # Then vector hits
    for hit in vector_hits:
        key = (hit["source"], hit.get("heading", ""))
        if key not in seen:
            seen.add(key)
            merged.append(hit)

    return merged[:top_k]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Search the knowledge base: keyword first, vector fallback."""
    query = str(args.get("query", "")).strip()
    if not query:
        raise InvalidSkillArg("'query' is required and must be non-empty")

    top_k = int(args.get("top_k", 5))
    top_k = max(1, min(top_k, 20))

    source_filter = args.get("source_filter")
    if source_filter:
        source_filter = str(source_filter).strip() or None

    t0 = time.monotonic()

    # Phase 1: keyword search
    keyword_hits = _grep_search(
        _DOCS_DIR, query, top_k=top_k, source_filter=source_filter,
    )

    search_mode = "keyword"
    results = keyword_hits

    # Phase 2: vector fallback if keyword hits < top_k
    if len(keyword_hits) < top_k:
        vector_hits = await _vector_search(
            query, top_k=top_k, source_filter=source_filter,
        )
        if vector_hits:
            results = _merge_results(keyword_hits, vector_hits, top_k)
            search_mode = "hybrid" if keyword_hits else "vector"

    elapsed = int((time.monotonic() - t0) * 1000)

    # Clean up internal fields from results
    clean_results = []
    for r in results:
        clean_results.append({
            "text": r["text"],
            "source": r["source"],
            "heading": r.get("heading", ""),
            "score": r.get("score", 0.0),
            "match_type": r.get("match_type", "keyword"),
        })

    summary = {
        "action": "search",
        "ok": True,
        "data": {
            "query": query,
            "results": clean_results,
            "total_hits": len(clean_results),
            "search_mode": search_mode,
        },
        "elapsed_ms": elapsed,
    }

    return SkillResult(summary=summary)
