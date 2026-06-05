"""Resource path resolution for skills.

Skills often need to load external resources (wordlists, POC templates, etc.)
from a well-known directory tree under the workspace.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from secbot.skills.types import SkillContext


def _workspace_root(ctx: SkillContext) -> Path:
    """Infer the workspace root from a scan directory.

    Runtime scans normally live under ``<workspace>/.secbot/scans/<scan_id>``
    or ``<workspace>/secbot/scans/<scan_id>``. Unit tests often pass a plain
    temporary scan directory, so fall back to the scan directory's parent.
    """

    scan_dir = ctx.scan_dir
    if scan_dir.parent.name == "scans" and scan_dir.parent.parent.name in {
        ".secbot",
        "secbot",
    }:
        return scan_dir.parent.parent.parent
    return scan_dir.parent


def resource_dir(ctx: SkillContext) -> Path:
    """Return ``<workspace>/secbot/resource/``.

    This is the writable workspace resource location. Use
    :func:`resolve_resource` when callers should also accept bundled resources.
    """
    return _workspace_root(ctx) / "secbot" / "resource"


def _bundled_resource_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "resource"


def _candidate_resource_dirs(ctx: SkillContext) -> Iterable[Path]:
    workspace = _workspace_root(ctx)
    candidates = [
        resource_dir(ctx),
        workspace / ".secbot" / "resource",
        _bundled_resource_dir(),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        yield candidate


def resolve_resource(ctx: SkillContext, *parts: str) -> Path | None:
    """Resolve a resource path and verify it exists.

    Workspace resources take precedence, followed by the legacy
    ``.secbot/resource`` location and finally bundled project resources.

    Returns ``None`` if the resolved path does not exist.
    """
    relative = Path(*parts)
    if relative.is_absolute():
        return None
    for root in _candidate_resource_dirs(ctx):
        root_path = root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root_path):
            continue
        if path.exists():
            return path
    return None


def list_dicts(ctx: SkillContext, category: str) -> list[str]:
    """List available dictionary/resource files under *category*.

    Returns sorted relative paths (POSIX strings) under
    ``secbot/resource/<category>/`` across all candidate resource roots.
    Hidden files and ``__pycache__`` entries are excluded.

    Skills can call this to enumerate available wordlists before prompting
    the LLM to pick one — avoiding the need for the LLM to glob the tree
    with relative paths (which the glob tool cannot resolve).

    >>> list_dicts(ctx, "fuzzDicts")
    ['XXEDicts/README.MD', 'apiDict/api.txt', ...]
    """
    results: set[str] = set()
    for root in _candidate_resource_dirs(ctx):
        cat_dir = root / category
        if not cat_dir.is_dir():
            continue
        for path in cat_dir.rglob("*"):
            if not path.is_file():
                continue
            # Skip hidden files and Python bytecode caches
            if any(
                part.startswith(".") or part == "__pycache__"
                for part in path.parts
            ):
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            rel = path.relative_to(cat_dir)
            results.add(rel.as_posix())
    return sorted(results)
