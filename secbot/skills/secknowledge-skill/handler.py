"""Low-risk lookup handler for the bundled secknowledge reference corpus."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult

_MAX_EXCERPT_CHARS = 520
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}", re.UNICODE)

_CATEGORY_FILES = {
    "methodology": (
        "testing-methodology.md",
        "gaarm-risk-matrix.md",
    ),
    "web": (
        "web-injection.md",
        "web-logic-auth.md",
        "web-file-infra.md",
        "web-modern-protocols.md",
        "web-deployment-security.md",
    ),
    "ai": (
        "ai-app-security.md",
        "ai-model-security.md",
        "ai-data-security.md",
        "ai-identity-security.md",
        "ai-baseline-security.md",
    ),
    "payloads": ("payloads.md",),
}

_AUTO_HINTS = {
    "ai": ("prompt", "llm", "mcp", "rag", "agent", "model", "jailbreak", "越狱", "注入", "模型"),
    "payloads": ("payload", "poc", "绕过", "反弹", "shell", "bypass"),
    "methodology": ("methodology", "owasp", "gaarm", "wstg", "方法论", "风险", "矩阵"),
}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    del ctx
    query = str(args.get("query", "")).strip()
    if len(query) < 2:
        raise InvalidSkillArg("query must contain at least 2 characters")

    category = str(args.get("category") or "auto").strip().lower()
    if category not in {"auto", "web", "ai", "payloads", "methodology", "all"}:
        raise InvalidSkillArg("category must be auto|web|ai|payloads|methodology|all")

    max_results = int(args.get("max_results") or 5)
    if max_results < 1 or max_results > 10:
        raise InvalidSkillArg("max_results must be between 1 and 10")

    resolved_category = _resolve_category(query, category)
    refs_dir = Path(__file__).resolve().parent / "references"
    files = _files_for_category(refs_dir, resolved_category)
    terms = _query_terms(query)

    matches = _search_references(files, terms, max_results=max_results)
    unable = not matches
    guidance = (
        "Use cited excerpts as hypotheses or payload families only; verify with "
        "the dedicated scanner/validator skill before reporting a confirmed finding."
        if matches
        else "UNABLE TO CITE: no bundled secknowledge reference matched this query."
    )

    return SkillResult(
        summary={
            "query": query,
            "category": resolved_category,
            "references": matches,
            "guidance": guidance,
            "unable_to_cite": unable,
        }
    )


def _resolve_category(query: str, category: str) -> str:
    if category != "auto":
        return category
    lowered = query.lower()
    for candidate, hints in _AUTO_HINTS.items():
        if any(hint in lowered for hint in hints):
            return candidate
    return "web"


def _files_for_category(refs_dir: Path, category: str) -> list[Path]:
    if category == "all":
        return sorted(refs_dir.glob("*.md"))
    names = _CATEGORY_FILES.get(category, _CATEGORY_FILES["web"])
    return [refs_dir / name for name in names if (refs_dir / name).is_file()]


def _query_terms(query: str) -> list[str]:
    terms = [term.lower() for term in _WORD_RE.findall(query)]
    # Keep order stable while removing duplicates.
    return list(dict.fromkeys(terms))[:12] or [query.lower()]


def _search_references(
    files: list[Path],
    terms: list[str],
    *,
    max_results: int,
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        current_section = path.stem
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                current_section = stripped.lstrip("#").strip() or current_section
                continue
            lowered = stripped.lower()
            if not stripped or not any(term in lowered for term in terms):
                continue
            excerpt = stripped
            if len(excerpt) > _MAX_EXCERPT_CHARS:
                excerpt = excerpt[: _MAX_EXCERPT_CHARS - 3].rstrip() + "..."
            matches.append(
                {
                    "file": f"references/{path.name}",
                    "section": current_section,
                    "excerpt": excerpt,
                }
            )
            if len(matches) >= max_results:
                return matches
    return matches
