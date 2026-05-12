"""sqlmap-dump handler.

Critical-risk skill: actually extracts data from a vulnerable endpoint.
Routed through `HighRiskGate` by the SkillTool wrapper (handler itself does
not need to call `ctx.confirm` again).

Supports four scopes via the ``action`` argument:
- ``dbs``     — enumerate databases
- ``tables``  — enumerate tables for ``database``
- ``columns`` — enumerate columns for ``database.table``
- ``dump``    — dump rows for ``database.table`` (bounded by ``limit``)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secbot.skills._shared.runner import execute
from secbot.skills.types import InvalidSkillArg, SkillContext, SkillResult


_LIST_RE = re.compile(r"^\[\*\]\s+(\S+)$", re.MULTILINE)


def _parse(raw_log: Path, _exit_code: int, *, action: str) -> dict[str, Any]:
    text = ""
    if raw_log.exists():
        text = raw_log.read_text(encoding="utf-8", errors="replace")

    items = _LIST_RE.findall(text)
    out: dict[str, Any] = {"action": action}
    if action == "dbs":
        out["databases"] = items[:200]
    elif action == "tables":
        out["tables"] = items[:500]
    elif action == "columns":
        out["columns"] = items[:500]
    elif action == "dump":
        # sqlmap dumps a CSV under output_dir/<host>/dump/<db>/<table>.csv
        row_count = 0
        dump_path = ""
        for line in text.splitlines():
            if "entries" in line and "fetched" in line:
                m = re.search(r"(\d+)\s+entries", line)
                if m:
                    row_count = int(m.group(1))
            if "dumped to CSV file" in line:
                m = re.search(r"'(.+?\.csv)'", line)
                if m:
                    dump_path = m.group(1)
        out["row_count"] = row_count
        out["dump_path"] = dump_path
    return out


async def run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    url: str = args["url"]
    action: str = args["action"]
    database: str | None = args.get("database")
    table: str | None = args.get("table")
    columns: list[str] = list(args.get("columns", []))
    limit: int = int(args.get("limit", 50))
    method: str = args.get("method", "GET")
    data: str | None = args.get("data")
    cookie: str | None = args.get("cookie")

    if action == "tables" and not database:
        raise InvalidSkillArg("action=tables requires 'database'")
    if action in ("columns", "dump") and not (database and table):
        raise InvalidSkillArg(f"action={action} requires 'database' and 'table'")

    sqlmap_dir = ctx.scan_dir / "sqlmap"
    sqlmap_dir.mkdir(parents=True, exist_ok=True)

    cli: list[str] = [
        "-u", url,
        "--batch",
        "--disable-coloring",
        "--output-dir", str(sqlmap_dir),
    ]
    if action == "dbs":
        cli.append("--dbs")
    elif action == "tables":
        cli += ["-D", database, "--tables"]
    elif action == "columns":
        cli += ["-D", database, "-T", table, "--columns"]
    elif action == "dump":
        cli += ["-D", database, "-T", table, "--dump", "--dump-format", "CSV", "--start", "1", "--stop", str(limit)]
        if columns:
            cli += ["-C", ",".join(columns)]
    if method == "POST" and data:
        cli += ["--data", data]
    if cookie:
        cli += ["--cookie", cookie]

    return await execute(
        binary="sqlmap",
        args=cli,
        timeout_sec=1200,
        raw_log_name=f"sqlmap-dump-{action}.log",
        ctx=ctx,
        parser=lambda log, code: _parse(log, code, action=action),
    )
