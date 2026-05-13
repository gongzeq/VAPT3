"""Workflow engine public surface.

Runner, executors and REST wiring live in sibling modules; this package
namespace re-exports the stable types and helpers that downstream
modules (``secbot.api``, ``secbot.cli.commands``) should import.
"""

from secbot.workflow.executors import (
    ExecutorError,
    StepContext,
    StepExecutor,
    build_default_executors,
)
from secbot.workflow.expr import ExprError, eval_bool, interpolate
from secbot.workflow.runner import RunnerError, WorkflowRunner
from secbot.workflow.service import WorkflowService, WorkflowServiceError
from secbot.workflow.store import WorkflowStore
from secbot.workflow.types import (
    OnError,
    RunStatus,
    StepKind,
    StepResult,
    StepStatus,
    TriggerKind,
    Workflow,
    WorkflowInput,
    WorkflowRun,
    WorkflowStep,
)

__all__ = [
    "ExecutorError",
    "ExprError",
    "OnError",
    "RunStatus",
    "RunnerError",
    "StepContext",
    "StepExecutor",
    "StepKind",
    "StepResult",
    "StepStatus",
    "TriggerKind",
    "Workflow",
    "WorkflowInput",
    "WorkflowRun",
    "WorkflowRunner",
    "WorkflowService",
    "WorkflowServiceError",
    "WorkflowStep",
    "WorkflowStore",
    "build_default_executors",
    "eval_bool",
    "interpolate",
]
