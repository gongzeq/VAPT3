"""Resource path resolution for skills.

Skills often need to load external resources (wordlists, POC templates, etc.)
from a well-known directory tree under the workspace.
"""

from __future__ import annotations

from pathlib import Path

from secbot.skills.types import SkillContext


def resource_dir(ctx: SkillContext) -> Path:
    """Return ``<workspace>/.secbot/resource/``.

    ``ctx.scan_dir`` is ``<workspace>/.secbot/scans/<scan_id>/``,
    so workspace is three levels up.
    """
    return ctx.scan_dir.parent.parent.parent / ".secbot" / "resource"


def resolve_resource(ctx: SkillContext, *parts: str) -> Path | None:
    """Resolve a path under ``.secbot/resource/`` and verify it exists.

    Returns ``None`` if the resolved path does not exist.
    """
    path = resource_dir(ctx) / Path(*parts)
    return path if path.exists() else None
