"""Integration tests for :mod:`secbot.api.workflow_routes`.

The tests run through aiohttp's ``TestClient`` so they exercise routing,
body parsing, error translation and the service wiring contract end-to-
end without spinning up a real agent loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from secbot.api.server import create_app
from secbot.workflow import (
    StepExecutor,
    WorkflowService,
)

try:
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:  # pragma: no cover - aiohttp is a hard dependency
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)

pytestmark = pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubExecutor(StepExecutor):
    """Trivial executor that echoes the resolved ``args`` as its output."""

    kind = "stub"

    async def _run(self, step, args, ctx):  # noqa: ANN001
        return dict(args)


class FakeCronJob:
    def __init__(self, job_id: str, message: str) -> None:
        self.id = job_id
        self.message = message


class FakeCronService:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeCronJob] = {}
        self._next = 1

    def add_job(self, *, name, schedule, message, deliver=False):  # noqa: ANN001
        job_id = f"job{self._next}"
        self._next += 1
        job = FakeCronJob(job_id, message)
        self.jobs[job_id] = job
        return job

    def remove_job(self, job_id: str) -> str:
        if job_id not in self.jobs:
            return "not_found"
        del self.jobs[job_id]
        return "removed"


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.display_name = name.replace("_", " ").title()
        self.description = f"fake tool {name}"
        self.parameters = {"type": "object", "properties": {}}
        self.output_schema = {"type": "object"}


class FakeToolRegistry:
    def __init__(self, names: list[str]) -> None:
        self._tools = {n: FakeTool(n) for n in names}

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> FakeTool | None:
        return self._tools.get(name)


class FakeAgentSpec:
    def __init__(self, name: str) -> None:
        self.name = name
        self.display_name = f"Agent {name}"
        self.description = f"desc of {name}"
        self.input_schema = {"type": "object"}
        self.output_schema = {"type": "object"}


class FakeAgentRegistry:
    def __init__(self, names: list[str]) -> None:
        self._specs = [FakeAgentSpec(n) for n in names]

    def __iter__(self):
        return iter(self._specs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_service(tmp_path: Path, *, cron: Any = None) -> WorkflowService:
    return WorkflowService(
        store_root=tmp_path / "wf",
        tool_registry=None,
        executors={"tool": StubExecutor()},
        cron_service=cron,
    )


def _mock_agent():
    from unittest.mock import AsyncMock, MagicMock

    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value="mock")
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()
    return agent


@pytest_asyncio.fixture
async def client_factory():
    clients: list[TestClient] = []

    async def _make(app):
        client = TestClient(TestServer(app))
        await client.start_server()
        clients.append(client)
        return client

    try:
        yield _make
    finally:
        for c in clients:
            await c.close()


@pytest_asyncio.fixture
async def client(tmp_path, client_factory):
    """App wired with WorkflowService + tool/agent registries (no cron)."""
    svc = _build_service(tmp_path)
    app = create_app(
        _mock_agent(),
        model_name="test",
        request_timeout=10.0,
        workflow_service=svc,
        workflow_tool_registry=FakeToolRegistry(["scan", "probe"]),
        workflow_agent_registry=FakeAgentRegistry(["alpha", "beta"]),
    )
    return await client_factory(app)


@pytest_asyncio.fixture
async def client_with_cron(tmp_path, client_factory):
    """App wired with a fake cron service for schedule tests."""
    cron = FakeCronService()
    svc = _build_service(tmp_path, cron=cron)
    app = create_app(
        _mock_agent(),
        model_name="test",
        request_timeout=10.0,
        workflow_service=svc,
    )
    cli = await client_factory(app)
    return cli, cron, svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workflow_body(
    name: str = "demo",
    *,
    step_kind: str = "tool",
    step_ref: str = "x",
) -> dict[str, Any]:
    return {
        "name": name,
        "description": "d",
        "tags": ["t1"],
        "inputs": [
            {"name": "target", "label": "Target", "type": "string", "required": True}
        ],
        "steps": [
            {
                "id": "s1",
                "name": "probe",
                "kind": step_kind,
                "ref": step_ref,
                "args": {"target": "${inputs.target}"},
            }
        ],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_and_get_workflow(client):
    resp = await client.post("/api/workflows", json=_workflow_body("hello"))
    assert resp.status == 201
    created = await resp.json()
    assert created["name"] == "hello"
    assert created["id"].startswith("wf_")
    assert created["createdAtMs"] > 0

    resp = await client.get(f"/api/workflows/{created['id']}")
    assert resp.status == 200
    fetched = await resp.json()
    assert fetched["id"] == created["id"]
    assert fetched["tags"] == ["t1"]


async def test_list_workflows_with_filter(client):
    for body in (
        _workflow_body("alpha-scan") | {"tags": ["scan"]},
        _workflow_body("beta-report") | {"tags": ["report"]},
    ):
        r = await client.post("/api/workflows", json=body)
        assert r.status == 201

    # Basic list returns both.
    resp = await client.get("/api/workflows")
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 2
    assert data["stats"]["scheduled"] == 0

    # Tag filter narrows to one.
    resp = await client.get("/api/workflows?tag=scan")
    data = await resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "alpha-scan"

    # Search filter.
    resp = await client.get("/api/workflows?search=report")
    data = await resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "beta-report"


async def test_update_workflow_rewrites_fields(client):
    resp = await client.post("/api/workflows", json=_workflow_body("orig"))
    wf = await resp.json()

    resp = await client.put(
        f"/api/workflows/{wf['id']}",
        json={"name": "renamed", "tags": ["a", "b"], "description": "new"},
    )
    assert resp.status == 200
    updated = await resp.json()
    assert updated["name"] == "renamed"
    assert updated["tags"] == ["a", "b"]
    assert updated["description"] == "new"
    assert updated["updatedAtMs"] >= wf["updatedAtMs"]


async def test_update_missing_returns_404(client):
    resp = await client.put("/api/workflows/wf_none", json={"name": "x"})
    assert resp.status == 404
    body = await resp.json()
    assert body["error"]["code"] == "workflow.not_found"


async def test_delete_workflow(client):
    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.delete(f"/api/workflows/{wf['id']}")
    assert resp.status == 200
    body = await resp.json()
    assert body == {"deleted": wf["id"]}

    resp = await client.get(f"/api/workflows/{wf['id']}")
    assert resp.status == 404


async def test_create_rejects_bad_step_kind(client):
    body = _workflow_body(step_kind="bogus")
    resp = await client.post("/api/workflows", json=body)
    assert resp.status == 400
    err = await resp.json()
    assert err["error"]["code"].startswith("workflow.validation.")


async def test_create_rejects_missing_name(client):
    resp = await client.post("/api/workflows", json={"steps": [], "inputs": []})
    assert resp.status == 400
    err = await resp.json()
    assert err["error"]["code"].startswith("workflow.validation.")


# ---------------------------------------------------------------------------
# Run + runs
# ---------------------------------------------------------------------------


async def test_run_workflow_echoes_inputs(client):
    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.post(
        f"/api/workflows/{wf['id']}/run",
        json={"inputs": {"target": "10.0.0.1"}},
    )
    assert resp.status == 200
    run = await resp.json()
    assert run["status"] == "ok"
    assert run["trigger"] == "api"
    assert run["runId"] == run["id"]
    assert run["stepResults"]["s1"]["output"] == {"target": "10.0.0.1"}

    resp = await client.get(f"/api/workflows/{wf['id']}/runs")
    assert resp.status == 200
    runs = (await resp.json())["items"]
    assert [r["id"] for r in runs] == [run["id"]]

    resp = await client.get(f"/api/workflows/{wf['id']}/runs/{run['id']}")
    assert resp.status == 200
    fetched = await resp.json()
    assert fetched["id"] == run["id"]
    assert fetched["status"] == "ok"


async def test_run_unknown_workflow_returns_404(client):
    resp = await client.post("/api/workflows/wf_nope/run", json={"inputs": {}})
    assert resp.status == 404
    err = await resp.json()
    assert err["error"]["code"] == "workflow.validation.not_found"


async def test_run_rejects_non_object_inputs(client):
    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.post(
        f"/api/workflows/{wf['id']}/run", json={"inputs": [1, 2, 3]}
    )
    assert resp.status == 400
    err = await resp.json()
    assert err["error"]["code"] == "workflow.validation.inputs"


async def test_get_run_missing_returns_404(client):
    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()
    resp = await client.get(f"/api/workflows/{wf['id']}/runs/run_none")
    assert resp.status == 404
    err = await resp.json()
    assert err["error"]["code"] == "run.not_found"


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


async def test_schedule_set_without_cron_returns_503(client):
    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.post(
        f"/api/workflows/{wf['id']}/schedule",
        json={"kind": "cron", "cronExpr": "0 9 * * *"},
    )
    assert resp.status == 503
    err = await resp.json()
    assert err["error"]["code"].endswith(".cron_unavailable")


async def test_schedule_set_then_delete(client_with_cron):
    client, cron, _svc = client_with_cron

    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.post(
        f"/api/workflows/{wf['id']}/schedule",
        json={"kind": "cron", "cronExpr": "0 9 * * *", "inputs": {"target": "1.1.1.1"}},
    )
    assert resp.status == 200
    attached = await resp.json()
    assert attached["scheduleRef"] is not None
    assert len(cron.jobs) == 1
    job = next(iter(cron.jobs.values()))
    # The cron payload encodes the __workflow__: prefix so on_cron_job
    # can dispatch it back to the service.
    assert job.message.startswith("__workflow__:")
    wf_id, inputs = WorkflowService.decode_cron_message(job.message)
    assert wf_id == wf["id"]
    assert inputs == {"target": "1.1.1.1"}

    resp = await client.delete(f"/api/workflows/{wf['id']}/schedule")
    assert resp.status == 200
    detached = await resp.json()
    assert detached["scheduleRef"] is None
    assert cron.jobs == {}


async def test_schedule_rejects_bad_kind(client_with_cron):
    client, _cron, _svc = client_with_cron

    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.post(
        f"/api/workflows/{wf['id']}/schedule", json={"kind": "forever"}
    )
    assert resp.status == 400
    err = await resp.json()
    assert err["error"]["code"] == "workflow.validation.schedule"


async def test_schedule_requires_matching_fields(client_with_cron):
    client, _cron, _svc = client_with_cron

    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    # kind=every without everyMs must fail.
    resp = await client.post(
        f"/api/workflows/{wf['id']}/schedule", json={"kind": "every"}
    )
    assert resp.status == 400


# ---------------------------------------------------------------------------
# Metadata endpoints
# ---------------------------------------------------------------------------


async def test_tools_endpoint(client):
    resp = await client.get("/api/workflows/_tools")
    assert resp.status == 200
    data = await resp.json()
    names = [item["name"] for item in data["items"]]
    assert names == ["probe", "scan"]  # sorted
    assert data["items"][0]["inputSchema"] == {
        "type": "object",
        "properties": {},
    }


async def test_agents_endpoint(client):
    resp = await client.get("/api/workflows/_agents")
    assert resp.status == 200
    data = await resp.json()
    names = [item["name"] for item in data["items"]]
    assert names == ["alpha", "beta"]


async def test_templates_endpoint(client):
    resp = await client.get("/api/workflows/_templates")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"items": []}


async def test_tools_endpoint_without_registry(tmp_path, client_factory):
    """When tool_registry is not wired the endpoint returns an empty list."""
    svc = _build_service(tmp_path)
    app = create_app(
        _mock_agent(),
        model_name="test",
        request_timeout=10.0,
        workflow_service=svc,
    )
    cli = await client_factory(app)
    resp = await cli.get("/api/workflows/_tools")
    assert resp.status == 200
    assert await resp.json() == {"items": []}


# ---------------------------------------------------------------------------
# Service-not-wired app
# ---------------------------------------------------------------------------


async def test_routes_absent_when_service_not_wired(client_factory):
    app = create_app(_mock_agent(), model_name="test", request_timeout=10.0)
    cli = await client_factory(app)
    # Without the workflow service the handlers never register; aiohttp
    # routes back to the catch-all handler which returns 404.
    resp = await cli.get("/api/workflows")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Cron prefix decoding through the service (covers the piece the gateway
# dispatches to).
# ---------------------------------------------------------------------------


async def test_cron_prefix_dispatch_round_trip(client_with_cron):
    """Schedule → cron message → decode → run round-trip used by on_cron_job."""
    client, cron, svc = client_with_cron

    resp = await client.post("/api/workflows", json=_workflow_body())
    wf = await resp.json()

    resp = await client.post(
        f"/api/workflows/{wf['id']}/schedule",
        json={"kind": "cron", "cronExpr": "*/5 * * * *", "inputs": {"target": "9.9.9.9"}},
    )
    assert resp.status == 200

    # Simulate the gateway's on_cron_job callback: detect the prefix and
    # dispatch. This is exactly the wiring used in _run_gateway.
    (job,) = cron.jobs.values()
    assert WorkflowService.is_cron_workflow_message(job.message)
    run = await svc.handle_cron_message(job.message)
    assert run.status == "ok"
    assert run.trigger == "cron"
    assert run.inputs == {"target": "9.9.9.9"}
    assert run.step_results["s1"].output == {"target": "9.9.9.9"}
