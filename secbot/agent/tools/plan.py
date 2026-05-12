"""Tool for publishing an orchestrator plan event."""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from secbot.agent.tools.base import Tool, tool_parameters
from secbot.agent.tools.schema import (
    ArraySchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)


@tool_parameters(
    tool_parameters_schema(
        steps=ArraySchema(
            ObjectSchema(
                {
                    "title": StringSchema("Short step title."),
                    "detail": StringSchema("Optional step detail.", nullable=True),
                },
                required=["title"],
                additional_properties=False,
            ),
            description="Ordered orchestration plan steps.",
            min_items=1,
        ),
        required=["steps"],
    )
)
class WritePlanTool(Tool):
    """Publish the current orchestrator plan to the chat surface."""

    def __init__(self, chat_id_getter: Any | None = None) -> None:
        self._chat_id_getter = chat_id_getter

    @property
    def name(self) -> str:
        return "write_plan"

    @property
    def description(self) -> str:
        return (
            "Record a visible orchestration plan for the user. This only publishes "
            "the plan; it does not delegate or execute any step."
        )

    async def execute(self, steps: list[dict[str, Any]], **_: Any) -> str:
        clean_steps = [
            {
                "title": str(step.get("title", "")).strip(),
                **(
                    {"detail": str(step.get("detail")).strip()}
                    if step.get("detail") is not None and str(step.get("detail")).strip()
                    else {}
                ),
            }
            for step in steps
            if isinstance(step, dict) and str(step.get("title", "")).strip()
        ]
        if not clean_steps:
            return "Error: steps must include at least one title."

        chat_id = self._chat_id_getter() if callable(self._chat_id_getter) else None
        if chat_id:
            from secbot.channels.websocket import WebSocketChannel

            channel = WebSocketChannel.get_active_instance()
            if channel is not None:
                try:
                    await channel.broadcast_agent_event(
                        chat_id=chat_id,
                        type="orchestrator_plan",
                        payload={
                            "agent": "orchestrator",
                            "steps": clean_steps,
                            "timestamp": time.time(),
                        },
                    )
                except Exception:
                    logger.debug("agent_event (orchestrator_plan) broadcast failed", exc_info=True)
        return f"Plan recorded: {len(clean_steps)} steps"
