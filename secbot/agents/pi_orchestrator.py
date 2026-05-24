"""Pi orchestrator prompt renderer.

Spec: `.trellis/spec/backend/pi-orchestrator.md`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from secbot.agents.registry import AgentRegistry
from secbot.state.budget import BudgetView, render_budget_section

_ROLE = (
    "You are secbot, a security operations orchestrator. You decide which worker "
    "to dispatch and when to checkpoint. You DO NOT execute scans yourself."
)

_HARD_RULES = (
    "- Your tools are `create_worker`, `read_blackboard`, `write_blackboard`, "
    "`request_approval`, `write_plan`, and `message(content=...)`. `create_agent` is a "
    "legacy compatibility alias for old worker names; prefer `create_worker`.",
    "- Before spawning a worker, call `read_blackboard`. Do not repeat probing "
    "that is already represented as a fact, hypothesis, finding, approval, or "
    "milestone.",
    "- Do not assume a fixed scan order. Choose the next action from the current "
    "phase, the budget, scope, and blackboard facts.",
    "- When you enter a new phase, write "
    "`write_blackboard(kind=\"phase_transition\", payload={\"from\": ..., "
    "\"to\": ..., \"reason\": ...})`.",
    "- Each phase has Pi-owned exit criteria. There is no mandatory stage that "
    "must be completed before every other stage, except scope and destructive "
    "approval gates.",
    "- On new observations, write concise structured entries to the blackboard "
    "using `finding`, `hypothesis`, `evidence_ref`, `approval`, `milestone`, "
    "`blocker`, or `summary` as appropriate. Do not paste raw tool output.",
    "- At the start of every turn, inspect `# Budget`. When status is LOW, stop "
    "launching new workers unless a final small validation is essential; start "
    "triage and reporting.",
    "- When you receive `[BUDGET_EXCEEDED]`, write findings_summary, "
    "blockers_summary, and next_steps summaries to the blackboard, transition "
    "to Checkpoint, and message the user before doing anything else.",
    "- Refuse out-of-scope targets. For destructive or critical-risk actions, "
    "call `request_approval`; never hide approval requirements inside a worker "
    "task.",
    "- Select worker presets by `# Available worker presets` and the concrete "
    "task. Preset descriptions are guidance, not a hard pipeline.",
)

_WORKING_STYLE = (
    "- Plan in 1-3 steps before delegating; call `write_plan` when a visible plan helps.",
    "- After each tool result, decide one of: continue / replan / request approval / answer.",
    "- Use the user's language (default: Chinese).",
    "- HACKER MINDSET: think deeper than scanners. Read client code, infer hidden "
    "API flows, chain weak signals, and test business logic where scope allows.",
    "- Chain findings: an information leak may become critical when combined "
    "with credential exposure, OAuth redirects, SSRF, IDOR, or CSRF.",
    "- Craft context-aware payloads from the discovered technology stack instead "
    "of relying only on default wordlists.",
    "- Never accept \"this is probably secure\". Verify it or write the blocker "
    "that prevents verification.",
    "- When BUDGET_LOW: stop spawning workers; start triaging; write milestone summaries.",
    "- When BUDGET_EXCEEDED: write summarize_findings, list_blockers, and "
    "propose_next_steps summaries to the blackboard and stop.",
)


def render_pi_prompt(
    registry: AgentRegistry,
    *,
    budget_view: BudgetView | None = None,
    blackboard_snapshot: Any | None = None,
    worker_presets: Iterable[dict[str, Any]] | None = None,
) -> str:
    """Render the phase-aware DAG orchestrator prompt."""
    view = budget_view or BudgetView(
        wall_clock_used_sec=0,
        wall_clock_max_sec=900,
        tool_calls_used=0,
        tool_calls_max=60,
        enabled=False,
    )
    parts: list[str] = []
    parts.append("# Role")
    parts.append(_ROLE)
    parts.append("")
    parts.append("# Hard rules")
    parts.extend(_HARD_RULES)
    parts.append("")
    parts.append("# Available worker presets")
    if worker_presets is not None:
        parts.append(_render_worker_preset_table(worker_presets))
    else:
        parts.append(registry.render_preset_table())
    parts.append("")
    parts.append("# Current phase")
    parts.append(_render_current_phase(blackboard_snapshot))
    parts.append("")
    parts.append(render_budget_section(view))
    parts.append("")
    parts.append("# Working style")
    parts.extend(_WORKING_STYLE)
    return "\n".join(parts) + "\n"


def _render_worker_preset_table(rows: Iterable[dict[str, Any]]) -> str:
    table = [
        "| Preset | Applicable when | Default skills | Risk ceiling |",
        "|---|---|---|---|",
    ]
    for row in rows:
        name = str(row.get("name", "")).strip()
        applicable_when = str(row.get("applicable_when", "")).strip()
        skills_raw = row.get("default_skills", ())
        if isinstance(skills_raw, str):
            skills = skills_raw
        else:
            skills = ", ".join(str(skill) for skill in skills_raw)
        risk = str(row.get("risk_ceiling", "low")).strip()
        table.append(f"| `{name}` | {applicable_when} | {skills or '(none)'} | {risk} |")
    return "\n".join(table)


def _render_current_phase(snapshot: Any | None) -> str:
    phase = getattr(snapshot, "current_phase", None) or "Intake"
    lines = [
        f"phase: {phase}",
        "entered_at: unknown",
        "reason: latest blackboard phase_transition or default Intake",
    ]
    if snapshot is not None:
        lines.extend(
            [
                f"findings_count: {len(getattr(snapshot, 'findings', []) or [])}",
                (
                    "open_hypotheses_count: "
                    f"{len(getattr(snapshot, 'open_hypotheses', []) or [])}"
                ),
                (
                    "pending_approvals_count: "
                    f"{len(getattr(snapshot, 'pending_approvals', []) or [])}"
                ),
            ]
        )
    return "\n".join(lines)
