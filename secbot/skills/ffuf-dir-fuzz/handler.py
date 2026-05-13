"""ffuf-dir-fuzz handler.

Runs ``ffuf`` to fuzz directories, files, parameters or API endpoints on
a target web app. Supports two invocation modes:

* **URL + FUZZ marker** – ``ffuf -w <wordlist>:FUZZ -u <url>``
* **Raw HTTP request** – ``ffuf --request <req.txt>`` for authenticated
  fuzzing with complex headers / bodies.

The full ffuf feature surface (matchers, filters, auto-calibration,
rate control, recursion, cookies, proxies, …) is exposed via the shared
:mod:`secbot.skills._shared.ffuf` module. See ``SKILL.md`` for the
user-facing usage guide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secbot.skills._shared import ffuf as _ffuf
from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult


def _parse_factory(results_file: Path):
    def _parse(_raw_log: Path, _exit_code: int) -> dict[str, Any]:
        entries, meta = _ffuf.parse_results_json(results_file)
        out: dict[str, Any] = {"hits": entries}
        if meta.get("parse_error"):
            out["parse_error"] = meta["parse_error"]
        if meta.get("total_hits") is not None:
            out["total_hits"] = meta["total_hits"]
        if meta.get("command_line"):
            out["command_line"] = meta["command_line"]
        return out

    return _parse


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    wordlist: list[str] = list(args.get("wordlist") or [])
    raw_request: str | None = args.get("raw_request")
    url: str | None = args.get("url")

    if raw_request is None and url is None:
        raise InvalidSkillArg(
            "must supply either 'url' (containing FUZZ) or 'raw_request'"
        )
    if raw_request is not None and url is not None:
        raise InvalidSkillArg(
            "'raw_request' and 'url' are mutually exclusive — pick one mode"
        )

    _ffuf.validate_wordlist(wordlist, allow_space=True)

    ffuf_dir = ctx.scan_dir / "ffuf" / "dir"
    ffuf_dir.mkdir(parents=True, exist_ok=True)
    wordlist_file = _ffuf.materialise_wordlist(wordlist, ffuf_dir / "wordlist.txt")
    results_file = ffuf_dir / "dir-results.json"

    cli: list[str] = []

    # ---- Mode: raw request vs URL+FUZZ --------------------------------
    if raw_request is not None:
        req_file = _ffuf.materialise_raw_request(raw_request, ffuf_dir / "req.txt")
        cli += ["--request", str(req_file)]
        proto = args.get("request_proto", "https")
        if proto not in ("http", "https"):
            raise InvalidSkillArg("request_proto must be 'http' or 'https'")
        cli += ["-request-proto", proto]
    else:
        assert url is not None  # narrow for the type checker
        _ffuf.ensure_no_forbidden("url", url)
        _ffuf.ensure_fuzz_marker("url", url)
        cli += ["-u", url]

        method: str = (args.get("method") or "GET").upper()
        _ffuf.validate_method(method)
        if method != "GET":
            cli += ["-X", method]

        body: str | None = args.get("body")
        if body is not None:
            _ffuf.ensure_no_forbidden("body", body)
            cli += ["-d", body]

    # ---- Wordlist binding (always FUZZ) -------------------------------
    cli += ["-w", f"{wordlist_file}:FUZZ"]

    # ---- Extensions (URL mode only; ffuf ignores them with --request) --
    exts = args.get("extensions") or []
    if exts:
        if raw_request is not None:
            raise InvalidSkillArg(
                "'extensions' is only valid in URL mode — embed the extension "
                "directly in the raw request path if needed"
            )
        for e in exts:
            if not isinstance(e, str):
                raise InvalidSkillArg(f"extension must be str: {e!r}")
            _ffuf.ensure_no_forbidden("extensions", e)
        cli += ["-e", ",".join(exts)]

    # ---- Shared option surface (matchers/filters/rate/auth/…) ---------
    opts = dict(args)
    # ``-ac`` removes the baseline 404 noise. Default match codes align
    # with the ffuf default plus 405 (some apps respond with 405 on the
    # routes we care about).
    opts.setdefault("match_codes", "200,204,301,302,307,401,403,405")
    cli += _ffuf.build_common_argv(opts, results_file=results_file)

    timeout_sec = int(args.get("timeout_sec", 600))
    if timeout_sec <= 0 or timeout_sec > 7_200:
        raise InvalidSkillArg(f"timeout_sec out of range: {timeout_sec!r}")

    return await execute(
        binary="ffuf",
        args=cli,
        timeout_sec=timeout_sec,
        raw_log_name="ffuf-dir-fuzz.log",
        ctx=ctx,
        parser=_parse_factory(results_file),
    )
