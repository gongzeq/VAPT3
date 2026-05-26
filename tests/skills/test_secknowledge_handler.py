"""Tests for the secknowledge-skill lookup handler."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema


async def test_secknowledge_lookup_returns_cited_reference(
    handler_loader,
    make_ctx,
) -> None:
    mod = handler_loader("secknowledge-skill")
    ctx = make_ctx()

    result = await mod.run(
        {
            "query": "SQL 注入 payload",
            "category": "web",
            "max_results": 3,
        },
        ctx,
    )

    summary = result.summary
    assert summary["query"] == "SQL 注入 payload"
    assert summary["category"] == "web"
    assert summary["unable_to_cite"] is False
    assert summary["references"]
    assert summary["references"][0]["file"].startswith("references/")
    assert summary["references"][0]["section"]


async def test_secknowledge_summary_matches_output_schema(
    handler_loader,
    make_ctx,
) -> None:
    mod = handler_loader("secknowledge-skill")
    ctx = make_ctx()

    result = await mod.run(
        {
            "query": "prompt injection MCP",
            "category": "ai",
            "max_results": 2,
        },
        ctx,
    )

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "secbot"
        / "skills"
        / "secknowledge-skill"
        / "output.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(result.summary, schema)
