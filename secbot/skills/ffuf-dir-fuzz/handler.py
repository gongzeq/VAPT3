"""ffuf-dir-fuzz handler.

Runs ``ffuf -w <wordlist>:FUZZ -u <url>`` against the target URL (which
must contain the ``FUZZ`` marker) and reads the JSON results file with
``-of json -o <raw_log>``. We intentionally materialise the wordlist under
``<scan_dir>/ffuf/wordlist.txt`` instead of trusting a user-supplied path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult


def _validate(url: str, wordlist: list[str]) -> None:
    if "FUZZ" not in url:
        raise InvalidSkillArg("url must contain the FUZZ marker")
    for w in wordlist:
        if any(c in w for c in ("\n", "\r", "\t")):
            raise InvalidSkillArg(f"invalid wordlist entry: {w!r}")


def _parse(raw_log: Path, _exit_code: int) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    if not raw_log.exists():
        return {"hits": hits}
    try:
        data = json.loads(raw_log.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        return {"hits": hits, "parse_error": str(exc)[:200]}

    for r in data.get("results", [])[:500]:
        hits.append(
            {
                "url": r.get("url", ""),
                "input": (r.get("input") or {}).get("FUZZ", ""),
                "status": int(r.get("status", 0)),
                "length": int(r.get("length", 0)),
                "words": int(r.get("words", 0)),
            }
        )
    return {"hits": hits}


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    url: str = args["url"]
    wordlist: list[str] = list(args["wordlist"])
    extensions: list[str] = list(args.get("extensions", []))
    threads: int = int(args.get("threads", 40))
    match_codes: str = args.get("match_codes", "200,204,301,302,307,401,403")

    _validate(url, wordlist)

    ffuf_dir = ctx.scan_dir / "ffuf"
    ffuf_dir.mkdir(parents=True, exist_ok=True)
    wordlist_file = ffuf_dir / "wordlist.txt"
    wordlist_file.write_text("\n".join(wordlist) + "\n", encoding="utf-8")
    results_file = ffuf_dir / "dir-results.json"

    cli: list[str] = [
        "-u", url,
        "-w", f"{wordlist_file}:FUZZ",
        "-t", str(threads),
        "-mc", match_codes,
        "-of", "json",
        "-o", str(results_file),
        "-s",
    ]
    if extensions:
        cli += ["-e", ",".join(extensions)]

    return await execute(
        binary="ffuf",
        args=cli,
        timeout_sec=600,
        raw_log_name="ffuf-dir-fuzz.log",  # ffuf stderr
        ctx=ctx,
        parser=lambda _log, code: _parse(results_file, code),
    )
