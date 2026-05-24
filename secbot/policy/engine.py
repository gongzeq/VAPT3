"""Unified policy checks for tool invocation routing.

Spec: `.trellis/spec/backend/policy-engine.md`.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import shlex
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from secbot.agents.high_risk import build_confirmation_payload
from secbot.security.network import validate_url_target
from secbot.skills.metadata import SkillMetadata

_CURL_VALUE_OPTIONS = frozenset({
    "-A",
    "--user-agent",
    "-b",
    "--cookie",
    "--cookie-raw",
    "-c",
    "--cookie-jar",
    "--cacert",
    "--cert",
    "-d",
    "--data",
    "--data-ascii",
    "--data-binary",
    "--data-raw",
    "--data-urlencode",
    "-F",
    "--form",
    "--form-string",
    "-H",
    "--header",
    "--key",
    "-m",
    "--max-time",
    "-o",
    "--output",
    "-u",
    "--user",
    "-w",
    "--write-out",
    "-X",
    "--request",
    "--connect-timeout",
})
_CURL_NETWORK_OVERRIDE_OPTIONS = frozenset({
    "--connect-to",
    "--preproxy",
    "--proxy",
    "--resolve",
    "--unix-socket",
})
_CURL_LOCAL_IO_OPTIONS = frozenset({
    "--cacert",
    "--capath",
    "--config",
    "--cookie-jar",
    "--cert",
    "--key",
    "--libcurl",
    "--netrc",
    "--netrc-file",
    "--netrc-optional",
    "--output",
    "--output-dir",
    "--remote-name",
    "--proxy-cacert",
    "--proxy-capath",
    "--proxy-cert",
    "--proxy-key",
    "--upload-file",
    "-E",
    "-K",
    "-O",
    "-T",
    "-c",
    "-o",
})
_CURL_LOCAL_IO_SHORT_PREFIXES = ("-E", "-K", "-T", "-c", "-o")
_CURL_FILE_VALUE_OPTIONS = frozenset({
    "--data",
    "--data-ascii",
    "--data-binary",
    "--data-raw",
    "--data-urlencode",
    "--form",
    "--header",
    "-F",
    "-H",
    "-d",
})
_CURL_COOKIE_OPTIONS = frozenset({"-b", "--cookie", "--cookie-raw"})

Action = Literal[
    "tool.invoke",
    "skill.invoke",
    "worker.spawn",
    "blackboard.write",
    "exec.shell",
    "http.fetch",
    "fs.read",
    "fs.write",
    "fs.delete",
    "approval.request",
    "report.publish",
    "blackboard.read",
    "message",
]
CallerKind = Literal["pi", "worker", "system"]
Verdict = Literal["allow", "need_approval", "deny"]


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Result returned by `PolicyEngine.check`."""

    verdict: Verdict
    rule: str | None = None
    reason: str | None = None
    suggest: str | None = None
    approval_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ScopeContract:
    """Minimal PR2 scope contract used by PolicyEngine.

    Scope atoms support IP/CIDR, exact domains, wildcard domains, and URL
    prefixes. Empty scope means degraded mode: allow and rely on existing tool
    guards.
    """

    in_scope: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    auth_window_start: datetime | None = None
    auth_window_end: datetime | None = None
    forbidden_actions: frozenset[Action] = frozenset()
    risk_profile: Literal["passive", "active", "intrusive"] = "active"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "ScopeContract | None":
        if not data:
            return None
        in_scope = tuple(str(item) for item in data.get("in_scope", ()) if str(item))
        out_of_scope = tuple(str(item) for item in data.get("out_of_scope", ()) if str(item))
        forbidden = frozenset(
            str(action) for action in data.get("forbidden_actions", ()) if str(action)
        )
        risk_profile = str(data.get("risk_profile") or "active")
        auth_window = _parse_auth_window(data)
        return cls(
            in_scope=in_scope,
            out_of_scope=out_of_scope,
            auth_window_start=auth_window.get("start"),
            auth_window_end=auth_window.get("end"),
            forbidden_actions=forbidden,  # type: ignore[arg-type]
            risk_profile=(
                risk_profile if risk_profile in {"passive", "active", "intrusive"}
                else "active"
            ),  # type: ignore[arg-type]
        )

    def is_authorized_now(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.auth_window_start and current < self.auth_window_start:
            return False
        if self.auth_window_end and current > self.auth_window_end:
            return False
        return True

    def contains(self, target: str | None) -> bool:
        if not self.in_scope:
            return True
        if not target:
            return True
        return any(_atom_matches(atom, target) for atom in self.in_scope)

    def is_explicitly_denied(self, target: str | None) -> bool:
        if not target:
            return False
        return any(_atom_matches(atom, target) for atom in self.out_of_scope)


@dataclass(frozen=True, slots=True)
class PolicyContext:
    """Per-call context supplied by the tool router."""

    caller_kind: CallerKind = "pi"
    worker_id: str | None = None
    scan_id: str = "adhoc"
    workspace: Path | None = None
    workspace_strict: bool = True
    scope: ScopeContract | None = None
    confirm: Callable[[Mapping[str, Any]], Awaitable[bool]] | None = None
    skill_metadata: SkillMetadata | None = None
    approved_skills: frozenset[str] = frozenset()
    credential_zones: Mapping[str, frozenset[str]] = field(default_factory=dict)
    budget: Any | None = None


class _SlidingWindowLimiter:
    def __init__(self, limit: int, window_sec: float = 60.0) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0
        current = now if now is not None else time.monotonic()
        bucket = self._hits[key]
        cutoff = current - self.window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False, len(bucket)
        bucket.append(current)
        return True, len(bucket)


class PolicyEngine:
    """Single policy gate for tool calls."""

    def __init__(
        self,
        *,
        worker_limit_per_minute: int = 30,
        endpoint_limit_per_minute: int = 10,
        skill_overrides_per_minute: Mapping[str, int | None] | None = None,
    ) -> None:
        self._worker_limiter = _SlidingWindowLimiter(worker_limit_per_minute)
        self._endpoint_limiter = _SlidingWindowLimiter(endpoint_limit_per_minute)
        self._skill_limiters: dict[str, _SlidingWindowLimiter] = {}
        for name, limit in (skill_overrides_per_minute or {}).items():
            if limit is not None:
                self._skill_limiters[name] = _SlidingWindowLimiter(limit)

    async def check(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext | None = None,
    ) -> PolicyDecision:
        """Run rules in spec order and return the first non-allow decision."""
        effective_ctx = ctx or PolicyContext()
        rules = (
            self._scope_rule,
            self._ssrf_rule,
            self._workspace_rule,
            self._credential_boundary_rule,
            self._caller_kind_rule,
            self._budget_rule,
            self._rate_limit_rule,
            self._destructive_rule,
        )
        for rule in rules:
            try:
                decision = rule(action, args, effective_ctx)
            except Exception as exc:  # noqa: BLE001 - fail closed at policy boundary
                return PolicyDecision(
                    "deny",
                    rule=f"{rule.__name__.lstrip('_')}_error",
                    reason=str(exc),
                    suggest="Pi: stop and ask the user how to proceed.",
                )
            if decision.verdict != "allow":
                return decision
        return PolicyDecision("allow")

    def with_context(
        self,
        context: PolicyContext | None,
        *,
        skill_metadata: SkillMetadata | None = None,
    ) -> PolicyContext:
        base = context or PolicyContext()
        if skill_metadata is None:
            return base
        return replace(base, skill_metadata=skill_metadata)

    def _caller_kind_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        if ctx.caller_kind != "worker":
            return PolicyDecision("allow")
        kind = args.get("kind")
        if action == "blackboard.write" and kind in {"finding", "phase_transition", "approval"}:
            return PolicyDecision(
                "deny",
                rule="caller_kind",
                reason=f"worker cannot blackboard.write({kind})",
                suggest="Pi: promote worker hypotheses or approvals yourself.",
            )
        if action in {"worker.spawn", "report.publish"}:
            return PolicyDecision(
                "deny",
                rule="caller_kind",
                reason=f"worker cannot {action}",
                suggest="Pi: handle this action in the main decision chain.",
            )
        return PolicyDecision("allow")

    def _scope_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        scope = ctx.scope
        if scope is None:
            return PolicyDecision("allow")
        if action in scope.forbidden_actions:
            return PolicyDecision(
                "deny",
                rule="scope_forbidden_action",
                reason=f"action {action} is forbidden by the scope contract",
                suggest="Pi: choose an allowed action or ask the user to update scope.",
            )
        if not scope.is_authorized_now():
            return PolicyDecision(
                "deny",
                rule="scope_window",
                reason="current time is outside the authorized testing window",
                suggest="Pi: wait for the authorized window or ask the user to extend it.",
            )
        if action not in {"skill.invoke", "worker.spawn", "http.fetch"}:
            return PolicyDecision("allow")
        targets = _extract_scope_targets(args)
        for target in targets:
            if scope.is_explicitly_denied(target):
                return PolicyDecision(
                    "deny",
                    rule="scope_denied",
                    reason=f"target {target} is in out_of_scope",
                    suggest="Pi: stop and notify the user; do not retry.",
                )
            if not scope.contains(target):
                return PolicyDecision(
                    "deny",
                    rule="scope",
                    reason=f"target {target} is not in scope",
                    suggest="Pi: stop and notify the user; do not retry.",
                )
        return PolicyDecision("allow")

    def _ssrf_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        if action not in {"http.fetch", "skill.invoke"}:
            return PolicyDecision("allow")
        blocked_shell = _blocked_curl_shell_syntax(args)
        if blocked_shell is not None:
            return PolicyDecision(
                "deny",
                rule="curl_safety",
                reason=f"curl command contains shell control syntax {blocked_shell!r}",
                suggest="Pi: provide one quoted curl invocation without shell operators.",
            )
        blocked_local_io = _blocked_curl_local_io(args)
        if blocked_local_io is not None:
            return PolicyDecision(
                "deny",
                rule="curl_safety",
                reason=f"curl option {blocked_local_io} can read or write local files",
                suggest="Pi: use headers/body literals only; do not read or write local files via curl.",
            )
        blocked_option = _blocked_curl_network_override(args)
        if blocked_option is not None:
            return PolicyDecision(
                "deny",
                rule="ssrf",
                reason=(
                    f"curl option {blocked_option} can override the validated "
                    "network target"
                ),
                suggest="Pi: remove network-routing overrides and fetch the explicit URL only.",
            )
        urls = _extract_urls(args)
        if not urls:
            return PolicyDecision("allow")
        for url in urls:
            ok, message = validate_url_target(url)
            if ok:
                continue
            return PolicyDecision(
                "deny",
                rule="ssrf",
                reason=message,
                suggest=(
                    "Pi: target is internal/private; require the user to whitelist "
                    "the exact IP/CIDR via tools.ssrfWhitelist."
                ),
            )
        return PolicyDecision("allow")

    def _workspace_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        if action not in {"fs.read", "fs.write", "fs.delete"}:
            return PolicyDecision("allow")
        if not ctx.workspace_strict or ctx.workspace is None:
            return PolicyDecision("allow")
        raw_path = args.get("path") or args.get("file_path") or args.get("notebook_path")
        if not raw_path:
            return PolicyDecision("allow")
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = ctx.workspace / path
        try:
            resolved = path.resolve()
            workspace = ctx.workspace.resolve()
            resolved.relative_to(workspace)
        except Exception:
            return PolicyDecision(
                "deny",
                rule="workspace",
                reason=f"path {raw_path} escapes workspace {ctx.workspace}",
                suggest="restrict file access to the configured workspace subtree",
            )
        return PolicyDecision("allow")

    def _credential_boundary_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        if action not in {"http.fetch", "skill.invoke"} or not ctx.credential_zones:
            return PolicyDecision("allow")
        creds = args.get("cookies") or args.get("auth_header") or args.get("authorization")
        if not creds:
            return PolicyDecision("allow")
        host = _extract_host(_extract_url(args) or _extract_target(args))
        if not host:
            return PolicyDecision("allow")
        cred_id = _fingerprint(creds)
        owners = ctx.credential_zones.get(host, frozenset())
        if cred_id not in owners:
            return PolicyDecision(
                "deny",
                rule="credential_boundary",
                reason=f"credential {cred_id[:8]} not authorised for {host}",
                suggest="Pi: do not reuse sessions or tokens across targets.",
            )
        return PolicyDecision("allow")

    def _rate_limit_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        if action not in {"skill.invoke", "http.fetch"}:
            return PolicyDecision("allow")

        if ctx.caller_kind == "worker":
            key = ctx.worker_id or ctx.scan_id
            ok, count = self._worker_limiter.check(key)
            if not ok:
                return PolicyDecision(
                    "deny",
                    rule="rate_limit",
                    reason=f"worker {key}: {count}/min exceeds limit",
                    suggest="Pi: sleep, checkpoint, or reduce worker tool calls.",
                )

        endpoint_url = args.get("endpoint_url")
        endpoint_param = args.get("endpoint_param")
        if endpoint_url and endpoint_param:
            key = f"{endpoint_url}|{endpoint_param}"
            ok, count = self._endpoint_limiter.check(key)
            if not ok:
                return PolicyDecision(
                    "deny",
                    rule="rate_limit",
                    reason=f"endpoint {key}: {count}/min exceeds limit",
                    suggest="Pi: wait before retrying this endpoint.",
                )

        if ctx.skill_metadata is not None:
            limiter = self._skill_limiters.get(ctx.skill_metadata.name)
            if limiter is not None:
                ok, count = limiter.check(ctx.skill_metadata.name)
                if not ok:
                    return PolicyDecision(
                        "deny",
                        rule="rate_limit",
                        reason=f"{ctx.skill_metadata.name}: {count}/min exceeds limit",
                        suggest="Pi: wait before retrying this skill.",
                    )

        return PolicyDecision("allow")

    def _destructive_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        if action not in {"skill.invoke", "exec.shell"}:
            return PolicyDecision("allow")
        meta = ctx.skill_metadata
        if meta is None or not meta.is_critical():
            return PolicyDecision("allow")
        if meta.name in ctx.approved_skills:
            return PolicyDecision("allow")
        payload = build_confirmation_payload(meta, args, ctx.scan_id)
        return PolicyDecision(
            "need_approval",
            rule="destructive",
            reason=f"{meta.name} is risk_level=critical",
            approval_payload=payload,
        )

    def _budget_rule(
        self,
        action: Action,
        args: Mapping[str, Any],
        ctx: PolicyContext,
    ) -> PolicyDecision:
        budget = ctx.budget
        if budget is None:
            return PolicyDecision("allow")
        status = _budget_status(budget, worker_id=ctx.worker_id)
        if status == "EXCEEDED":
            kind = args.get("kind")
            if action == "blackboard.write" and kind in {"summary", "phase_transition"}:
                return PolicyDecision("allow")
            if action in {"blackboard.read", "message"}:
                return PolicyDecision("allow")
            return PolicyDecision(
                "deny",
                rule="budget",
                reason="budget exhausted; write summary/phase_transition first",
                suggest="see [BUDGET_EXCEEDED] instructions",
            )
        return PolicyDecision("allow")


def policy_denied_payload(decision: PolicyDecision) -> str:
    """Serialize a policy denial as the Tool Router contract."""
    return json.dumps(
        {
            "error": "policy_denied",
            "rule": decision.rule,
            "reason": decision.reason,
            "suggest": decision.suggest,
        },
        ensure_ascii=False,
    )


def user_denied_payload(decision: PolicyDecision) -> str:
    return json.dumps(
        {
            "error": "user_denied",
            "rule": decision.rule,
            "reason": decision.reason or "user denied confirmation",
        },
        ensure_ascii=False,
    )


def _budget_status(budget: Any, *, worker_id: str | None = None) -> str | None:
    status_fn = getattr(budget, "status", None)
    if callable(status_fn):
        try:
            value = status_fn(worker_id=worker_id)
        except TypeError:
            value = status_fn()
        if worker_id:
            try:
                master_value = status_fn()
            except TypeError:
                master_value = value
            master_status = getattr(master_value, "status", master_value)
            if str(master_status) == "EXCEEDED":
                return "EXCEEDED"
    else:
        value = getattr(budget, "status", None)
    status_value = getattr(value, "status", value)
    return str(status_value) if status_value is not None else None


def _extract_target(args: Mapping[str, Any]) -> str | None:
    for key in ("target", "url", "endpoint_url", "host", "hostname", "address"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    command = args.get("command")
    if isinstance(command, str):
        url = _extract_url({"command": command})
        if url:
            return url
    return None


def _extract_scope_targets(args: Mapping[str, Any]) -> tuple[str, ...]:
    targets: list[str] = []
    for key in ("target", "url", "endpoint_url", "host", "hostname", "address"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            targets.append(value.strip())
    scope_view = args.get("scope_view")
    if isinstance(scope_view, Mapping):
        in_scope = scope_view.get("in_scope")
        if isinstance(in_scope, list):
            targets.extend(str(item).strip() for item in in_scope if str(item).strip())
        out_of_scope = scope_view.get("out_of_scope")
        if isinstance(out_of_scope, list):
            targets.extend(str(item).strip() for item in out_of_scope if str(item).strip())
    command = args.get("command")
    if isinstance(command, str):
        targets.extend(_extract_command_urls(command))
    if not targets:
        target = _extract_target(args)
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))


def _extract_url(args: Mapping[str, Any]) -> str | None:
    urls = _extract_urls(args)
    return urls[0] if urls else None


def _extract_urls(args: Mapping[str, Any]) -> tuple[str, ...]:
    urls: list[str] = []
    for key in ("url", "endpoint_url", "target"):
        value = args.get(key)
        if not isinstance(value, str):
            continue
        candidate = _normalise_url_candidate(value, allow_bare=False)
        if candidate:
            urls.append(candidate)
    command = args.get("command")
    if isinstance(command, str):
        urls.extend(_extract_command_urls(command))
    return tuple(dict.fromkeys(urls))


def _extract_command_urls(command: str) -> list[str]:
    tokens = _shell_tokens(command)
    if not tokens:
        return []
    urls: list[str] = []
    skip_next = False
    for idx, token in enumerate(tokens[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            continue
        if token == "--url":
            if idx + 1 < len(tokens):
                candidate = _normalise_url_candidate(tokens[idx + 1], allow_bare=True)
                if candidate:
                    urls.append(candidate)
            skip_next = True
            continue
        if token.startswith("--url="):
            candidate = _normalise_url_candidate(token.split("=", 1)[1], allow_bare=True)
            if candidate:
                urls.append(candidate)
            continue
        if token in _CURL_VALUE_OPTIONS:
            skip_next = True
            continue
        if any(
            token.startswith(f"{option}=")
            for option in _CURL_VALUE_OPTIONS
            if option.startswith("--")
        ):
            continue
        if token.startswith("-"):
            continue
        candidate = _normalise_url_candidate(token, allow_bare=True)
        if candidate:
            urls.append(candidate)
    return urls


def _blocked_curl_network_override(args: Mapping[str, Any]) -> str | None:
    command = args.get("command")
    if not isinstance(command, str):
        return None
    for token in _shell_tokens(command)[1:]:
        if token in _CURL_NETWORK_OVERRIDE_OPTIONS:
            return token
        for option in _CURL_NETWORK_OVERRIDE_OPTIONS:
            if token.startswith(f"{option}="):
                return option
        if token == "-x" or (token.startswith("-x") and len(token) > 2):
            return "-x"
    return None


def _blocked_curl_local_io(args: Mapping[str, Any]) -> str | None:
    command = args.get("command")
    if not isinstance(command, str):
        return None
    tokens = _shell_tokens(command)
    idx = 1
    while idx < len(tokens):
        token = tokens[idx]
        option, value = _split_curl_option(token)
        if option in _CURL_LOCAL_IO_OPTIONS:
            return option
        if any(
            token.startswith(prefix) and token != prefix
            for prefix in _CURL_LOCAL_IO_SHORT_PREFIXES
        ):
            return token[:2]
        if option in _CURL_COOKIE_OPTIONS and _curl_cookie_value_reads_file(value):
            return option
        if token in _CURL_COOKIE_OPTIONS:
            next_value = tokens[idx + 1] if idx + 1 < len(tokens) else None
            if _curl_cookie_value_reads_file(next_value):
                return token
            idx += 1
        if option in _CURL_FILE_VALUE_OPTIONS and _curl_value_reads_file(value):
            return option
        if token in _CURL_FILE_VALUE_OPTIONS:
            next_value = tokens[idx + 1] if idx + 1 < len(tokens) else None
            if _curl_value_reads_file(next_value):
                return token
            idx += 1
        if token.startswith(("-d", "-F")) and len(token) > 2:
            inline_value = token[2:]
            if _curl_value_reads_file(inline_value):
                return token[:2]
        if token.startswith("-b") and len(token) > 2:
            inline_value = token[2:]
            if _curl_cookie_value_reads_file(inline_value):
                return "-b"
        if "://" in token and not token.lower().startswith(("http://", "https://")):
            return token.split("://", 1)[0] + "://"
        idx += 1
    return None


def _split_curl_option(token: str) -> tuple[str, str | None]:
    if token.startswith("--") and "=" in token:
        option, value = token.split("=", 1)
        return option, value
    return token, None


def _curl_value_reads_file(value: str | None) -> bool:
    if not value:
        return False
    stripped = value.strip()
    return stripped.startswith("@") or "=@" in stripped


def _curl_cookie_value_reads_file(value: str | None) -> bool:
    if not value:
        return False
    stripped = value.strip()
    if stripped.startswith("@"):
        return True
    return "=" not in stripped


def _blocked_curl_shell_syntax(args: Mapping[str, Any]) -> str | None:
    command = args.get("command")
    if not isinstance(command, str):
        return None
    in_single = False
    in_double = False
    idx = 0
    while idx < len(command):
        char = command[idx]
        if char == "\\" and not in_single:
            idx += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            idx += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            idx += 1
            continue
        if not in_single and char == "`":
            return "`"
        if not in_single and command.startswith("$(", idx):
            return "$("
        if not in_single and not in_double and char in {";", "&", "|", "<", ">", "\n", "\r"}:
            return char
        idx += 1
    return None


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.replace('"', " ").replace("'", " ").split()


def _normalise_url_candidate(token: str, *, allow_bare: bool) -> str | None:
    stripped = token.strip().strip("`(),;")
    if not stripped or stripped.startswith("@"):
        return None
    lowered = stripped.lower()
    if lowered.startswith(("http://", "https://")):
        return stripped
    if "://" in lowered:
        return stripped
    if not allow_bare:
        return None
    parsed = urlparse(f"//{stripped}")
    host = parsed.hostname
    if host and _looks_like_host(host):
        return f"http://{stripped}"
    return None


def _looks_like_host(host: str) -> bool:
    normalised = host.strip("[]").lower()
    if normalised == "localhost":
        return True
    try:
        ipaddress.ip_address(normalised)
        return True
    except ValueError:
        pass
    if "." not in normalised:
        return False
    labels = normalised.rstrip(".").split(".")
    return all(
        label
        and not label.startswith("-")
        and not label.endswith("-")
        and all(ch.isalnum() or ch == "-" for ch in label)
        for label in labels
    )


def _extract_host(target: str | None) -> str | None:
    if not target:
        return None
    parsed = urlparse(target if "://" in target else f"//{target}")
    return (parsed.hostname or target).strip().lower()


def _atom_matches(atom: str, target: str) -> bool:
    atom = atom.strip()
    if not atom:
        return False
    target = target.strip()

    if "://" in atom:
        return _url_prefix_matches(atom, target)

    host = _extract_host(target)
    if not host:
        return False

    try:
        network = ipaddress.ip_network(atom, strict=False)
        try:
            return ipaddress.ip_address(host) in network
        except ValueError:
            return False
    except ValueError:
        pass

    if atom.startswith("*."):
        suffix = atom[1:].lower()
        return host.endswith(suffix) and host != suffix.lstrip(".")
    return host == atom.lower()


def _url_prefix_matches(atom: str, target: str) -> bool:
    atom_url = urlparse(atom)
    target_url = urlparse(target)
    if not atom_url.scheme or not target_url.scheme:
        return False
    if atom_url.scheme.lower() != target_url.scheme.lower():
        return False
    atom_host = atom_url.hostname
    target_host = target_url.hostname
    if not atom_host or not target_host:
        return False
    if atom_host.lower() != target_host.lower():
        return False
    atom_port = _url_port(atom_url)
    target_port = _url_port(target_url)
    if atom_port is not None and atom_port != target_port:
        return False
    atom_path = atom_url.path or "/"
    target_path = target_url.path or "/"
    if atom_path == "/":
        return True
    if atom_path.endswith("/"):
        return target_path.startswith(atom_path)
    return target_path == atom_path or target_path.startswith(f"{atom_path}/")


def _url_port(parsed: Any) -> int | None:
    try:
        return parsed.port
    except ValueError:
        return None


def _parse_auth_window(data: Mapping[str, Any]) -> dict[str, datetime | None]:
    window = data.get("auth_window")
    start_raw = data.get("auth_window_start")
    end_raw = data.get("auth_window_end")
    if isinstance(window, Mapping):
        start_raw = window.get("start") or window.get("from") or start_raw
        end_raw = window.get("end") or window.get("to") or end_raw
    elif isinstance(window, (list, tuple)) and len(window) >= 2:
        start_raw = window[0]
        end_raw = window[1]
    return {
        "start": _parse_datetime(start_raw),
        "end": _parse_datetime(end_raw),
    }


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()
