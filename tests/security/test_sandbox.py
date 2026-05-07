"""Sandbox / argv injection unit tests (spec §7)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from secbot.skills._shared import (
    BINARY_WHITELIST,
    BinaryNotAllowed,
    InvalidArgvCharacter,
    NetworkPolicy,
    run_command,
)
from secbot.skills.types import SkillBinaryMissing, SkillCancelled, SkillTimeout


def test_binary_whitelist_contains_required_tools():
    for required in ("nmap", "fscan", "nuclei", "weasyprint", "python3"):
        assert required in BINARY_WHITELIST


@pytest.mark.asyncio
async def test_rejects_non_whitelisted_binary(tmp_path: Path):
    with pytest.raises(BinaryNotAllowed):
        await run_command(
            binary="rm",
            args=["-rf", "/"],
            timeout_sec=1,
            network=NetworkPolicy.NONE,
            capture="discard",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "1.2.3.4; rm -rf /",
        "$(whoami)",
        "`id`",
        "a|b",
        "a&b",
        "a\nb",
        "a>b",
        "a<b",
        "a\\b",
    ],
)
async def test_argv_injection_blocked(bad: str, tmp_path: Path):
    with pytest.raises(InvalidArgvCharacter):
        await run_command(
            binary="python3",
            args=["-c", "print(1)", bad],
            timeout_sec=1,
            network=NetworkPolicy.NONE,
            capture="discard",
        )


@pytest.mark.asyncio
async def test_missing_binary_raises_binary_missing(tmp_path: Path, monkeypatch):
    # Force shutil.which to return None for an otherwise-whitelisted binary.
    monkeypatch.setattr("secbot.skills._shared.sandbox.shutil.which", lambda _b: None)
    with pytest.raises(SkillBinaryMissing):
        await run_command(
            binary="nmap",
            args=["-V"],
            timeout_sec=1,
            network=NetworkPolicy.NONE,
            capture="discard",
        )


@pytest.mark.asyncio
async def test_zero_timeout_rejected():
    with pytest.raises(ValueError):
        await run_command(
            binary="python3",
            args=["-c", "pass"],
            timeout_sec=0,
            network=NetworkPolicy.NONE,
            capture="discard",
        )


@pytest.mark.asyncio
async def test_capture_file_requires_path():
    with pytest.raises(ValueError):
        await run_command(
            binary="python3",
            args=["-c", "pass"],
            timeout_sec=1,
            network=NetworkPolicy.NONE,
            capture="file",
            raw_log_path=None,
        )


@pytest.mark.asyncio
async def test_python3_runs_and_writes_log(tmp_path: Path):
    log = tmp_path / "out.log"
    res = await run_command(
        binary="python3",
        args=["-c", "print(1234567)"],
        timeout_sec=10,
        network=NetworkPolicy.NONE,
        capture="file",
        raw_log_path=log,
    )
    assert res.exit_code == 0
    assert log.exists()
    assert b"1234567" in log.read_bytes()


@pytest.mark.asyncio
async def test_timeout_kills_process(tmp_path: Path):
    log = tmp_path / "out.log"
    with pytest.raises(SkillTimeout):
        await run_command(
            binary="python3",
            args=["-m", "http.server", "0", "--bind", "127.0.0.1"],
            timeout_sec=1,
            network=NetworkPolicy.NONE,
            capture="file",
            raw_log_path=log,
        )


@pytest.mark.asyncio
async def test_cancel_token_terminates(tmp_path: Path):
    log = tmp_path / "out.log"
    cancel = asyncio.Event()

    async def _trigger():
        await asyncio.sleep(0.2)
        cancel.set()

    asyncio.create_task(_trigger())
    with pytest.raises(SkillCancelled):
        await run_command(
            binary="python3",
            args=["-m", "http.server", "0", "--bind", "127.0.0.1"],
            timeout_sec=10,
            network=NetworkPolicy.NONE,
            capture="file",
            raw_log_path=log,
            cancel_token=cancel,
        )
