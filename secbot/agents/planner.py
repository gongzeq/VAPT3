"""Execution plan models for parallel orchestration.

Spec: The orchestrator LLM emits a structured JSON execution plan that
describes which agents to invoke and how to batch them for parallelism.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTask:
    """A single agent invocation within a batch."""

    agent_name: str
    input_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionBatch:
    """A batch of agent tasks that can execute in parallel."""

    tasks: list[AgentTask] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    """Structured execution plan output by the Orchestrator LLM."""

    batches: list[ExecutionBatch] = field(default_factory=list)
    reasoning: str = ""


def parse_execution_plan(llm_output: str) -> ExecutionPlan | None:
    """Parse LLM output to extract a structured execution plan.

    Expects JSON in format:
    {
        "reasoning": "...",
        "batches": [
            {"tasks": [{"agent": "name", "args": {...}}, ...]},
            ...
        ]
    }

    Returns None if no valid plan found in the output.
    """
    # Try to extract JSON from markdown code blocks or raw JSON
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", llm_output, re.DOTALL)
    if json_match:
        raw = json_match.group(1).strip()
    else:
        # Try raw JSON detection
        brace_start = llm_output.find("{")
        if brace_start == -1:
            return None
        raw = llm_output[brace_start:]
        # Find matching closing brace
        depth = 0
        end = -1
        for i, ch in enumerate(raw):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            return None
        raw = raw[:end]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict) or "batches" not in data:
        return None

    plan = ExecutionPlan(reasoning=data.get("reasoning", ""))
    for batch_data in data["batches"]:
        batch = ExecutionBatch()
        for task_data in batch_data.get("tasks", []):
            agent_name = task_data.get("agent", "")
            input_args = task_data.get("args", {})
            if agent_name:
                batch.tasks.append(AgentTask(agent_name=agent_name, input_args=input_args))
        if batch.tasks:
            plan.batches.append(batch)

    return plan if plan.batches else None
