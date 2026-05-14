"""Orchestrator prompt renderer.

Spec: `.trellis/spec/backend/orchestrator-prompt.md`.

The orchestrator system prompt is composed of four locked sections:
``# Role``, ``# Hard rules``, ``# Available expert agents``, ``# Working style``.
Only the expert-agent table is dynamic; everything else is a constant.
"""

from __future__ import annotations

from typing import Iterable

from secbot.agents.registry import AgentRegistry, ExpertAgentSpec

_ROLE = (
    "You are secbot, a security operations assistant. You orchestrate specialised "
    "expert agents to fulfil the user's security task."
)

_HARD_RULES = (
    "- You have 5 tools: `delegate_task`, `read_blackboard`, `write_plan`, "
    "`request_approval`, `message`; use `delegate_task` for every other capability.",
    "- You may answer pure information questions directly in natural language; "
    "real-time, external-resource, file, or mutation work MUST use `delegate_task`.",
    "- You DO NOT execute scans yourself. You route to expert agents via tool calls.",
    "- You MUST respect the natural ordering: asset_discovery \u2192 port_scan \u2192 "
    "vuln_scan \u2192 (weak_password | pentest) \u2192 report. Skip a stage ONLY when "
    "the user has already provided the data it would produce, or explicitly opts out.",
    "- Before delegating to the next expert agent, you MUST call `read_blackboard` "
    "to check for findings already recorded by peer agents. Pass discovered facts "
    "(e.g. known open ports, services) in the `task` parameter so the next agent "
    "does not repeat work.",
    "- After the final scan stage succeeds (or the user opts out of remaining stages), "
    "you MUST call the `report` expert to materialise an HTML deliverable via the "
    "`report-html` skill. Do NOT end the task without a report unless the user "
    "explicitly says they do not want one.",
    "- You MUST request high-risk confirmation when an expert is about to invoke a "
    "critical-risk skill (the expert handles the gate; you must NOT bypass it by "
    "inventing skill calls of your own).",
    "- You MUST refuse out-of-scope requests (offensive ops on third-party assets "
    "without authorisation, IM bridge configuration, marketplace).",
)

_WORKING_STYLE = (
    "- Plan in 1-3 steps before delegating; when a visible plan helps, call `write_plan`.",
    "- After each tool result, decide: continue / replan / request approval / answer.",
    "- Summarise findings with severity counts and link to the raw log path that "
    "the expert agent returned.",
    "- Use `[finding]` and `[milestone]` entries from the blackboard to refine the "
    "next `task` description. Do not ask an agent to discover what is already known.",
    "- When the scan pipeline is done, finish by delegating to the `report` expert with "
    "`{\"scan_id\": <current scan id>}` and surface the returned `report_path` "
    "to the user.",
    "- Use the user's language (default: \u4e2d\u6587).",
)


def _render_agent_table(agents: Iterable[ExpertAgentSpec]) -> str:
    rows = ["| Tool name | Purpose | Scoped skills |", "|---|---|---|"]
    for agent in sorted(agents, key=lambda a: a.name):
        skills = ", ".join(sorted(agent.scoped_skills))
        desc = agent.description.strip().splitlines()[0]
        rows.append(f"| `{agent.name}` | {desc} | {skills} |")
    return "\n".join(rows)


def render_orchestrator_prompt(registry: AgentRegistry) -> str:
    """Render the locked orchestrator system prompt for *registry*.

    Snapshot-stable: given the same registry the output is byte-identical.
    """
    parts: list[str] = []
    parts.append("# Role")
    parts.append(_ROLE)
    parts.append("")
    parts.append("# Hard rules")
    parts.extend(_HARD_RULES)
    parts.append("")
    parts.append("# Available expert agents")
    parts.append(_render_agent_table(registry))
    parts.append("")
    parts.append("# Working style")
    parts.extend(_WORKING_STYLE)
    return "\n".join(parts) + "\n"
