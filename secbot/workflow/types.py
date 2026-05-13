"""Workflow data model.

Mirrors ``.trellis/tasks/05-11-workflow-builder-ui/api-spec.md`` §1. Every
field serialises to camelCase via :func:`to_dict`; :func:`from_dict` is
tolerant of both snake_case (legacy) and camelCase payloads.

Kept deliberately dataclass-based (not pydantic) to match the cron module
style (``secbot/cron/types.py``) and keep the serialisation surface
small and explicit.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


StepKind = Literal["tool", "script", "agent", "llm"]
OnError = Literal["stop", "continue", "retry"]
RunStatus = Literal["running", "ok", "error", "cancelled"]
StepStatus = Literal["ok", "error", "skipped", "retried"]
InputType = Literal["string", "cidr", "int", "bool", "enum"]
TriggerKind = Literal["manual", "cron", "api"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# camelCase / snake_case mapping
# ---------------------------------------------------------------------------

# snake_case dataclass field name  <->  camelCase JSON field name. Any
# field not listed round-trips as-is.
_CAMEL_MAP: dict[str, str] = {
    "created_at_ms": "createdAtMs",
    "updated_at_ms": "updatedAtMs",
    "schedule_ref": "scheduleRef",
    "enum_values": "enumValues",
    "on_error": "onError",
    "started_at_ms": "startedAtMs",
    "finished_at_ms": "finishedAtMs",
    "duration_ms": "durationMs",
    "step_results": "stepResults",
    "workflow_id": "workflowId",
}
_SNAKE_MAP: dict[str, str] = {v: k for k, v in _CAMEL_MAP.items()}


def _to_camel(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {_CAMEL_MAP.get(k, k): _to_camel(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_camel(x) for x in obj]
    return obj


def _to_snake(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {_SNAKE_MAP.get(k, k): _to_snake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_snake(x) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# Input / Step
# ---------------------------------------------------------------------------


@dataclass
class WorkflowInput:
    """A single user-defined workflow input parameter.

    Names, types and requiredness are fully creator-supplied — the UI
    MUST NOT pre-populate any field name. ``required`` here only controls
    whether the value may be omitted on run; it does NOT imply that any
    particular name (``target_ip`` etc.) must exist.
    """

    name: str
    label: str
    type: InputType = "string"
    required: bool = False
    default: Any = None
    description: str | None = None
    enum_values: list[str] | None = None


@dataclass
class WorkflowStep:
    """One ordered step inside a workflow.

    ``kind`` selects one of 4 executors (tool | script | agent | llm). The
    shape of ``args`` is kind-specific; see
    ``.trellis/tasks/05-11-workflow-builder-ui/api-spec.md §1.3``.
    """

    id: str
    name: str
    kind: StepKind
    ref: str
    args: dict[str, Any] = field(default_factory=dict)
    condition: str | None = None
    on_error: OnError = "stop"
    retry: int = 0


@dataclass
class Workflow:
    """A versioned, schedulable workflow definition."""

    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    inputs: list[WorkflowInput] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    schedule_ref: str | None = None
    created_at_ms: int = 0
    updated_at_ms: int = 0

    # ---- factory / serialisation -----------------------------------------

    @classmethod
    def new(
        cls,
        *,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
        inputs: list[WorkflowInput] | None = None,
        steps: list[WorkflowStep] | None = None,
    ) -> "Workflow":
        now = _now_ms()
        return cls(
            id=_new_id("wf"),
            name=name,
            description=description,
            tags=list(tags or []),
            inputs=list(inputs or []),
            steps=list(steps or []),
            created_at_ms=now,
            updated_at_ms=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return _to_camel(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        data = _to_snake(dict(data))
        inputs = [WorkflowInput(**_to_snake(x)) for x in data.get("inputs", [])]
        steps = [WorkflowStep(**_to_snake(x)) for x in data.get("steps", [])]
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            tags=list(data.get("tags", [])),
            inputs=inputs,
            steps=steps,
            schedule_ref=data.get("schedule_ref"),
            created_at_ms=int(data.get("created_at_ms") or 0),
            updated_at_ms=int(data.get("updated_at_ms") or 0),
        )


# ---------------------------------------------------------------------------
# Run / StepResult
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Unified return contract for all 4 executor kinds.

    ``output`` shape is kind-specific but always referenceable by downstream
    steps via ``${steps.<id>.result.<jsonpath>}``.
    """

    status: StepStatus
    started_at_ms: int
    finished_at_ms: int
    duration_ms: int
    output: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _to_camel(asdict(self))

    @classmethod
    def skipped(cls, *, at_ms: int | None = None) -> "StepResult":
        t = at_ms if at_ms is not None else _now_ms()
        return cls(status="skipped", started_at_ms=t, finished_at_ms=t, duration_ms=0)


@dataclass
class WorkflowRun:
    """A single execution of a workflow.

    ``step_results`` maps ``step.id`` to ``StepResult``. ``trigger`` marks
    the entry point (``manual`` via REST, ``cron`` via scheduler, ``api``
    via programmatic).
    """

    id: str
    workflow_id: str
    started_at_ms: int
    finished_at_ms: int | None = None
    status: RunStatus = "running"
    inputs: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, StepResult] = field(default_factory=dict)
    trigger: TriggerKind = "manual"
    error: str | None = None

    @classmethod
    def new(
        cls, *, workflow_id: str, inputs: dict[str, Any], trigger: TriggerKind = "manual"
    ) -> "WorkflowRun":
        return cls(
            id=_new_id("run"),
            workflow_id=workflow_id,
            started_at_ms=_now_ms(),
            inputs=dict(inputs),
            trigger=trigger,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "status": self.status,
            "inputs": self.inputs,
            "step_results": {sid: r.to_dict() for sid, r in self.step_results.items()},
            "trigger": self.trigger,
            "error": self.error,
        }
        # step_results inner values already camelCased; only outer keys left.
        return _to_camel(payload)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowRun":
        data = _to_snake(dict(data))
        results: dict[str, StepResult] = {}
        for sid, raw in (data.get("step_results") or {}).items():
            raw = _to_snake(raw)
            results[sid] = StepResult(
                status=raw.get("status", "ok"),
                started_at_ms=int(raw.get("started_at_ms") or 0),
                finished_at_ms=int(raw.get("finished_at_ms") or 0),
                duration_ms=int(raw.get("duration_ms") or 0),
                output=raw.get("output"),
                error=raw.get("error"),
            )
        return cls(
            id=data["id"],
            workflow_id=data["workflow_id"],
            started_at_ms=int(data.get("started_at_ms") or 0),
            finished_at_ms=(int(data["finished_at_ms"]) if data.get("finished_at_ms") else None),
            status=data.get("status", "running"),
            inputs=dict(data.get("inputs") or {}),
            step_results=results,
            trigger=data.get("trigger", "manual"),
            error=data.get("error"),
        )
