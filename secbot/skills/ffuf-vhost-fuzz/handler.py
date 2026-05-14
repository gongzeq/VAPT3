"""ffuf-vhost-fuzz handler.

Fuzz the ``Host:`` header to enumerate virtual hosts backed by the same
IP or base URL. Supports two modes:

* **url + host_template** — ``ffuf -u <url> -H "Host: FUZZ.example.com"``
* **raw_request** — ``ffuf --request <req.txt>`` with a ``Host: FUZZ…``
  line embedded in the raw request.

All ffuf knobs (matchers, filters, auto-calibration, rate control,
cookies, proxies) are exposed through the shared
:mod:`secbot.skills._shared.ffuf` module. See ``SKILL.md`` for usage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secbot.skills._shared import ffuf as _ffuf
from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillBinaryMissing, SkillContext, SkillResult


def _resolve_ffuf_binary(cli: list[str]) -> tuple[str, list[str]]:
    """Return (binary, args) for ffuf, honouring config overrides.

    Priority:
      1. Configured override in ``tools.skillBinaries.ffuf``.
      2. ``ffuf`` found on PATH.
      3. Raise :class:`SkillBinaryMissing` with a helpful hint.
    """
    import shutil
    from pathlib import Path

    from secbot.config.loader import load_config

    cfg = load_config()
    override = cfg.tools.skill_binaries.get("ffuf")
    if override:
        if not Path(override).exists():
            raise SkillBinaryMissing(
                f"Configured ffuf override not found: {override}. "
                "Check tools.skillBinaries.ffuf in your config."
            )
        return override, cli
    if shutil.which("ffuf"):
        return "ffuf", cli
    raise SkillBinaryMissing(
        "ffuf not found on PATH. "
        "Install ffuf or set tools.skillBinaries.ffuf in ~/.secbot/config.json"
    )


def _parse_factory(results_file: Path, base_url: str | None):
    def _parse(_raw_log: Path, _exit_code: int) -> dict[str, Any]:
        entries, meta = _ffuf.parse_results_json(results_file)
        vhosts: list[dict[str, Any]] = []
        for r in entries:
            vhosts.append(
                {
                    "host": r.get("input") or "",
                    "url": r.get("url") or (base_url or ""),
                    "status": r["status"],
                    "length": r["length"],
                    "words": r["words"],
                    "lines": r["lines"],
                    "duration_ms": r["duration_ms"],
                    "content_type": r["content_type"],
                    "redirect_location": r["redirect_location"],
                }
            )
        out: dict[str, Any] = {"vhosts": vhosts}
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
    host_template: str | None = args.get("host_template")

    # Mode guards -------------------------------------------------------
    if raw_request is None:
        if url is None or host_template is None:
            raise InvalidSkillArg(
                "url+host_template are required unless 'raw_request' is set"
            )
    else:
        if url is not None or host_template is not None:
            raise InvalidSkillArg(
                "'raw_request' is mutually exclusive with 'url' / 'host_template'"
            )

    # host_template / wordlist MUST NOT contain spaces — they end up in a
    # single Host header.
    _ffuf.validate_wordlist(wordlist, allow_space=False)

    ffuf_dir = ctx.scan_dir / "ffuf" / "vhost"
    ffuf_dir.mkdir(parents=True, exist_ok=True)
    wordlist_file = _ffuf.materialise_wordlist(
        wordlist, ffuf_dir / "vhost-wordlist.txt"
    )
    results_file = ffuf_dir / "vhost-results.json"

    cli: list[str] = []

    if raw_request is not None:
        req_file = _ffuf.materialise_raw_request(raw_request, ffuf_dir / "req.txt")
        cli += ["--request", str(req_file)]
        proto = args.get("request_proto", "https")
        if proto not in ("http", "https"):
            raise InvalidSkillArg("request_proto must be 'http' or 'https'")
        cli += ["-request-proto", proto]
    else:
        assert url is not None and host_template is not None
        _ffuf.ensure_no_forbidden("url", url)
        _ffuf.ensure_fuzz_marker("host_template", host_template)
        _ffuf.ensure_no_forbidden("host_template", host_template)
        if " " in host_template:
            raise InvalidSkillArg("host_template must not contain spaces")
        cli += ["-u", url, "-H", f"Host: {host_template}"]

    # Wordlist binding
    cli += ["-w", f"{wordlist_file}:FUZZ"]

    # Shared flags (matchers / filters / rate / auth / auto-calibration) -
    # Unlike dir-fuzz we do NOT inject a default match_codes: vhost fuzzing
    # relies on auto-calibration filtering the baseline, and ffuf's own
    # default match set (200-299, 301, 302, 307, 401, 403, 405, 500) is a
    # good fit. Operators can still pass match_codes / filter_sizes to
    # narrow further.
    cli += _ffuf.build_common_argv(dict(args), results_file=results_file)

    timeout_sec = int(args.get("timeout_sec", 600))
    if timeout_sec <= 0 or timeout_sec > 7_200:
        raise InvalidSkillArg(f"timeout_sec out of range: {timeout_sec!r}")

    binary, args = _resolve_ffuf_binary(cli)
    return await execute(
        binary=binary,
        args=args,
        timeout_sec=timeout_sec,
        raw_log_name="ffuf-vhost-fuzz.log",
        ctx=ctx,
        parser=_parse_factory(results_file, url),
    )
