"""Skill handler unit tests.

Each skill gets happy-path coverage (with a fixed stdout fed through the
sandbox fake) plus at least one failure branch (timeout / input validation).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from secbot.skills._shared.sandbox import SandboxResult
from secbot.skills.types import (
    InvalidSkillArg,
    SkillResult,
    SkillTimeout,
)

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "secbot" / "skills"


def load_handler(skill_name: str) -> ModuleType:
    mod_name = f"_secbot_skill_{skill_name.replace('-', '_')}_handler"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    path = _SKILLS_ROOT / skill_name / "handler.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# qscan-host-discovery
# --------------------------------------------------------------------------

_QSCAN_SN_OUT = b"""\
http://10.0.0.1/
http://10.0.0.7/some-page
"""


async def test_qscan_host_discovery_happy(make_ctx, fake_run_command, monkeypatch):
    import shutil

    mod = load_handler("qscan-host-discovery")
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/qscan" if name == "qscan" else None
    )
    fake_run_command(mod, stdout=b"", exit_code=0)
    ctx = make_ctx()
    (ctx.raw_log_dir / "qscan-host-discovery.log").write_bytes(_QSCAN_SN_OUT)
    res = await mod.run({"target": "10.0.0.0/24"}, ctx)
    assert isinstance(res, SkillResult)
    assert res.summary["hosts_up"] == ["10.0.0.1", "10.0.0.7"]
    assert "elapsed_sec" in res.summary


async def test_qscan_host_discovery_invalid_target(make_ctx):
    mod = load_handler("qscan-host-discovery")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"target": "not a target"}, make_ctx())


async def test_qscan_host_discovery_timeout(make_ctx, fake_run_command, monkeypatch):
    import shutil

    mod = load_handler("qscan-host-discovery")
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/qscan" if name == "qscan" else None
    )
    fake_run_command(mod, exc=SkillTimeout("timeout"))
    res = await mod.run({"target": "10.0.0.0/24"}, make_ctx())
    assert res.summary.get("error") == "timeout"


# --------------------------------------------------------------------------
# fscan-asset-discovery
# --------------------------------------------------------------------------

_FSCAN_ALIVE = b"""\
start fscan
(icmp) Target 10.0.0.1     is alive
(icmp) Target 10.0.0.12    is alive
[*] LiveTop 10.0.0.0/24     2/256
"""


async def test_fscan_asset_discovery_happy(make_ctx, fake_run_command):
    mod = load_handler("fscan-asset-discovery")
    # fscan-asset-discovery uses the runner.execute helper which imports
    # run_command from `secbot.skills._shared`.
    from secbot.skills._shared import runner as runner_mod

    fake_run_command(runner_mod, stdout=_FSCAN_ALIVE, exit_code=0)
    ctx = make_ctx()
    res = await mod.run({"target": "10.0.0.0/24"}, ctx)
    assert "elapsed_sec" in res.summary
    assert res.summary["hosts_up"] == ["10.0.0.1", "10.0.0.12"]
    assert len(res.cmdb_writes) == 2
    assert all(w["table"] == "assets" for w in res.cmdb_writes)
    assert {w["data"]["target"] for w in res.cmdb_writes} == {"10.0.0.1", "10.0.0.12"}


async def test_fscan_asset_discovery_invalid_target(make_ctx):
    mod = load_handler("fscan-asset-discovery")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"target": "../etc/passwd"}, make_ctx())


# --------------------------------------------------------------------------
# qscan-port-scan
# --------------------------------------------------------------------------

_QSCAN_PS_OUT = b"""\
http://10.0.0.1/	Title	Port:22,FingerPrint:ssh,Digest:...,Length:2567
http://10.0.0.1/	Title	Port:80,FingerPrint:http,Digest:...,Length:2567
http://10.0.0.7/	Title	Port:443,FingerPrint:https,Digest:...,Length:2567
"""


async def test_qscan_port_scan_happy(make_ctx, fake_run_command, monkeypatch):
    import shutil

    mod = load_handler("qscan-port-scan")
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/qscan" if name == "qscan" else None
    )
    fake_run_command(mod, stdout=b"", exit_code=0)
    ctx = make_ctx()
    (ctx.raw_log_dir / "qscan-port-scan.log").write_bytes(_QSCAN_PS_OUT)
    res = await mod.run({"target": "10.0.0.0/24"}, ctx)
    svcs = res.summary["services"]
    hp = {(s["host"], s["port"]) for s in svcs}
    assert ("10.0.0.1", 22) in hp
    assert ("10.0.0.1", 80) in hp
    assert ("10.0.0.7", 443) in hp
    assert len(svcs) == 3
    assert len(res.cmdb_writes) == 3
    assert all(w["table"] == "services" for w in res.cmdb_writes)
    assert {(w["data"]["target"], w["data"]["port"]) for w in res.cmdb_writes} == {
        ("10.0.0.1", 22),
        ("10.0.0.1", 80),
        ("10.0.0.7", 443),
    }


# --------------------------------------------------------------------------
# fscan-port-scan
# --------------------------------------------------------------------------

_FSCAN_PORTS = b"""\
start fscan
10.0.0.1:22 open
10.0.0.1:80 open
10.0.0.7:8080 open
[*] alive ports len is: 3
"""


async def test_fscan_port_scan_happy(make_ctx, fake_run_command):
    mod = load_handler("fscan-port-scan")
    from secbot.skills._shared import runner as runner_mod

    fake_run_command(runner_mod, stdout=_FSCAN_PORTS, exit_code=0)
    res = await mod.run({"target": "10.0.0.0/24", "ports": "1-65535"}, make_ctx())
    svcs = res.summary["services"]
    assert {(s["host"], s["port"]) for s in svcs} == {
        ("10.0.0.1", 22),
        ("10.0.0.1", 80),
        ("10.0.0.7", 8080),
    }
    assert len(res.cmdb_writes) == 3
    assert all(w["table"] == "services" for w in res.cmdb_writes)
    assert {(w["data"]["target"], w["data"]["port"]) for w in res.cmdb_writes} == {
        ("10.0.0.1", 22),
        ("10.0.0.1", 80),
        ("10.0.0.7", 8080),
    }


# --------------------------------------------------------------------------
# nuclei-template-scan
# --------------------------------------------------------------------------

_NUCLEI_JSONL = (
    b'{"template-id":"CVE-2021-44228","info":{"name":"Log4Shell","severity":"critical"},'
    b'"host":"http://10.0.0.1:8080","matched-at":"http://10.0.0.1:8080/api"}\n'
    b'{"template-id":"exposed-git","info":{"name":"Git exposed","severity":"medium"},'
    b'"host":"http://10.0.0.7","matched-at":"http://10.0.0.7/.git/"}\n'
)


async def test_nuclei_template_scan_happy(make_ctx, fake_run_command):
    mod = load_handler("nuclei-template-scan")
    fake_run_command(mod, stdout=b"", exit_code=0)
    ctx = make_ctx()
    # The handler writes raw_log via `-o` option rather than sandbox capture,
    # so populate the expected path ourselves.
    (ctx.raw_log_dir / "nuclei.jsonl").write_bytes(_NUCLEI_JSONL)

    res = await mod.run(
        {"targets": ["http://10.0.0.1:8080", "http://10.0.0.7"]}, ctx
    )
    assert res.summary["findings_count"] == 2
    ids = {f["template_id"] for f in res.findings}
    assert ids == {"CVE-2021-44228", "exposed-git"}
    assert all(w["table"] == "vulnerabilities" for w in res.cmdb_writes)


async def test_nuclei_template_scan_accepts_bundled_template(make_ctx, monkeypatch):
    mod = load_handler("nuclei-template-scan")
    captured: dict[str, object] = {}

    async def _fake_run_command(**kwargs):
        captured.update(kwargs)
        return SandboxResult(exit_code=0, raw_log_path=None, captured=None)

    monkeypatch.setattr(mod, "run_command", _fake_run_command, raising=True)
    monkeypatch.setattr(mod, "_resolve_nuclei_binary", lambda cli: ("nuclei", cli))

    res = await mod.run(
        {
            "targets": ["http://10.0.0.1"],
            "templates": ["upload/pikachu_upload.yaml"],
        },
        make_ctx(),
    )

    argv = captured["args"]
    assert isinstance(argv, list)
    template_path = Path(argv[argv.index("-t") + 1])
    assert template_path.name == "pikachu_upload.yaml"
    assert "secbot/resource/poc/upload" in template_path.as_posix()
    assert res.summary["findings_count"] == 0


async def test_nuclei_template_scan_rejects_bad_target(make_ctx):
    mod = load_handler("nuclei-template-scan")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"targets": ["not a url"]}, make_ctx())


async def test_nuclei_template_scan_rejects_bad_severity(make_ctx):
    mod = load_handler("nuclei-template-scan")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {"targets": ["http://10.0.0.1"], "severity": "info,low"}, make_ctx()
        )


# --------------------------------------------------------------------------
# fscan-vuln-scan
# --------------------------------------------------------------------------

_FSCAN_VULN = b"""\
start fscan
10.0.0.1:8080 open
[+] poc-yaml-thinkphp-5022-rce http://10.0.0.1:8080 extra=cmd
[+] poc-yaml-weblogic-cve-2020-14882 http://10.0.0.7:7001 extra=auth
"""


async def test_fscan_vuln_scan_happy(make_ctx, fake_run_command):
    mod = load_handler("fscan-vuln-scan")
    fake_run_command(mod, stdout=b"", exit_code=0)
    ctx = make_ctx()
    (ctx.raw_log_dir / "fscan-vuln-scan.log").write_bytes(_FSCAN_VULN)

    res = await mod.run({"target": "10.0.0.0/24"}, ctx)
    assert res.summary["findings_count"] == 2
    hosts = {f["host"] for f in res.findings}
    assert hosts == {"10.0.0.1", "10.0.0.7"}
    assert res.cmdb_writes[0]["table"] == "vulnerabilities"


async def test_fscan_vuln_scan_invalid_target(make_ctx):
    mod = load_handler("fscan-vuln-scan")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"target": "1;2"}, make_ctx())
