"""Persistent teammate communication and lifecycle support."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from loguru import logger

from secbot.agent.runner import AgentRunner, AgentRunSpec
from secbot.agent.tools.registry import ToolRegistry
from secbot.config.schema import AgentDefaults
from secbot.providers.base import LLMProvider

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
TEAM_STATUS_IDLE = "idle"
TEAM_STATUS_WORKING = "working"
TEAM_STATUS_SHUTDOWN = "shutdown"
TEAM_STATUSES = frozenset({TEAM_STATUS_IDLE, TEAM_STATUS_WORKING, TEAM_STATUS_SHUTDOWN})
_UNSET = object()


def normalize_teammate_name(name: str) -> str:
    """Return the canonical teammate name used for config keys and inbox files."""
    normalized = str(name or "").strip().lower()
    if not _NAME_RE.fullmatch(normalized):
        raise ValueError(
            "teammate name must be 1-64 chars of lowercase letters, digits, '_', '.', or '-' "
            "and must start with a letter or digit"
        )
    return normalized


@dataclass(slots=True)
class _TeammateWorker:
    """Process-local handle for a teammate run hosted by a dedicated thread."""

    thread: threading.Thread
    done: threading.Event
    error: BaseException | None = None


@dataclass(slots=True)
class TeamMessage:
    """One structured message stored as a JSONL mailbox row."""

    sender: str
    to: str
    content: str
    msg_type: str = "message"
    timestamp: float = 0.0
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.msg_type,
            "from": self.sender,
            "to": self.to,
            "content": self.content,
            "timestamp": self.timestamp or time.time(),
            "metadata": dict(self.metadata or {}),
        }


class TeamMessageBus:
    """File-backed JSONL mailboxes under ``.team/inbox``."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.team_dir = self.workspace / ".team"
        self.inbox_dir = self.team_dir / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, RLock] = {}
        self._locks_guard = RLock()

    def _lock_for(self, name: str) -> RLock:
        normalized = normalize_teammate_name(name)
        with self._locks_guard:
            lock = self._locks.get(normalized)
            if lock is None:
                lock = RLock()
                self._locks[normalized] = lock
            return lock

    def inbox_path(self, name: str) -> Path:
        return self.inbox_dir / f"{normalize_teammate_name(name)}.jsonl"

    def ensure_inbox(self, name: str) -> Path:
        path = self.inbox_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    async def send(
        self,
        *,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sender_name = normalize_teammate_name(sender)
        target_name = normalize_teammate_name(to)
        if not str(content or "").strip():
            raise ValueError("message content cannot be empty")
        message = TeamMessage(
            sender=sender_name,
            to=target_name,
            content=str(content).strip(),
            msg_type=str(msg_type or "message").strip() or "message",
            timestamp=time.time(),
            metadata=dict(metadata or {}),
        ).to_dict()
        path = self.ensure_inbox(target_name)
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock_for(target_name):
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        return message

    async def read_inbox(self, name: str) -> list[dict[str, Any]]:
        normalized = normalize_teammate_name(name)
        path = self.ensure_inbox(normalized)
        with self._lock_for(normalized):
            lines = path.read_text(encoding="utf-8").splitlines()
            messages: list[dict[str, Any]] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed teammate inbox row for {}", normalized)
                    continue
                if isinstance(data, dict):
                    messages.append(data)
            path.write_text("", encoding="utf-8")
        return messages


@dataclass(slots=True)
class TeammateRecord:
    """Durable teammate roster entry."""

    name: str
    role: str
    status: str = TEAM_STATUS_IDLE
    created_at: float = 0.0
    updated_at: float = 0.0
    current_task: str | None = None
    last_result: str | None = None
    last_error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeammateRecord:
        name = normalize_teammate_name(str(data.get("name", "")))
        status = str(data.get("status") or TEAM_STATUS_IDLE)
        if status not in TEAM_STATUSES:
            status = TEAM_STATUS_IDLE
        now = time.time()
        return cls(
            name=name,
            role=str(data.get("role") or ""),
            status=status,
            created_at=float(data.get("created_at") or now),
            updated_at=float(data.get("updated_at") or now),
            current_task=data.get("current_task") if data.get("current_task") else None,
            last_result=data.get("last_result") if data.get("last_result") else None,
            last_error=data.get("last_error") if data.get("last_error") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_task": self.current_task,
            "last_result": self.last_result,
            "last_error": self.last_error,
        }


class TeamConfigStore:
    """Atomic JSON config store for ``.team/config.json``."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.team_dir = self.workspace / ".team"
        self.path = self.team_dir / "config.json"
        self._lock = RLock()
        self.team_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save_unlocked({"team_name": "default", "members": []})

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, TypeError, json.JSONDecodeError):
            data = {"team_name": "default", "members": []}
        if not isinstance(data, dict):
            data = {"team_name": "default", "members": []}
        members = data.get("members")
        if not isinstance(members, list):
            data["members"] = []
        data.setdefault("team_name", "default")
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        self.team_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
        os.replace(tmp_path, self.path)

    def list(self) -> list[TeammateRecord]:
        with self._lock:
            data = self._load_unlocked()
            records: list[TeammateRecord] = []
            for raw in data.get("members", []):
                if not isinstance(raw, dict):
                    continue
                try:
                    records.append(TeammateRecord.from_dict(raw))
                except ValueError:
                    logger.warning("Skipping invalid teammate config row: {}", raw)
            return records

    def get(self, name: str) -> TeammateRecord | None:
        normalized = normalize_teammate_name(name)
        return next((record for record in self.list() if record.name == normalized), None)

    def upsert(
        self,
        *,
        name: str,
        role: str,
        status: str,
        current_task: str | None = None,
        last_result: Any = _UNSET,
        last_error: Any = _UNSET,
    ) -> TeammateRecord:
        normalized = normalize_teammate_name(name)
        if status not in TEAM_STATUSES:
            raise ValueError(f"invalid teammate status: {status}")
        now = time.time()
        with self._lock:
            data = self._load_unlocked()
            members = [
                TeammateRecord.from_dict(raw)
                for raw in data.get("members", [])
                if isinstance(raw, dict)
            ]
            record = next((member for member in members if member.name == normalized), None)
            if record is None:
                record = TeammateRecord(
                    name=normalized,
                    role=role,
                    status=status,
                    created_at=now,
                    updated_at=now,
                    current_task=current_task,
                    last_result=None if last_result is _UNSET else last_result,
                    last_error=None if last_error is _UNSET else last_error,
                )
                members.append(record)
            else:
                record.role = role or record.role
                record.status = status
                record.updated_at = now
                record.current_task = current_task
                if last_result is not _UNSET:
                    record.last_result = last_result
                if last_error is not _UNSET:
                    record.last_error = last_error
            members.sort(key=lambda item: item.name)
            data["members"] = [member.to_dict() for member in members]
            self._save_unlocked(data)
            return TeammateRecord.from_dict(record.to_dict())

    def update_status(
        self,
        name: str,
        status: str,
        *,
        current_task: str | None = None,
        last_result: Any = _UNSET,
        last_error: Any = _UNSET,
    ) -> TeammateRecord:
        record = self.get(name)
        if record is None:
            raise KeyError(f"unknown teammate: {name}")
        return self.upsert(
            name=record.name,
            role=record.role,
            status=status,
            current_task=current_task,
            last_result=last_result,
            last_error=last_error,
        )

    def reset_working_to_idle(self) -> list[TeammateRecord]:
        """Mark stale working records idle after a process restart."""
        with self._lock:
            data = self._load_unlocked()
            changed = False
            now = time.time()
            members: list[TeammateRecord] = []
            for raw in data.get("members", []):
                if not isinstance(raw, dict):
                    continue
                try:
                    record = TeammateRecord.from_dict(raw)
                except ValueError:
                    logger.warning("Skipping invalid teammate config row: {}", raw)
                    continue
                if record.status == TEAM_STATUS_WORKING:
                    record.status = TEAM_STATUS_IDLE
                    record.updated_at = now
                    record.current_task = None
                    record.last_error = "Recovered from interrupted teammate run."
                    changed = True
                members.append(record)
            if changed:
                members.sort(key=lambda item: item.name)
                data["members"] = [member.to_dict() for member in members]
                self._save_unlocked(data)
            return [TeammateRecord.from_dict(member.to_dict()) for member in members]


class TeammateManager:
    """Manages persistent teammates with durable roster and JSONL inboxes."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        *,
        model: str | None = None,
        max_tool_result_chars: int | None = None,
        max_iterations: int | None = None,
    ) -> None:
        defaults = AgentDefaults()
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_tool_result_chars = (
            max_tool_result_chars
            if max_tool_result_chars is not None
            else defaults.max_tool_result_chars
        )
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else defaults.max_tool_iterations
        )
        self.config = TeamConfigStore(workspace)
        self.config.reset_working_to_idle()
        self.mailboxes = TeamMessageBus(workspace)
        self.runner = AgentRunner(provider)
        self._workers: dict[str, _TeammateWorker] = {}
        self._workers_lock = RLock()

    def set_provider(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model
        self.runner.provider = provider

    async def spawn(self, *, name: str, role: str, task: str | None = None) -> TeammateRecord:
        """Create or assign a teammate. Supplying *task* starts a working run."""
        teammate = normalize_teammate_name(name)
        role = str(role or "").strip()
        if not role:
            raise ValueError("role cannot be empty")
        work = str(task or "").strip()
        existing = self.config.get(teammate)
        if existing is not None and existing.status == TEAM_STATUS_SHUTDOWN:
            raise RuntimeError(f"teammate '{teammate}' is shutdown")
        running = self._worker_for(teammate)
        if running is not None and running.thread.is_alive():
            raise RuntimeError(f"teammate '{teammate}' is already working")
        self.mailboxes.ensure_inbox(teammate)
        status = TEAM_STATUS_WORKING if work else TEAM_STATUS_IDLE
        record = self.config.upsert(
            name=teammate,
            role=role,
            status=status,
            current_task=work or None,
            last_error=None,
        )
        if work:
            self._start_worker(record.name, record.role, work)
        return record

    async def list_teammates(self) -> list[TeammateRecord]:
        return self.config.list()

    async def send(
        self,
        *,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = normalize_teammate_name(to)
        if target != "orchestrator" and self.config.get(target) is None:
            raise KeyError(f"unknown teammate: {target}")
        return await self.mailboxes.send(
            sender=sender,
            to=target,
            content=content,
            msg_type=msg_type,
            metadata=metadata,
        )

    async def read_inbox(self, name: str) -> list[dict[str, Any]]:
        return await self.mailboxes.read_inbox(name)

    async def shutdown(self, name: str) -> TeammateRecord:
        teammate = normalize_teammate_name(name)
        if self.config.get(teammate) is None:
            raise KeyError(f"unknown teammate: {teammate}")
        return self.config.update_status(
            teammate,
            TEAM_STATUS_SHUTDOWN,
            current_task=None,
        )

    async def wait_for_idle(self, name: str, timeout: float = 5.0) -> TeammateRecord:
        teammate = normalize_teammate_name(name)
        worker = self._worker_for(teammate)
        if worker is not None and worker.thread.is_alive():
            await self._join_worker(worker, timeout)
        self._cleanup_worker(teammate)
        record = self.config.get(teammate)
        if record is None:
            raise KeyError(f"unknown teammate: {teammate}")
        return record

    def _worker_for(self, name: str) -> _TeammateWorker | None:
        with self._workers_lock:
            return self._workers.get(name)

    def _start_worker(self, name: str, role: str, task: str) -> None:
        done = threading.Event()
        worker = _TeammateWorker(
            thread=threading.Thread(
                target=self._run_teammate_thread,
                args=(name, role, task, done),
                name=f"secbot-teammate-{name}",
                daemon=True,
            ),
            done=done,
        )
        with self._workers_lock:
            self._workers[name] = worker
        worker.thread.start()

    def _run_teammate_thread(
        self,
        name: str,
        role: str,
        task: str,
        done: threading.Event,
    ) -> None:
        try:
            asyncio.run(self._run_teammate(name, role, task))
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            logger.exception("Teammate thread '{}' failed", name)
            with self._workers_lock:
                worker = self._workers.get(name)
                if worker is not None:
                    worker.error = exc
            record = self.config.get(name)
            if record is not None and record.status != TEAM_STATUS_SHUTDOWN:
                self.config.update_status(
                    name,
                    TEAM_STATUS_IDLE,
                    current_task=None,
                    last_error=str(exc),
                )
        finally:
            done.set()

    async def _join_worker(self, worker: _TeammateWorker, timeout: float) -> None:
        await asyncio.wait_for(asyncio.to_thread(worker.done.wait), timeout=timeout)
        if worker.error is not None:
            raise worker.error

    def _cleanup_worker(self, name: str) -> None:
        with self._workers_lock:
            worker = self._workers.get(name)
            if worker is not None and not worker.thread.is_alive():
                self._workers.pop(name, None)

    async def _run_teammate(self, name: str, role: str, task: str) -> None:
        try:
            result = await self.runner.run(
                AgentRunSpec(
                    initial_messages=self._initial_messages(name, role, task),
                    tools=self._build_teammate_tools(name),
                    model=self.model,
                    max_iterations=self.max_iterations,
                    max_tool_result_chars=self.max_tool_result_chars,
                    max_iterations_message="Teammate run completed without a final response.",
                    error_message=None,
                    fail_on_tool_error=False,
                    workspace=self.workspace,
                    session_key=f"teammate:{name}",
                )
            )
            record = self.config.get(name)
            if record is not None and record.status != TEAM_STATUS_SHUTDOWN:
                last_error = result.error if result.stop_reason == "error" else None
                self.config.update_status(
                    name,
                    TEAM_STATUS_IDLE,
                    current_task=None,
                    last_result=result.final_content,
                    last_error=last_error,
                )
        except Exception as exc:
            logger.exception("Teammate '{}' failed", name)
            record = self.config.get(name)
            if record is not None and record.status != TEAM_STATUS_SHUTDOWN:
                self.config.update_status(
                    name,
                    TEAM_STATUS_IDLE,
                    current_task=None,
                    last_error=str(exc),
                )

    def _build_teammate_tools(self, name: str) -> ToolRegistry:
        from secbot.agent.tools.teammate import (
            ListTeammatesTool,
            ReadTeammateInboxTool,
            SendTeammateMessageTool,
        )

        tools = ToolRegistry()
        tools.register(ListTeammatesTool(self))
        tools.register(SendTeammateMessageTool(self, sender=name))
        tools.register(
            ReadTeammateInboxTool(
                self,
                default_name=name,
                allow_name_override=False,
            )
        )
        return tools

    @staticmethod
    def _initial_messages(name: str, role: str, task: str) -> list[dict[str, Any]]:
        system = (
            f"You are persistent teammate `{name}`.\n"
            f"Role: {role}\n\n"
            "You run in an isolated agent loop. Use teammate mailbox tools for "
            "asynchronous coordination. Read your own inbox when the task needs "
            "updates from peers, and send concise messages to other teammates or "
            "to `orchestrator`. When this assigned task is done, provide a final "
            "summary. There is no automatic idle polling in this MVP."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
