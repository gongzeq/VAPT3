"""EvidenceStore backed by CMDB metadata and filesystem raw refs."""

from __future__ import annotations

import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from sqlalchemy import delete, select

from secbot.cmdb.db import get_session
from secbot.cmdb.models import EvidenceFindingLinkModel, EvidenceRecordModel
from secbot.evidence.sanitiser import sanitise_with_status

EvidenceType = Literal["http", "screenshot", "log", "cmd_output", "dom", "har", "other"]
LinkRole = Literal["primary", "supporting", "rebuttal"]

VALID_EVIDENCE_TYPES = frozenset(
    {"http", "screenshot", "log", "cmd_output", "dom", "har", "other"}
)
VALID_LINK_ROLES = frozenset({"primary", "supporting", "rebuttal"})
_SAFE_SEGMENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    chat_id: str
    source_tool: str
    evidence_type: str
    summary: str
    raw_ref: str | None
    sanitised: bool
    sensitive_keys: tuple[str, ...]
    created_at: float
    size_bytes: int


def _record_from_model(row: EvidenceRecordModel) -> EvidenceRecord:
    return EvidenceRecord(
        id=row.id,
        chat_id=row.chat_id,
        source_tool=row.source_tool,
        evidence_type=row.evidence_type,
        summary=row.summary,
        raw_ref=row.raw_ref,
        sanitised=bool(row.sanitised),
        sensitive_keys=tuple(row.sensitive_keys or ()),
        created_at=float(row.created_at),
        size_bytes=row.size_bytes,
    )


def _safe_chat_segment(chat_id: str) -> str:
    """Return a single filesystem segment for an untrusted chat id."""
    if (
        chat_id
        and chat_id not in {".", ".."}
        and all(ch in _SAFE_SEGMENT_CHARS for ch in chat_id)
    ):
        return chat_id
    digest = sha256(chat_id.encode("utf-8", errors="surrogatepass")).hexdigest()[:16]
    return f"chat-{digest}"


class EvidenceStore:
    """Store evidence metadata in CMDB and raw bytes under an fs root."""

    def __init__(self, fs_root: Path) -> None:
        self.fs_root = Path(fs_root).resolve()

    async def put(
        self,
        chat_id: str,
        *,
        source_tool: str,
        evidence_type: str,
        summary: str,
        raw_bytes: bytes | None = None,
        sensitive_keys: Iterable[str] = (),
    ) -> str:
        """Persist evidence metadata and optional raw bytes, returning evidence_id."""
        self._validate_put(chat_id, source_tool, evidence_type, summary)
        evidence_id = str(uuid.uuid4()).replace("-", "")[:12]
        key_list = tuple(dict.fromkeys(str(key) for key in sensitive_keys if str(key)))
        sanitised = False
        raw_ref: str | None = None
        size_bytes = len(raw_bytes or b"")

        if raw_bytes is not None:
            bytes_to_write = raw_bytes
            sanitised_bytes, changed = sanitise_with_status(raw_bytes, key_list)
            if changed:
                bytes_to_write = sanitised_bytes
                sanitised = True
            raw_ref = self._write_raw(chat_id, evidence_id, evidence_type, bytes_to_write)

        row = EvidenceRecordModel(
            id=evidence_id,
            chat_id=chat_id,
            source_tool=source_tool,
            evidence_type=evidence_type,
            summary=summary,
            raw_ref=raw_ref,
            sanitised=1 if sanitised else 0,
            sensitive_keys=list(key_list) or None,
            created_at=time.time(),
            size_bytes=size_bytes,
        )
        async with get_session() as session:
            session.add(row)
        return evidence_id

    async def get(self, evidence_id: str) -> EvidenceRecord | None:
        async with get_session() as session:
            row = await session.get(EvidenceRecordModel, evidence_id)
            return _record_from_model(row) if row is not None else None

    async def link(
        self,
        evidence_id: str,
        finding_id: str,
        *,
        role: LinkRole = "primary",
    ) -> None:
        if role not in VALID_LINK_ROLES:
            raise ValueError("role must be primary/supporting/rebuttal")
        async with get_session() as session:
            exists = await session.get(EvidenceRecordModel, evidence_id)
            if exists is None:
                raise ValueError(f"unknown evidence_id: {evidence_id}")
            link = EvidenceFindingLinkModel(
                evidence_id=evidence_id,
                finding_id=finding_id,
                link_role=role,
            )
            await session.merge(link)

    async def find_for(self, finding_id: str) -> list[EvidenceRecord]:
        async with get_session() as session:
            stmt = (
                select(EvidenceRecordModel)
                .join(EvidenceFindingLinkModel)
                .where(EvidenceFindingLinkModel.finding_id == finding_id)
                .order_by(EvidenceRecordModel.created_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_record_from_model(row) for row in rows]

    async def gc(self, chat_id: str, *, before: float) -> int:
        """Remove evidence older than ``before`` for a chat, including raw files."""
        async with get_session() as session:
            stmt = select(EvidenceRecordModel).where(
                EvidenceRecordModel.chat_id == chat_id,
                EvidenceRecordModel.created_at < before,
            )
            rows = (await session.execute(stmt)).scalars().all()
            count = len(rows)
            for row in rows:
                if row.raw_ref:
                    self._remove_raw(row.raw_ref)
            await session.execute(
                delete(EvidenceRecordModel).where(
                    EvidenceRecordModel.chat_id == chat_id,
                    EvidenceRecordModel.created_at < before,
                )
            )
        chat_dir = self.fs_root / _safe_chat_segment(chat_id)
        if chat_dir.exists() and not any(chat_dir.iterdir()):
            chat_dir.rmdir()
        return count

    def raw_path(self, raw_ref: str) -> Path:
        """Resolve a stored relative raw_ref to an absolute path."""
        path = (self.fs_root / raw_ref).resolve()
        try:
            path.relative_to(self.fs_root)
        except ValueError as exc:
            raise ValueError("raw_ref escapes evidence root") from exc
        return path

    def _write_raw(
        self,
        chat_id: str,
        evidence_id: str,
        evidence_type: str,
        raw_bytes: bytes,
    ) -> str | None:
        suffix = {
            "http": ".http",
            "screenshot": ".bin",
            "log": ".log",
            "cmd_output": ".txt",
            "dom": ".html",
            "har": ".har",
            "other": ".bin",
        }[evidence_type]
        rel = Path(_safe_chat_segment(chat_id)) / f"{evidence_id}{suffix}"
        try:
            target = self.fs_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw_bytes)
            return rel.as_posix()
        except OSError:
            return None

    def _remove_raw(self, raw_ref: str) -> None:
        path = self.raw_path(raw_ref)
        try:
            if path.exists():
                path.unlink()
        except (OSError, ValueError):
            return
        parent = path.parent
        while parent != self.fs_root and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    @staticmethod
    def _validate_put(
        chat_id: str,
        source_tool: str,
        evidence_type: str,
        summary: str,
    ) -> None:
        for field, value in {
            "chat_id": chat_id,
            "source_tool": source_tool,
            "summary": summary,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
        if evidence_type not in VALID_EVIDENCE_TYPES:
            raise ValueError("evidence_type must be http/screenshot/log/cmd_output/dom/har/other")
        if len(summary) > 200:
            raise ValueError("summary must be <= 200 chars")

    def drop_chat_fs(self, chat_id: str) -> None:
        """Best-effort hard delete of raw evidence for a chat."""
        shutil.rmtree(self.fs_root / _safe_chat_segment(chat_id), ignore_errors=True)
