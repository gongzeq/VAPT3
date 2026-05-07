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
# nmap-host-discovery
# --------------------------------------------------------------------------

_NMAP_SN_OUT = b"""\
# Nmap 7.94 scan initiated
Host: 10.0.0.1 (gw.example)	Status: Up
Host: 10.0.0.7 (ws7.example)	Status: Up
Host: 10.0.0.8 (off.example)	Status: Down
# Nmap done
"""


async def test_nmap_host_discovery_happy(make_ctx, fake_run_command):
    mod = load_handler("nmap-host-discovery")
    fake_run_command(mod, stdout=_NMAP_SN_OUT, exit_code=0)
    ctx = make_ctx()
    res = await mod.run({"target": "10.0.0.0/24", "rate": "normal"}, ctx)
    assert isinstance(res, SkillResult)
    assert res.summary["hosts_up"] == ["10.0.0.1", "10.0.0.7"]
    assert "elapsed_sec" in res.summary


async def test_nmap_host_discovery_invalid_target(make_ctx):
    mod = load_handler("nmap-host-discovery")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"target": "not a target"}, make_ctx())


async def test_nmap_host_discovery_timeout(make_ctx, fake_run_command):
    mod = load_handler("nmap-host-discovery")
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


async def test_fscan_asset_discovery_invalid_target(make_ctx):
    mod = load_handler("fscan-asset-discovery")
    with pytest.raises(InvalidSkillArg):
        await mod.run({"target": "../etc/passwd"}, make_ctx())


# --------------------------------------------------------------------------
# nmap-port-scan
# --------------------------------------------------------------------------

_NMAP_PS_OUT = b"""\
Host: 10.0.0.1 ()	Ports: 22/open/tcp//ssh///, 80/open/tcp//http///	Ignored State: closed
Host: 10.0.0.7 ()	Ports: 443/open/tcp//https///
"""


async def test_nmap_port_scan_happy(make_ctx, fake_run_command):
    mod = load_handler("nmap-port-scan")
    from secbot.skills._shared import runner as runner_mod

    fake_run_command(runner_mod, stdout=_NMAP_PS_OUT, exit_code=0)
    res = await mod.run({"targets": ["10.0.0.0/24"], "ports": "22,80,443"}, make_ctx())
    svcs = res.summary["services"]
    hp = {(s["host"], s["port"]) for s in svcs}
    assert ("10.0.0.1", 22) in hp
    assert ("10.0.0.1", 80) in hp
    assert ("10.0.0.7", 443) in hp


async def test_nmap_port_scan_bad_portspec(make_ctx):
    mod = load_handler("nmap-port-scan")
    with pytest.raises(InvalidSkillArg):
        await mod.run(
            {"targets": ["10.0.0.1"], "ports": "22;rm -rf /"}, make_ctx()
        )


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
