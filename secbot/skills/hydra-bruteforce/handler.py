"""hydra-bruteforce handler.

Runs `hydra` against a single target/service with bounded user/password
lists. The word lists are materialised to ``<scan_dir>/hydra/<stem>.txt``
(never read from the user-controlled filesystem directly) to keep the
sandbox contract: only whitelisted binary arguments flow into argv.

Output is parsed from ``hydra -o <raw_log> -u -f`` machine-readable JSON
lines (``hydra -b json``); when `-b json` is unavailable the ``[host][port]``
line format is used as fallback.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult

_TARGET_RE = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}$"
    r"|^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$"
)
# hydra text line format:
#   [22][ssh] host: 10.0.0.1   login: root   password: toor
_TEXT_LINE = re.compile(
    r"^\[(?P<port>\d+)\]\[(?P<service>[a-z0-9\-]+)\]\s+host:\s*(?P<host>\S+)"
    r"\s+login:\s*(?P<user>\S+)\s+password:\s*(?P<pwd>\S+)"
)


def _validate(target: str, users: list[str], passwords: list[str]) -> None:
    if not _TARGET_RE.match(target):
        raise InvalidSkillArg(f"invalid target: {target!r}")
    for u in users:
        if any(c in u for c in (":", "\n", "\r", " ", "\t")):
            raise InvalidSkillArg(f"invalid username: {u!r}")
    for p in passwords:
        if any(c in p for c in ("\n", "\r")):
            raise InvalidSkillArg("passwords must not contain newlines")


def _write_list(path: Path, items: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(items) + "\n", encoding="utf-8")


def _parse(raw_log: Path, _exit_code: int) -> dict[str, Any]:
    creds: list[dict[str, Any]] = []
    if not raw_log.exists():
        return {"credentials": creds}

    with raw_log.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            # JSON line (hydra -b jsonv1)
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    if obj.get("success") is True:
                        creds.append(
                            {
                                "host": obj.get("host", ""),
                                "port": int(obj.get("port", 0)) or None,
                                "service": obj.get("service", ""),
                                "username": obj.get("login", ""),
                                "password": obj.get("password", ""),
                            }
                        )
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass
            m = _TEXT_LINE.match(line)
            if m:
                creds.append(
                    {
                        "host": m["host"],
                        "port": int(m["port"]),
                        "service": m["service"],
                        "username": m["user"],
                        "password": m["pwd"],
                    }
                )
    return {"credentials": creds, "attempts": len(creds)}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    target: str = args["target"]
    service: str = args["service"]
    port: int | None = args.get("port")
    users: list[str] = list(args["users"])
    passwords: list[str] = list(args["passwords"])
    tasks: int = int(args.get("tasks", 4))
    form: str | None = args.get("form")

    _validate(target, users, passwords)

    hydra_dir = ctx.scan_dir / "hydra"
    user_file = hydra_dir / "users.txt"
    pass_file = hydra_dir / "passwords.txt"
    _write_list(user_file, users)
    _write_list(pass_file, passwords)

    cli: list[str] = [
        "-L", str(user_file),
        "-P", str(pass_file),
        "-t", str(tasks),
        "-I",
        "-f",
        "-V",
    ]
    if port:
        cli += ["-s", str(port)]
    cli.append(target)
    if service == "http-post-form":
        if not form:
            raise InvalidSkillArg("service=http-post-form requires 'form' argument")
        cli.append(f"http-post-form")
        cli.append(form)
    else:
        cli.append(service)

    return await execute(
        binary="hydra",
        args=cli,
        timeout_sec=900,
        raw_log_name="hydra-bruteforce.log",
        ctx=ctx,
        parser=_parse,
    )
