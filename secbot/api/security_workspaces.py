"""Shared API payload builders for security workspace views."""

from __future__ import annotations

import json as _json
from typing import Any

from aiohttp import web

from sqlalchemy.ext.asyncio import AsyncSession

from secbot.cmdb import repo
from secbot.cmdb.db import get_session
from secbot.cmdb.models import DEFAULT_ACTOR


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


async def _read_json(request: web.Request) -> dict[str, Any]:
    raw = await request.read()
    if not raw:
        return {}
    try:
        data = _json.loads(raw.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


async def public_asset_discovery_snapshot(
    session: AsyncSession,
    actor_id: str,
    *,
    scope_id: int | None = None,
    candidate_status: str | None = None,
) -> dict[str, Any]:
    """Return the Public Asset Discovery Workspace snapshot."""

    scopes = await repo.list_organization_scopes(session, actor_id)
    rules = await repo.list_asset_search_rules(session, actor_id, scope_id=scope_id)
    candidates = await repo.list_public_asset_candidates(
        session,
        actor_id,
        scope_id=scope_id,
        status=candidate_status,
    )
    candidate_payload = []
    for candidate in candidates:
        evidence = await repo.list_public_asset_evidence(
            session,
            actor_id,
            candidate_id=candidate.id,
            limit=50,
        )
        candidate_payload.append(repo.public_asset_candidate_to_dict(candidate, evidence=evidence))
    managed_assets = await repo.list_assets(session, actor_id)
    return {
        "scopes": [repo.organization_scope_to_dict(scope) for scope in scopes],
        "rules": [repo.asset_search_rule_to_dict(rule) for rule in rules],
        "candidates": candidate_payload,
        "managed_assets": [
            {
                "id": asset.id,
                "target": asset.target,
                "ip": asset.ip,
                "hostname": asset.hostname,
                "tags": asset.tags or {},
                "scan_id": asset.scan_id,
                "created_at": asset.created_at.isoformat(),
                "updated_at": asset.updated_at.isoformat(),
            }
            for asset in managed_assets
        ],
    }


async def white_box_workspace_snapshot(
    session: AsyncSession,
    actor_id: str,
    *,
    assessment_id: str | None = None,
) -> dict[str, Any]:
    """Return the White-Box Workspace snapshot."""

    if assessment_id:
        assessment = await repo.get_white_box_assessment(session, actor_id, assessment_id)
        assessments = [] if assessment is None else [assessment]
    else:
        assessments = list(await repo.list_white_box_assessments(session, actor_id))
    findings = await repo.list_white_box_findings(
        session,
        actor_id,
        assessment_id=assessment_id,
    )
    finding_payload = []
    for finding in findings:
        evidence = await repo.get_white_box_evidence(
            session,
            actor_id,
            finding.evidence_id,
        )
        document_rows = [
            row
            for row in await repo.list_white_box_reproduction_documents(
                session,
                actor_id,
                finding_id=finding.id,
            )
        ]
        finding_payload.append(
            repo.white_box_finding_to_dict(
                finding,
                evidence=evidence,
                reproduction_documents=document_rows,
            )
        )
    evidence_rows = await repo.list_white_box_evidence(
        session,
        actor_id,
        assessment_id=assessment_id,
    )
    return {
        "assessments": [repo.white_box_assessment_to_dict(row) for row in assessments],
        "evidence": [repo.white_box_evidence_to_dict(row) for row in evidence_rows],
        "findings": finding_payload,
    }


async def handle_public_assets(request: web.Request) -> web.Response:
    """GET /api/public-assets."""

    scope_raw = (request.query.get("scope_id") or "").strip()
    status = (request.query.get("status") or "").strip() or None
    scope_id: int | None = None
    if scope_raw:
        try:
            scope_id = int(scope_raw)
        except ValueError:
            return _error(400, "public_assets.validation.scope_id", "scope_id must be an integer")
    try:
        async with get_session() as session:
            payload = await public_asset_discovery_snapshot(
                session,
                DEFAULT_ACTOR,
                scope_id=scope_id,
                candidate_status=status,
            )
    except ValueError as exc:
        return _error(400, "public_assets.validation", str(exc))
    return web.json_response(payload)


async def handle_create_scope(request: web.Request) -> web.Response:
    """POST /api/public-assets/scopes."""

    try:
        body = await _read_json(request)
    except ValueError as exc:
        return _error(400, "public_assets.validation.body", str(exc))
    try:
        async with get_session() as session:
            scope = await repo.create_organization_scope(
                session,
                DEFAULT_ACTOR,
                name=str(body.get("name") or ""),
                aliases=body.get("aliases"),
                root_domains=body.get("root_domains") or body.get("rootDomains"),
                icp_subjects=body.get("icp_subjects") or body.get("icpSubjects"),
                certificate_subjects=body.get("certificate_subjects")
                or body.get("certificateSubjects"),
                asns=body.get("asns"),
                ip_ranges=body.get("ip_ranges") or body.get("ipRanges"),
                include_terms=body.get("include_terms") or body.get("includeTerms"),
                exclude_terms=body.get("exclude_terms") or body.get("excludeTerms"),
                notes=body.get("notes"),
            )
            await session.commit()
            return web.json_response(repo.organization_scope_to_dict(scope), status=201)
    except (LookupError, ValueError) as exc:
        return _error(400, "public_assets.validation", str(exc))


async def handle_record_observation(request: web.Request) -> web.Response:
    """POST /api/public-assets/observations."""

    try:
        body = await _read_json(request)
        scope_id = int(body.get("scope_id") or body.get("scopeId"))
    except (TypeError, ValueError) as exc:
        return _error(400, "public_assets.validation.body", str(exc))
    try:
        async with get_session() as session:
            candidate, evidence, created = await repo.record_public_asset_observation(
                session,
                DEFAULT_ACTOR,
                scope_id=scope_id,
                source=str(body.get("source") or ""),
                host=str(body.get("host") or body.get("observed_host") or body.get("url") or ""),
                rule_id=body.get("rule_id") or body.get("ruleId"),
                port=body.get("port"),
                protocol=body.get("protocol"),
                url=body.get("url"),
                title=body.get("title"),
                banner=body.get("banner"),
                certificate=body.get("certificate"),
                raw=body.get("raw"),
            )
            await session.commit()
            return web.json_response(
                {
                    "candidate": repo.public_asset_candidate_to_dict(candidate),
                    "evidence": repo.public_asset_evidence_to_dict(evidence),
                    "created_candidate": created,
                },
                status=201 if created else 200,
            )
    except (LookupError, ValueError) as exc:
        return _error(400, "public_assets.validation", str(exc))


async def handle_promote_candidate(request: web.Request) -> web.Response:
    """POST /api/public-assets/candidates/{id}/promote."""

    try:
        candidate_id = int(request.match_info["id"])
        body = await _read_json(request)
    except ValueError as exc:
        return _error(400, "public_assets.validation.body", str(exc))
    try:
        async with get_session() as session:
            candidate, asset = await repo.promote_public_asset_candidate(
                session,
                DEFAULT_ACTOR,
                candidate_id,
                review_note=body.get("review_note") or body.get("reviewNote"),
            )
            await session.commit()
            return web.json_response(
                {
                    "candidate": repo.public_asset_candidate_to_dict(candidate),
                    "managed_asset": {
                        "id": asset.id,
                        "target": asset.target,
                        "ip": asset.ip,
                        "hostname": asset.hostname,
                        "scan_id": asset.scan_id,
                    },
                }
            )
    except LookupError as exc:
        return _error(404, "public_assets.not_found", str(exc))
    except ValueError as exc:
        return _error(400, "public_assets.validation", str(exc))


async def handle_scan_prompt_draft(request: web.Request) -> web.Response:
    """POST /api/public-assets/scan-prompt-draft."""

    try:
        body = await _read_json(request)
        asset_ids = body.get("asset_ids") or body.get("assetIds") or []
        if not isinstance(asset_ids, list):
            raise ValueError("asset_ids must be a list")
    except ValueError as exc:
        return _error(400, "public_assets.validation.body", str(exc))
    try:
        async with get_session() as session:
            payload = await repo.build_scan_prompt_draft(
                session,
                DEFAULT_ACTOR,
                asset_ids=asset_ids,
                scan_request=str(body.get("scan_request") or body.get("scanRequest") or ""),
            )
            return web.json_response(payload)
    except LookupError as exc:
        return _error(404, "public_assets.not_found", str(exc))
    except ValueError as exc:
        return _error(400, "public_assets.validation", str(exc))


async def handle_white_box_workspace(request: web.Request) -> web.Response:
    """GET /api/white-box."""

    assessment_id = (request.query.get("assessment_id") or "").strip() or None
    async with get_session() as session:
        payload = await white_box_workspace_snapshot(
            session,
            DEFAULT_ACTOR,
            assessment_id=assessment_id,
        )
    return web.json_response(payload)


async def handle_create_white_box_assessment(request: web.Request) -> web.Response:
    """POST /api/white-box/assessments."""

    try:
        body = await _read_json(request)
        package_name = str(body.get("package_name") or body.get("packageName") or "")
        compressed_size = int(body.get("compressed_size_bytes") or body.get("compressedSizeBytes") or 0)
        extracted_size = int(body.get("extracted_size_bytes") or body.get("extractedSizeBytes") or 0)
    except ValueError as exc:
        return _error(400, "white_box.validation.body", str(exc))
    try:
        async with get_session() as session:
            assessment = await repo.create_white_box_assessment(
                session,
                DEFAULT_ACTOR,
                package_name=package_name,
                compressed_size_bytes=compressed_size,
                extracted_size_bytes=extracted_size,
                language_summary=body.get("language_summary") or body.get("languageSummary"),
                archive_path=body.get("archive_path") or body.get("archivePath"),
                extracted_path=body.get("extracted_path") or body.get("extractedPath"),
            )
            await session.commit()
            return web.json_response(repo.white_box_assessment_to_dict(assessment), status=201)
    except ValueError as exc:
        return _error(400, "white_box.validation", str(exc))


async def handle_transition_white_box_assessment(request: web.Request) -> web.Response:
    """POST /api/white-box/assessments/{id}/transition."""

    try:
        body = await _read_json(request)
        status = str(body.get("status") or "")
    except ValueError as exc:
        return _error(400, "white_box.validation.body", str(exc))
    try:
        async with get_session() as session:
            assessment = await repo.transition_white_box_assessment(
                session,
                DEFAULT_ACTOR,
                request.match_info["id"],
                status=status,
                error=body.get("error"),
            )
            await session.commit()
            return web.json_response(repo.white_box_assessment_to_dict(assessment))
    except LookupError as exc:
        return _error(404, "white_box.not_found", str(exc))
    except ValueError as exc:
        return _error(400, "white_box.validation", str(exc))


async def handle_purge_white_box_source(request: web.Request) -> web.Response:
    """POST /api/white-box/assessments/{id}/purge-source."""

    try:
        async with get_session() as session:
            assessment = await repo.purge_white_box_source_material(
                session,
                DEFAULT_ACTOR,
                request.match_info["id"],
            )
            await session.commit()
            return web.json_response(repo.white_box_assessment_to_dict(assessment))
    except LookupError as exc:
        return _error(404, "white_box.not_found", str(exc))


async def handle_add_white_box_evidence(request: web.Request) -> web.Response:
    """POST /api/white-box/evidence."""

    try:
        body = await _read_json(request)
    except ValueError as exc:
        return _error(400, "white_box.validation.body", str(exc))
    try:
        async with get_session() as session:
            evidence = await repo.add_white_box_evidence(
                session,
                DEFAULT_ACTOR,
                assessment_id=str(body.get("assessment_id") or body.get("assessmentId") or ""),
                analyzer=str(body.get("analyzer") or ""),
                vulnerability_type=str(
                    body.get("vulnerability_type") or body.get("vulnerabilityType") or "other"
                ),
                confidence=str(body.get("confidence") or "low"),
                primary_file=str(body.get("primary_file") or body.get("primaryFile") or ""),
                primary_sink_line=body.get("primary_sink_line") or body.get("primarySinkLine"),
                entry_points=body.get("entry_points") or body.get("entryPoints"),
                sources=body.get("sources"),
                sinks=body.get("sinks"),
                sanitizers=body.get("sanitizers"),
                data_flow=body.get("data_flow") or body.get("dataFlow"),
                prerequisites=body.get("prerequisites"),
                request_samples=body.get("request_samples") or body.get("requestSamples"),
                remediation=body.get("remediation"),
                raw=body.get("raw"),
            )
            await session.commit()
            return web.json_response(repo.white_box_evidence_to_dict(evidence), status=201)
    except LookupError as exc:
        return _error(404, "white_box.not_found", str(exc))
    except ValueError as exc:
        return _error(400, "white_box.validation", str(exc))


async def handle_create_white_box_finding(request: web.Request) -> web.Response:
    """POST /api/white-box/findings."""

    try:
        body = await _read_json(request)
        evidence_id = int(body.get("evidence_id") or body.get("evidenceId"))
    except (TypeError, ValueError) as exc:
        return _error(400, "white_box.validation.body", str(exc))
    try:
        async with get_session() as session:
            finding = await repo.upsert_white_box_finding_from_evidence(
                session,
                DEFAULT_ACTOR,
                evidence_id=evidence_id,
                title=str(body.get("title") or ""),
                category=str(body.get("category") or "other"),
                status=str(body.get("status") or "open"),
            )
            await session.commit()
            evidence = await repo.get_white_box_evidence(session, DEFAULT_ACTOR, finding.evidence_id)
            return web.json_response(
                repo.white_box_finding_to_dict(finding, evidence=evidence),
                status=201,
            )
    except LookupError as exc:
        return _error(404, "white_box.not_found", str(exc))
    except ValueError as exc:
        return _error(400, "white_box.validation", str(exc))


async def handle_create_white_box_reproduction_document(request: web.Request) -> web.Response:
    """POST /api/white-box/findings/{id}/reproduction-document."""

    try:
        finding_id = int(request.match_info["id"])
    except ValueError as exc:
        return _error(400, "white_box.validation.finding_id", str(exc))
    try:
        async with get_session() as session:
            document = await repo.create_white_box_reproduction_document(
                session,
                DEFAULT_ACTOR,
                finding_id=finding_id,
            )
            await session.commit()
            return web.json_response(
                repo.white_box_reproduction_document_to_dict(document),
                status=201,
            )
    except LookupError as exc:
        return _error(404, "white_box.not_found", str(exc))


def register_security_workspace_routes(app: web.Application) -> None:
    """Register Public Asset Discovery and White-Box Workspace routes."""

    app.router.add_get("/api/public-assets", handle_public_assets)
    app.router.add_post("/api/public-assets/scopes", handle_create_scope)
    app.router.add_post("/api/public-assets/observations", handle_record_observation)
    app.router.add_post("/api/public-assets/candidates/{id}/promote", handle_promote_candidate)
    app.router.add_post("/api/public-assets/scan-prompt-draft", handle_scan_prompt_draft)

    app.router.add_get("/api/white-box", handle_white_box_workspace)
    app.router.add_post("/api/white-box/assessments", handle_create_white_box_assessment)
    app.router.add_post(
        "/api/white-box/assessments/{id}/transition",
        handle_transition_white_box_assessment,
    )
    app.router.add_post(
        "/api/white-box/assessments/{id}/purge-source",
        handle_purge_white_box_source,
    )
    app.router.add_post("/api/white-box/evidence", handle_add_white_box_evidence)
    app.router.add_post("/api/white-box/findings", handle_create_white_box_finding)
    app.router.add_post(
        "/api/white-box/findings/{id}/reproduction-document",
        handle_create_white_box_reproduction_document,
    )
