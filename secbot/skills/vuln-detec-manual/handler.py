"""vuln-detec-manual handler.

Placeholder skill — the vuln_detec expert agent performs verification
probes via ExecTool (curl). This handler returns a guidance message.
"""

from typing import Any

from secbot.skills.types import SkillContext, SkillResult


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    return SkillResult(
        data={"message": "Use the exec tool to run curl-based manual verification tests."},
        summary="vuln-detec-manual is a registry placeholder; run probes via exec.",
    )
