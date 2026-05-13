"""Disk-backed workflow persistence.

Two files live side-by-side under ``<root>/workflows/``:

* ``workflows.json`` — complete list of ``Workflow`` objects, atomically
  rewritten on every mutation (filelock + ``os.replace`` + ``fsync``).
* ``runs.jsonl`` — append-only log of ``WorkflowRun`` snapshots; newer
  entries overwrite older ones on ``upsert_run`` by re-serialising the
  whole file (acceptable: MVP expects a few thousand rows max, and the
  engine prunes by time + count anyway).

Why JSON not SQL: mirrors ``secbot/cron/service.py`` persistence style,
keeps zero extra deps, and lets the config directory stay hand-editable
for ops. Swap for SQLAlchemy later if run volume justifies it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from filelock import FileLock

from secbot.utils.atomic import atomic_write_text
from secbot.workflow.types import Workflow, WorkflowRun

# Default retention: keep the most recent ``_MAX_RUNS`` runs. Anything
# older is dropped on ``upsert_run``. Tune via constructor argument.
_MAX_RUNS_DEFAULT = 1000


class WorkflowStore:
    """Filesystem-backed CRUD for workflows and their runs.

    All mutating methods acquire a process-shared :class:`FileLock` so
    concurrent secbot workers (unlikely in MVP, but possible once cron
    + REST + direct API overlap) cannot corrupt ``workflows.json``.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_runs: int = _MAX_RUNS_DEFAULT,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._workflows_path = self._root / "workflows.json"
        self._runs_path = self._root / "runs.jsonl"
        self._lock = FileLock(str(self._root) + ".lock")
        self._max_runs = max_runs

    # ------------------------------------------------------------------
    # Workflow CRUD
    # ------------------------------------------------------------------

    def list_workflows(self) -> list[Workflow]:
        """Return every persisted workflow. Missing file ⇒ empty list."""
        if not self._workflows_path.exists():
            return []
        try:
            raw = json.loads(self._workflows_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        items = raw.get("items", []) if isinstance(raw, dict) else raw
        out: list[Workflow] = []
        for entry in items:
            try:
                out.append(Workflow.from_dict(entry))
            except Exception:
                # Ignore malformed rows rather than fail startup.
                continue
        return out

    def get_workflow(self, wf_id: str) -> Workflow | None:
        for wf in self.list_workflows():
            if wf.id == wf_id:
                return wf
        return None

    def save_workflow(self, wf: Workflow) -> Workflow:
        """Insert or replace ``wf`` (match by ``id``)."""
        with self._lock:
            items = self.list_workflows()
            items = [w for w in items if w.id != wf.id]
            items.append(wf)
            self._write_workflows(items)
        return wf

    def delete_workflow(self, wf_id: str) -> bool:
        with self._lock:
            items = self.list_workflows()
            new_items = [w for w in items if w.id != wf_id]
            if len(new_items) == len(items):
                return False
            self._write_workflows(new_items)
        return True

    def _write_workflows(self, items: Iterable[Workflow]) -> None:
        payload = {"version": 1, "items": [w.to_dict() for w in items]}
        atomic_write_text(
            self._workflows_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    # ------------------------------------------------------------------
    # Run log
    # ------------------------------------------------------------------

    def list_runs(self, *, workflow_id: str | None = None, limit: int | None = None) -> list[WorkflowRun]:
        """Return most recent runs first (newest → oldest)."""
        if not self._runs_path.exists():
            return []
        out: list[WorkflowRun] = []
        try:
            with open(self._runs_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(WorkflowRun.from_dict(json.loads(line)))
                    except Exception:
                        # Tolerate a trailing malformed row (truncated crash).
                        continue
        except OSError:
            return []
        if workflow_id is not None:
            out = [r for r in out if r.workflow_id == workflow_id]
        # Newest first: sort by started_at_ms desc.
        out.sort(key=lambda r: r.started_at_ms, reverse=True)
        if limit is not None:
            out = out[:limit]
        return out

    def get_run(self, run_id: str) -> WorkflowRun | None:
        for run in self.list_runs():
            if run.id == run_id:
                return run
        return None

    def upsert_run(self, run: WorkflowRun) -> WorkflowRun:
        """Persist ``run`` and truncate the log to ``max_runs`` entries.

        A run is typically inserted twice — once on ``started``, once on
        ``finished`` — so we rewrite the whole JSONL file each time to
        honour the upsert semantic. This is O(n) on the retention window
        (≤ 1000 rows), which is acceptable for MVP.
        """
        with self._lock:
            existing = {r.id: r for r in self.list_runs()}
            existing[run.id] = run
            ordered = sorted(existing.values(), key=lambda r: r.started_at_ms, reverse=True)
            kept = ordered[: self._max_runs]
            lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in reversed(kept)]
            atomic_write_text(self._runs_path, ("\n".join(lines) + ("\n" if lines else "")))
        return run
