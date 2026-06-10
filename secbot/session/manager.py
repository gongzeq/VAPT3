"""Session management for conversation history."""

import json
import os
import shutil
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from secbot.config.paths import get_legacy_sessions_dir
from secbot.utils.helpers import (
    ensure_dir,
    estimate_message_tokens,
    find_legal_message_start,
    image_placeholder_text,
    safe_filename,
)

FILE_MAX_MESSAGES = 2000
ASSET_AUTO_MANAGEMENT_KEY = "asset_auto_management"


@dataclass
class Session:
    """A conversation session."""

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    @staticmethod
    def _annotate_message_time(message: dict[str, Any], content: Any) -> Any:
        """Expose persisted turn timestamps to the model for relative-date reasoning.

        Annotating *every* assistant turn trains the model (via in-context
        demonstrations) to start its own replies with the same
        ``[Message Time: ...]`` prefix, which leaks metadata back to the user.
        We therefore only annotate:

        * ``user`` turns — needed so the model can pin the conversation in time.
        * proactive deliveries (``_channel_delivery=True``) — cron / heartbeat
          assistant pushes that may sit hours away from the next user reply,
          and are too infrequent to act as parroting demonstrations.
        """
        timestamp = message.get("timestamp")
        if not timestamp or not isinstance(content, str):
            return content
        role = message.get("role")
        if role == "user":
            pass
        elif role == "assistant" and message.get("_channel_delivery"):
            pass
        else:
            return content
        return f"[Message Time: {timestamp}]\n{content}"

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(
        self,
        max_messages: int = 120,
        *,
        max_tokens: int = 0,
        include_timestamps: bool = False,
    ) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input.

        History is sliced by message count first (``max_messages``), then by
        token budget from the tail (``max_tokens``) when provided.
        """
        unconsolidated = self.messages[self.last_consolidated:]
        max_messages = max_messages if max_messages > 0 else 120
        sliced = unconsolidated[-max_messages:]

        # Avoid starting mid-turn when possible, except for proactive
        # assistant deliveries that the user may be replying to.
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                start = i
                if i > 0 and sliced[i - 1].get("_channel_delivery"):
                    start = i - 1
                sliced = sliced[start:]
                break

        # Drop orphan tool results at the front.
        start = find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            # Skip UI-only agent events so they do not pollute the LLM context.
            if message.get("_kind") == "agent_event":
                continue
            content = message.get("content", "")
            # Synthesize an ``[image: path]`` breadcrumb from the persisted
            # ``media`` kwarg so LLM replay still sees *something* where the
            # image used to be. Without this, an image-only user turn
            # replays as an empty user message — the assistant's reply then
            # looks like it's responding to nothing.
            media = message.get("media")
            if isinstance(media, list) and media and isinstance(content, str):
                breadcrumbs = "\n".join(
                    image_placeholder_text(p) for p in media if isinstance(p, str) and p
                )
                content = f"{content}\n{breadcrumbs}" if content else breadcrumbs
            if include_timestamps:
                content = self._annotate_message_time(message, content)
            entry: dict[str, Any] = {"role": message["role"], "content": content}
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in message:
                    entry[key] = message[key]
            # Strip reasoning_content / thinking_blocks from replay — the
            # LLM's chain-of-thought from a completed turn is never needed
            # in future replay; only the chosen actions (tool_calls) and
            # their outcomes matter.  This alone can reduce orchestrator
            # replay tokens by 30-50%.
            out.append(entry)

        if max_tokens > 0 and out:
            kept: list[dict[str, Any]] = []
            used = 0
            for message in reversed(out):
                tokens = estimate_message_tokens(message)
                if kept and used + tokens > max_tokens:
                    break
                kept.append(message)
                used += tokens
            kept.reverse()

            # Keep history aligned to the first visible user turn.
            first_user = next((i for i, m in enumerate(kept) if m.get("role") == "user"), None)
            if first_user is not None:
                kept = kept[first_user:]
            else:
                # Tight token budgets can otherwise leave assistant-only tails.
                # If a user turn exists in the unsliced output, recover the
                # nearest one even if it slightly exceeds the token budget.
                recovered_user = next(
                    (i for i in range(len(out) - 1, -1, -1) if out[i].get("role") == "user"),
                    None,
                )
                if recovered_user is not None:
                    kept = out[recovered_user:]

            # And keep a legal tool-call boundary at the front.
            start = find_legal_message_start(kept)
            if start:
                kept = kept[start:]
            out = kept
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()

    def retain_recent_legal_suffix(self, max_messages: int) -> None:
        """Keep a legal recent suffix constrained by a hard message cap."""
        if max_messages <= 0:
            self.clear()
            return
        if len(self.messages) <= max_messages:
            return

        retained = list(self.messages[-max_messages:])

        # Prefer starting at a user turn when one exists within the tail.
        first_user = next((i for i, m in enumerate(retained) if m.get("role") == "user"), None)
        if first_user is not None:
            retained = retained[first_user:]
        else:
            # If the tail is assistant/tool-only, anchor to the latest user in
            # the full session and take a capped forward window from there.
            latest_user = next(
                (i for i in range(len(self.messages) - 1, -1, -1)
                 if self.messages[i].get("role") == "user"),
                None,
            )
            if latest_user is not None:
                retained = list(self.messages[latest_user: latest_user + max_messages])

        # Mirror get_history(): avoid persisting orphan tool results at the front.
        start = find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        # Hard-cap guarantee: never keep more than max_messages.
        if len(retained) > max_messages:
            retained = retained[-max_messages:]
            start = find_legal_message_start(retained)
            if start:
                retained = retained[start:]

        dropped = len(self.messages) - len(retained)
        self.messages = retained
        self.last_consolidated = max(0, self.last_consolidated - dropped)
        self.updated_at = datetime.now()

    def enforce_file_cap(
        self,
        on_archive: Any = None,
        limit: int = FILE_MAX_MESSAGES,
    ) -> None:
        """Bound session message growth by archiving and trimming old prefixes."""
        if limit <= 0 or len(self.messages) <= limit:
            return

        before = list(self.messages)
        before_last_consolidated = self.last_consolidated
        before_count = len(before)
        self.retain_recent_legal_suffix(limit)
        dropped_count = before_count - len(self.messages)
        if dropped_count <= 0:
            return

        dropped = before[:dropped_count]
        already_consolidated = min(before_last_consolidated, dropped_count)
        archive_chunk = dropped[already_consolidated:]
        if archive_chunk and on_archive:
            on_archive(archive_chunk)
        logger.info(
            "Session file cap hit for {}: dropped {}, raw-archived {}, kept {}",
            self.key,
            dropped_count,
            len(archive_chunk),
            len(self.messages),
        )


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    @staticmethod
    def safe_key(key: str) -> str:
        """Public helper used by HTTP handlers to map an arbitrary key to a stable filename stem."""
        return safe_filename(key.replace(":", "_"))

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        return self.sessions_dir / f"{self.safe_key(key)}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.secbot/sessions/)."""
        return self.legacy_sessions_dir / f"{self.safe_key(key)}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            updated_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        updated_at = datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered session {} from corrupt file ({} messages)", key, len(repaired.messages))
            return repaired

    def _repair(self, key: str) -> Session | None:
        """Attempt to recover a session from a corrupt JSONL file."""
        path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated = 0
            skipped = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1
                        continue

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        if data.get("created_at"):
                            with suppress(ValueError, TypeError):
                                created_at = datetime.fromisoformat(data["created_at"])
                        if data.get("updated_at"):
                            with suppress(ValueError, TypeError):
                                updated_at = datetime.fromisoformat(data["updated_at"])
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            if skipped:
                logger.warning("Skipped {} corrupt lines in session {}", skipped, key)

            if not messages and not metadata:
                return None

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Repair failed for session {}: {}", key, e)
            return None

    @staticmethod
    def _session_payload(session: Session) -> dict[str, Any]:
        return {
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "messages": session.messages,
        }

    def save(self, session: Session, *, fsync: bool = False) -> None:
        """Save a session to disk atomically.

        When *fsync* is ``True`` the final file and its parent directory are
        explicitly flushed to durable storage.  This is intentionally off by
        default (the OS page-cache is sufficient for normal operation) but
        should be enabled during graceful shutdown so that filesystems with
        write-back caching (e.g. rclone VFS, NFS, FUSE mounts) do not lose
        the most recent writes.
        """
        path = self._get_session_path(session.key)
        tmp_path = path.with_suffix(".jsonl.tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                metadata_line = {
                    "_type": "metadata",
                    "key": session.key,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "metadata": session.metadata,
                    "last_consolidated": session.last_consolidated
                }
                f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
                for msg in session.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())

            os.replace(tmp_path, path)

            if fsync:
                # fsync the directory so the rename is durable.
                # On Windows, opening a directory with O_RDONLY raises
                # PermissionError — skip the dir sync there (NTFS
                # journals metadata synchronously).
                with suppress(PermissionError):
                    fd = os.open(str(path.parent), os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        self._cache[session.key] = session

    def flush_all(self) -> int:
        """Re-save every cached session with fsync for durable shutdown.

        Returns the number of sessions flushed.  Errors on individual
        sessions are logged but do not prevent other sessions from being
        flushed.
        """
        flushed = 0
        for key, session in list(self._cache.items()):
            try:
                self.save(session, fsync=True)
                flushed += 1
            except Exception:
                logger.warning("Failed to flush session {}", key, exc_info=True)
        return flushed

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def delete_session(self, key: str) -> bool:
        """Remove a session from disk and the in-memory cache.

        Returns True if a JSONL file was found and unlinked.
        """
        path = self._get_session_path(key)
        self.invalidate(key)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as e:
            logger.warning("Failed to delete session file {}: {}", path, e)
            return False

    def set_archived(self, key: str, archived: bool) -> bool:
        """Flip the ``archived`` metadata flag on an existing session.

        Returns ``True`` on success, ``False`` if no session file exists for
        *key* (caller surfaces a 404). Idempotent: calling with the current
        value still rewrites the file and bumps no other metadata.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return False
        session = self.get_or_create(key)
        session.metadata["archived"] = bool(archived)
        self.save(session)
        return True

    def get_asset_auto_management(self, key: str) -> bool:
        """Return whether this session may update Managed Assets.

        The flag defaults off. Backend CMDB ingestion uses this as the source
        of truth, so a stale or missing WebUI switch state cannot permit writes.
        """

        session = self.get_or_create(key)
        return bool(session.metadata.get(ASSET_AUTO_MANAGEMENT_KEY, False))

    def set_asset_auto_management(self, key: str, enabled: bool) -> bool:
        """Set the session-scoped Managed Asset ingestion switch."""

        session = self.get_or_create(key)
        session.metadata[ASSET_AUTO_MANAGEMENT_KEY] = bool(enabled)
        self.save(session)
        return bool(enabled)

    def read_session_file(self, key: str) -> dict[str, Any] | None:
        """Load a session from disk without caching; intended for read-only HTTP endpoints.

        Returns ``{"key", "created_at", "updated_at", "metadata", "messages"}`` or
        ``None`` when the session file does not exist or fails to parse.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return None
        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: str | None = None
            updated_at: str | None = None
            stored_key: str | None = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = data.get("created_at")
                        updated_at = data.get("updated_at")
                        stored_key = data.get("key")
                    else:
                        messages.append(data)
            return {
                "key": stored_key or key,
                "created_at": created_at,
                "updated_at": updated_at,
                "metadata": metadata,
                "messages": messages,
            }
        except Exception as e:
            logger.warning("Failed to read session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered read-only session view {} from corrupt file", key)
                return self._session_payload(repaired)
            return None

    @staticmethod
    def _compute_session_rollups(
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute scan metadata and rollups from persisted JSONL messages.

        Returns a dict with: ``scan_type``, ``target``, ``status``,
        ``findings`` (severity rollup), ``tokens`` (usage rollup),
        ``duration_ms``.

        This is a best-effort computation — fields default to ``null`` / zero
        when data is unavailable. Results are intended for caching in the
        session metadata line so subsequent reads skip the full-file scan.
        """
        scan_type: str | None = None
        target: str | None = None
        status = "finished"  # default for completed sessions

        findings = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
        tokens = {"input": 0, "output": 0, "cached": 0}

        first_created: str | None = None
        last_created: str | None = None

        for msg in messages:
            if not isinstance(msg, dict):
                continue

            # Track timestamps for duration computation.
            ts = msg.get("timestamp")
            if isinstance(ts, str) and ts:
                if first_created is None:
                    first_created = ts
                last_created = ts

            # Agent events: count findings from blackboard entries.
            if msg.get("_kind") == "agent_event":
                ae = msg.get("agent_event")
                if isinstance(ae, dict):
                    ae_type = ae.get("type")

                    # Blackboard entries: findings AND milestones both count.
                    if ae_type == "blackboard_entry":
                        kind = ae.get("kind")
                        text = ae.get("text", "")
                        is_finding = kind == "finding" or (isinstance(text, str) and "[finding" in text.lower())
                        is_milestone = kind == "milestone" or (isinstance(text, str) and "[milestone" in text.lower())
                        if is_finding or is_milestone:
                            findings["total"] += 1
                            # Try to extract severity from text prefix / content.
                            lower = text.lower() if isinstance(text, str) else ""
                            for sev in ("critical", "high", "medium", "low"):
                                if sev in lower:
                                    findings[sev] += 1
                                    break
                            else:
                                findings["medium"] += 1  # default severity

                    # Orchestrator plan can hint at scan_type.
                    if ae_type == "orchestrator_plan":
                        steps = ae.get("steps")
                        if isinstance(steps, list):
                            step_text = " ".join(
                                str(s.get("title", "")) for s in steps if isinstance(s, dict)
                            ).lower()
                            if any(kw in step_text for kw in ("port", "scan", "nmap")):
                                scan_type = scan_type or "full"
                            elif "vuln" in step_text:
                                scan_type = scan_type or "vuln"
                            elif "weak" in step_text or "password" in step_text:
                                scan_type = scan_type or "weakpwd"
                            elif "asset" in step_text:
                                scan_type = scan_type or "asset"

            # Tool messages may contain scan targets.
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str):
                    lower = content.lower()
                    if "target" in lower and not target:
                        # Heuristic: look for IP/CIDR patterns.
                        import re
                        ip_match = re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?", content)
                        if ip_match:
                            target = ip_match.group(0)

            # User messages: infer scan_type from first message.
            if msg.get("role") == "user" and not msg.get("injected_event"):
                content = msg.get("content", "")
                if isinstance(content, str) and not target:
                    import re
                    ip_match = re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?", content)
                    if ip_match:
                        target = ip_match.group(0)
                        if not scan_type:
                            lower = content.lower()
                            if any(kw in lower for kw in ("full scan", "全量", "full")):
                                scan_type = "full"
                            elif any(kw in lower for kw in ("vuln", "漏洞")):
                                scan_type = "vuln"
                            elif any(kw in lower for kw in ("weak", "弱口令", "password")):
                                scan_type = "weakpwd"
                            elif any(kw in lower for kw in ("asset", "资产")):
                                scan_type = "asset"
                            else:
                                scan_type = "full"
                    elif not scan_type:
                        # No IP found — likely a query/conversational session.
                        if not any(
                            kw in content.lower()
                            for kw in ("scan", "扫描", "nmap", "端口", "漏")
                        ):
                            scan_type = "query"
                            target = content[:80] if content else None

        # If scan_type was never inferred, default based on whether we found a target.
        if scan_type is None:
            scan_type = "query" if target is None else "full"

        # Duration: compute from first to last message timestamp.
        duration_ms: int | None = None
        if first_created and last_created and first_created != last_created:
            try:
                from datetime import datetime as _dt
                t0 = _dt.fromisoformat(first_created)
                t1 = _dt.fromisoformat(last_created)
                duration_ms = int((t1 - t0).total_seconds() * 1000)
                if duration_ms < 0:
                    duration_ms = None
            except Exception:
                duration_ms = None

        # Tokens: sum persisted per-turn usage from session metadata.
        if metadata:
            turn_usage = metadata.get("_turn_usage")
            if isinstance(turn_usage, list):
                for entry in turn_usage:
                    if isinstance(entry, dict):
                        tokens["input"] += entry.get("input", 0)
                        tokens["output"] += entry.get("output", 0)
                        tokens["cached"] += entry.get("cached", 0)

        return {
            "scan_type": scan_type,
            "target": target,
            "status": status,
            "findings": findings,
            "tokens": tokens,
            "duration_ms": duration_ms,
        }

    @staticmethod
    def _enrich_from_cmdb(target: str | None, created_at: str | None, rollups: dict[str, Any], session_key: str | None = None) -> dict[str, Any]:
        """Enrich session rollups with real CMDB data when a matching scan exists.

        Queries ``~/.secbot/cmdb.sqlite3`` directly (sync sqlite3) to find scans
        matching the session. Matching strategies (in priority order):

        1. Session key → scan ID mapping (``websocket:XXX`` → ``websocket_XXX``).
        2. Target IP/hostname LIKE match against ``scan.target``.

        When a match is found, the vulnerability severity counts from the CMDB
        replace the JSONL-inferred rollup.

        Returns the (possibly updated) rollups dict.
        """
        if not target and not session_key:
            return rollups

        scan_id: str | None = None
        try:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path

            db_path = _Path.home() / ".secbot" / "cmdb.sqlite3"
            if not db_path.exists():
                return rollups

            conn = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = _sqlite3.Row
            cur = conn.cursor()

            best_scan = None

            # Strategy 1: Match by session key → scan ID.
            if session_key:
                derived_scan_id = session_key.replace(":", "_", 1)
                cur.execute(
                    "SELECT id, target, status, started_at, finished_at, scope_json "
                    "FROM scan WHERE id = ?",
                    (derived_scan_id,),
                )
                best_scan = cur.fetchone()

            # Strategy 2: Match by target IP/hostname.
            if best_scan is None and target:
                like_pat = f"%{target}%"
                cur.execute(
                    "SELECT id, target, status, started_at, finished_at, scope_json "
                    "FROM scan WHERE target LIKE ? ORDER BY started_at DESC LIMIT 1",
                    (like_pat,),
                )
                best_scan = cur.fetchone()

            if best_scan is not None:
                scan_id = best_scan["id"]
                scan_status = best_scan["status"]

                # Update status from CMDB if available.
                if scan_status and scan_status != "queued":
                    rollups["status"] = "running" if scan_status == "running" else "finished"

                # Count vulnerabilities by severity for this scan's assets.
                cur.execute(
                    "SELECT v.severity, COUNT(*) as cnt "
                    "FROM vulnerability v "
                    "JOIN asset a ON v.asset_id = a.id "
                    "WHERE a.scan_id = ? "
                    "GROUP BY v.severity",
                    (scan_id,),
                )
                vuln_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
                for row in cur.fetchall():
                    sev = row["severity"]
                    cnt = row["cnt"]
                    if sev in vuln_counts:
                        vuln_counts[sev] = cnt
                    vuln_counts["total"] += cnt

                # Only replace JSONL findings if CMDB has data.
                if vuln_counts["total"] > 0:
                    rollups["findings"] = vuln_counts

                # Update target from scan if session target is just an IP fragment.
                scan_target = best_scan["target"]
                if scan_target and scan_target != scan_id:
                    rollups["target"] = scan_target

                # Infer scan type from scan scope if available.
                scope_raw = best_scan["scope_json"]
                if scope_raw:
                    try:
                        scope = json.loads(scope_raw) if isinstance(scope_raw, str) else scope_raw
                        if isinstance(scope, dict):
                            st = scope.get("scan_type") or scope.get("type")
                            if isinstance(st, str) and st:
                                rollups["scan_type"] = st
                    except Exception:
                        pass

                # Query report_meta for this scan.
                try:
                    cur.execute(
                        "SELECT id, title, type, status, download_path, critical_count "
                        "FROM report_meta WHERE scan_id = ? ORDER BY created_at DESC",
                        (scan_id,),
                    )
                    reports = [dict(r) for r in cur.fetchall()]
                    if reports:
                        rollups["reports"] = reports
                except Exception:
                    pass

                conn.close()
            else:
                conn.close()
        except Exception:
            # CMDB enrichment is best-effort; fall back to JSONL data.
            pass

        # Fallback: scan filesystem for generated reports when CMDB
        # report_meta is empty.  Reports live under
        # ``~/.secbot/workspace/.secbot/scans/<scan_id>/report/``.
        if not rollups.get("reports"):
            try:
                from pathlib import Path as _P
                scans_root = _P.home() / ".secbot" / "workspace" / ".secbot" / "scans"

                # Candidate scan dirs: the matched scan_id first, then any
                # scan whose directory name contains the target IP/hostname.
                candidate_ids: list[str] = []
                if scan_id:
                    candidate_ids.append(scan_id)
                if session_key:
                    derived = session_key.replace(":", "_", 1)
                    if derived not in candidate_ids:
                        candidate_ids.append(derived)
                if target and scans_root.is_dir():
                    try:
                        for d in scans_root.iterdir():
                            if d.is_dir() and d.name not in candidate_ids and target in d.name:
                                candidate_ids.append(d.name)
                    except OSError:
                        pass

                for cid in candidate_ids:
                    scan_dir = scans_root / cid / "report"
                    if not scan_dir.is_dir():
                        continue
                    fs_reports = []
                    for rpt in sorted(scan_dir.iterdir()):
                        if rpt.is_file() and rpt.suffix in (".html", ".pdf"):
                            fmt = "pdf" if rpt.suffix == ".pdf" else "html"
                            fs_reports.append({
                                "id": rpt.stem,
                                "title": f"{cid} {fmt.upper()} Report",
                                "type": fmt,
                                "status": "completed",
                                "download_path": f"/api/scan-reports/{cid}/download",
                                "critical_count": 0,
                            })
                    if fs_reports:
                        rollups["reports"] = fs_reports
                        break
            except Exception:
                pass

        return rollups

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions with extended fields for the SessionsPage.

        Returns:
            List of session info dicts including ``scan_type``, ``target``,
            ``status``, ``findings``, ``tokens``, ``duration_ms`` in addition
            to the base fields (``key``, ``created_at``, ``updated_at``,
            ``title``, ``archived``, ``preview``).
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            fallback_key = path.stem.replace("_", ":", 1)
            try:
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if not first_line:
                        continue
                    data = json.loads(first_line)
                    if data.get("_type") != "metadata":
                        continue

                    key = data.get("key") or path.stem.replace("_", ":", 1)
                    metadata = data.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    title = metadata.get("title")
                    archived = bool(metadata.get("archived"))
                    created_at = data.get("created_at")
                    updated_at = data.get("updated_at")

                    # Check for cached rollups in metadata.
                    cached_rollups = metadata.get("_rollups")
                    if isinstance(cached_rollups, dict) and cached_rollups.get("_v") == 2:
                        # Use cached rollups — skip the full-file scan.
                        preview = self._first_user_preview(f)
                        # Auto-populate title from first user message when empty.
                        display_title = title if isinstance(title, str) and title.strip() else (preview[:80] if preview else "")
                        rollups = {
                            "scan_type": cached_rollups.get("scan_type"),
                            "target": cached_rollups.get("target"),
                            "status": cached_rollups.get("status", "finished"),
                            "findings": cached_rollups.get("findings", {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}),
                            "tokens": cached_rollups.get("tokens", {"input": 0, "output": 0, "cached": 0}),
                            "duration_ms": cached_rollups.get("duration_ms"),
                        }
                        # Enrich with CMDB data (may override findings if real vuln data exists).
                        rollups = self._enrich_from_cmdb(rollups.get("target"), created_at, rollups, session_key=key)
                        sessions.append({
                            "key": key,
                            "created_at": created_at,
                            "updated_at": updated_at,
                            "title": display_title,
                            "archived": archived,
                            "preview": preview,
                            "path": str(path),
                            "scan_type": rollups.get("scan_type"),
                            "target": rollups.get("target"),
                            "status": rollups.get("status", "finished"),
                            "findings": rollups.get("findings", {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}),
                            "tokens": rollups.get("tokens", {"input": 0, "output": 0, "cached": 0}),
                            "duration_ms": rollups.get("duration_ms"),
                            "reports": rollups.get("reports", []),
                        })
                    else:
                        # No cached rollups — read the full file to compute.
                        messages: list[dict[str, Any]] = []
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                row = json.loads(line)
                                messages.append(row)
                            except Exception:
                                continue

                        preview = self._first_user_preview_from_messages(messages)
                        rollups = self._compute_session_rollups(messages, metadata=metadata)

                        # Override with metadata-set values if present.
                        meta_scan_type = metadata.get("scan_type")
                        meta_target = metadata.get("target")
                        meta_status = metadata.get("status")
                        if isinstance(meta_scan_type, str):
                            rollups["scan_type"] = meta_scan_type
                        if isinstance(meta_target, str):
                            rollups["target"] = meta_target
                        if isinstance(meta_status, str):
                            rollups["status"] = meta_status

                        # Enrich with CMDB data (real vulnerability counts).
                        rollups = self._enrich_from_cmdb(rollups.get("target"), created_at, rollups, session_key=key)

                        # Cache enriched rollups in metadata for next read.
                        try:
                            metadata["_rollups"] = {**rollups, "_v": 2}
                            data["metadata"] = metadata
                            with open(path, "w", encoding="utf-8") as wf:
                                wf.write(json.dumps(data, ensure_ascii=False) + "\n")
                                for msg in messages:
                                    wf.write(json.dumps(msg, ensure_ascii=False) + "\n")
                        except Exception:
                            pass  # caching is best-effort

                        # Auto-populate title from first user message when empty.
                        display_title = title if isinstance(title, str) and title.strip() else (preview[:80] if preview else "")

                        sessions.append({
                            "key": key,
                            "created_at": created_at,
                            "updated_at": updated_at,
                            "title": display_title,
                            "archived": archived,
                            "preview": preview,
                            "path": str(path),
                            "scan_type": rollups["scan_type"],
                            "target": rollups["target"],
                            "status": rollups["status"],
                            "findings": rollups["findings"],
                            "tokens": rollups["tokens"],
                            "duration_ms": rollups["duration_ms"],
                            "reports": rollups.get("reports", []),
                        })
            except Exception:
                repaired = self._repair(fallback_key)
                if repaired is not None:
                    rollups = self._compute_session_rollups(repaired.messages, metadata=repaired.metadata)
                    repaired_preview = self._first_user_preview_from_messages(repaired.messages)
                    repaired_title = repaired.metadata.get("title")
                    # Enrich with CMDB data.
                    rollups = self._enrich_from_cmdb(rollups.get("target"), None, rollups, session_key=repaired.key)
                    display_title = (
                        repaired_title
                        if isinstance(repaired_title, str) and repaired_title.strip()
                        else (repaired_preview[:80] if repaired_preview else "")
                    )
                    sessions.append({
                        "key": repaired.key,
                        "created_at": repaired.created_at.isoformat(),
                        "updated_at": repaired.updated_at.isoformat(),
                        "title": display_title,
                        "archived": bool(repaired.metadata.get("archived")),
                        "preview": repaired_preview,
                        "path": str(path),
                        "scan_type": rollups["scan_type"],
                        "target": rollups["target"],
                        "status": rollups["status"],
                        "findings": rollups["findings"],
                        "tokens": rollups["tokens"],
                        "duration_ms": rollups["duration_ms"],
                        "reports": rollups.get("reports", []),
                    })
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    @staticmethod
    def _is_subagent_result_row(row: dict[str, Any]) -> bool:
        if row.get("injected_event") == "subagent_result":
            return True
        content = row.get("content")
        if isinstance(content, str):
            stripped = content.lstrip()
            return stripped.startswith("[Subagent '") or stripped.startswith('[Subagent "')
        return False

    @staticmethod
    def _first_user_preview(file_obj: Any) -> str:
        """Scan an already-opened JSONL file for the first user message.

        Returns a compact one-line preview used as the sidebar title. The
        caller is expected to have already consumed the leading metadata
        line so the iteration starts with the first message row.
        """
        for line in file_obj:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("role") != "user":
                continue
            if SessionManager._is_subagent_result_row(row):
                continue
            content = row.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            return text.strip()
        return ""

    @staticmethod
    def _first_user_preview_from_messages(
        messages: list[dict[str, Any]],
    ) -> str:
        """Equivalent of ``_first_user_preview`` for in-memory message lists."""
        for row in messages:
            if not isinstance(row, dict) or row.get("role") != "user":
                continue
            if SessionManager._is_subagent_result_row(row):
                continue
            content = row.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            return text.strip()
        return ""
