"""EvidenceStore tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

from sqlalchemy import select

from secbot.cmdb.models import EvidenceFindingLinkModel
from secbot.evidence.sanitiser import sanitise
from secbot.evidence.store import EvidenceStore


def test_sanitise_redacts_json_keys() -> None:
    raw = b'{"token":"abcdef","nested":{"session":"xyz"},"ok":true}'

    redacted = sanitise(raw, ["token", "session"])
    payload = json.loads(redacted)

    assert payload["token"] == "***REDACTED:6c***"
    assert payload["nested"]["session"] == "***REDACTED:3c***"
    assert payload["ok"] is True


def test_sanitise_redacts_headers_and_query_params() -> None:
    raw = (
        b"GET https://example.test/path?token=abcdef&safe=1 HTTP/1.1\n"
        b"Authorization: Bearer secret\n"
        b"Cookie: sid=abc\n"
    )

    redacted = sanitise(raw, ["token"]).decode()

    assert "abcdef" not in redacted
    assert "Bearer secret" not in redacted
    assert "sid=abc" not in redacted
    assert "safe=1" in redacted


async def test_put_get_records_metadata_and_raw_file(tmp_cmdb, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / ".secbot" / "evidence")

    evidence_id = await store.put(
        "chat-a",
        source_tool="nuclei",
        evidence_type="http",
        summary="request and response",
        raw_bytes=b"Authorization: Bearer secret\nbody",
    )

    record = await store.get(evidence_id)
    assert record is not None
    assert record.id == evidence_id
    assert record.chat_id == "chat-a"
    assert record.source_tool == "nuclei"
    assert record.evidence_type == "http"
    assert record.summary == "request and response"
    assert record.size_bytes == len(b"Authorization: Bearer secret\nbody")
    assert record.sanitised is True
    assert record.raw_ref is not None
    raw_path = store.raw_path(record.raw_ref)
    assert raw_path.exists()
    assert b"Bearer secret" not in raw_path.read_bytes()


async def test_put_without_raw_bytes_records_metadata_only(tmp_cmdb, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / ".secbot" / "evidence")

    evidence_id = await store.put(
        "chat-a",
        source_tool="pi",
        evidence_type="other",
        summary="manual note",
    )

    record = await store.get(evidence_id)
    assert record is not None
    assert record.raw_ref is None
    assert record.sanitised is False
    assert record.size_bytes == 0


async def test_link_and_find_for_supports_multiple_findings(tmp_cmdb, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / ".secbot" / "evidence")
    evidence_id = await store.put(
        "chat-a",
        source_tool="worker:a",
        evidence_type="log",
        summary="scanner log",
        raw_bytes=b"plain log",
    )

    await store.link(evidence_id, "finding-1")
    await store.link(evidence_id, "finding-2", role="supporting")

    one = await store.find_for("finding-1")
    two = await store.find_for("finding-2")
    assert [record.id for record in one] == [evidence_id]
    assert [record.id for record in two] == [evidence_id]

    rows = (await tmp_cmdb.execute(select(EvidenceFindingLinkModel))).scalars().all()
    assert {(row.finding_id, row.link_role) for row in rows} == {
        ("finding-1", "primary"),
        ("finding-2", "supporting"),
    }


async def test_gc_removes_db_rows_and_raw_files(tmp_cmdb, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / ".secbot" / "evidence")
    evidence_id = await store.put(
        "chat-a",
        source_tool="worker:a",
        evidence_type="cmd_output",
        summary="command output",
        raw_bytes=b"output",
    )
    record = await store.get(evidence_id)
    assert record is not None and record.raw_ref is not None
    raw_path = store.raw_path(record.raw_ref)
    assert raw_path.exists()

    removed = await store.gc("chat-a", before=time.time() + 1)

    assert removed == 1
    assert await store.get(evidence_id) is None
    assert not raw_path.exists()


async def test_raw_storage_sanitises_chat_id_path_segment(tmp_cmdb, tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / ".secbot" / "evidence")

    evidence_id = await store.put(
        "../outside",
        source_tool="worker:a",
        evidence_type="log",
        summary="path traversal attempt",
        raw_bytes=b"output",
    )

    record = await store.get(evidence_id)
    assert record is not None and record.raw_ref is not None
    assert ".." not in Path(record.raw_ref).parts
    raw_path = store.raw_path(record.raw_ref)
    assert raw_path.exists()
    assert raw_path.is_relative_to(store.fs_root)
    assert not (tmp_path / ".secbot" / "outside").exists()


def test_raw_path_rejects_escaped_ref(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / ".secbot" / "evidence")

    try:
        store.raw_path("../outside.txt")
    except ValueError as exc:
        assert "escapes evidence root" in str(exc)
    else:
        raise AssertionError("raw_path accepted an escaped ref")
