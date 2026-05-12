"""Tool for requesting structured human approval."""

from typing import Any

from secbot.agent.tools.ask import AskUserInterrupt
from secbot.agent.tools.base import Tool, tool_parameters
from secbot.agent.tools.schema import ArraySchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        title=StringSchema("Short approval title describing the action to review."),
        detail=StringSchema(
            "Optional detail explaining scope, expected impact, and why approval is needed.",
            nullable=True,
        ),
        options=ArraySchema(
            StringSchema("A possible approval decision label"),
            description="Optional decision choices. Defaults to Approve and Deny.",
        ),
        required=["title"],
    )
)
class RequestApprovalTool(Tool):
    """Pause the turn until the user approves or denies a proposed action."""

    @property
    def name(self) -> str:
        return "request_approval"

    @property
    def description(self) -> str:
        return (
            "Request blocking human approval before continuing with a sensitive "
            "or externally visible action. Use this for orchestration-level approval."
        )

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self,
        title: str,
        detail: str | None = None,
        options: list[str] | None = None,
        **_: Any,
    ) -> Any:
        choices = [str(option) for option in (options or ["Approve", "Deny"]) if str(option)]
        question = title.strip()
        if detail and detail.strip():
            question = f"{question}\n\n{detail.strip()}"
        raise AskUserInterrupt(question=question, options=choices)
