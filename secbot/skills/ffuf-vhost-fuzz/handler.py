"""ffuf-vhost-fuzz handler.

Fuzz the ``Host:`` header with ``ffuf -H "Host: <host_template>"`` using
``host_template`` that contains the ``FUZZ`` marker (e.g. ``FUZZ.example.com``).
Filters on response size to eliminate the 404-equivalent baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult


def _validate(host_template: str, wordlist: list[str]) -> None:
    if "FUZZ" not in host_template:
        raise InvalidSkillArg("host_template must contain the FUZZ marker")
    for w in wordlist:
        if any(c in w for c in ("\n", "\r", "\t", " ")):
            raise InvalidSkillArg(f"invalid wordlist entry: {w!r}")


def _parse(raw_log: Path, _exit_code: int) -> dict[str, Any]:
    vhosts: list[dict[str, Any]] = []
    if not raw_log.exists():
        return {"vhosts": vhosts}
    try:
        data = json.loads(raw_log.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        return {"vhosts": vhosts, "parse_error": str(exc)[:200]}

    for r in data.get("results", [])[:500]:
        vhosts.append(
            {
                "host": (r.get("input") or {}).get("FUZZ", ""),
                "status": int(r.get("status", 0)),
                "length": int(r.get("length", 0)),
                "words": int(r.get("words", 0)),
            }
        )
    return {"vhosts": vhosts}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    url: str = args["url"]
    host_template: str = args["host_template"]
    wordlist: list[str] = list(args["wordlist"])
    threads: int = int(args.get("threads", 40))
    filter_size: str | None = args.get("filter_size")

    _validate(host_template, wordlist)

    ffuf_dir = ctx.scan_dir / "ffuf"
    ffuf_dir.mkdir(parents=True, exist_ok=True)
    wordlist_file = ffuf_dir / "vhost-wordlist.txt"
    wordlist_file.write_text("\n".join(wordlist) + "\n", encoding="utf-8")
    results_file = ffuf_dir / "vhost-results.json"

    cli: list[str] = [
        "-u", url,
        "-H", f"Host: {host_template}",
        "-w", f"{wordlist_file}:FUZZ",
        "-t", str(threads),
        "-of", "json",
        "-o", str(results_file),
        "-s",
    ]
    if filter_size:
        cli += ["-fs", filter_size]

    return await execute(
        binary="ffuf",
        args=cli,
        timeout_sec=600,
        raw_log_name="ffuf-vhost-fuzz.log",
        ctx=ctx,
        parser=lambda _log, code: _parse(results_file, code),
    )
