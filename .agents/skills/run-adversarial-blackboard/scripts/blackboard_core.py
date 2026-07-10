#!/usr/bin/env python3
"""Core protocol logic for adversarial blackboard runs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STAGES = [
    "00-context.md",
    "10-proposal.md",
    "20-critique.md",
    "25-rebuttal.md",
    "30-verdict.md",
    "40-checks.json",
]
MARKDOWN_SECTIONS = {
    "00-context.md": ("# E0 Frozen Context", "## Evidence register"),
    "10-proposal.md": ("# A Proposal", "## Claims"),
    "20-critique.md": ("# B Critique", "## Critique coverage"),
    "25-rebuttal.md": ("# A2 Rebuttal or Revision", "## Consolidated effective proposal"),
    "30-verdict.md": ("# J Verdict", "## Run decision"),
}
SEVERITIES = ("low", "medium", "high", "critical")
ATTACK_TYPES = {"disproof", "missing_evidence", "risk"}
RESPONSE_ACTIONS = {"rebut", "accept_and_revise", "downgrade_to_hypothesis", "withdraw"}
RULING_STATUSES = {
    "sustained",
    "rejected",
    "unresolved",
    "out_of_scope",
    "resolved_by_revision",
}
BLOCKING_RULINGS = {"sustained", "unresolved"}
TERMINAL_DECISIONS = {"accept", "reject"}
VERIFICATION_SCOPES = {"record_presence", "independent_operational"}
INSTRUCTION_SCAN_STATUSES = {"passed", "not_applicable"}
ID_PATTERNS = {
    "evidence": re.compile(r"^E-\d{3,}$"),
    "claim": re.compile(r"^C-\d{3,}$"),
    "attack": re.compile(r"^ATK-\d{3,}$"),
    "response": re.compile(r"^RSP-\d{3,}$"),
    "ruling": re.compile(r"^V-\d{3,}$"),
    "decision": re.compile(r"^D-\d{3,}$"),
    "check": re.compile(r"^CHK-\d{3,}$"),
}
ID_SECTION = re.compile(r"(?ms)^### ((?:E|C|ATK|RSP|V|D)-\d{3,})\s*$\n(.*?)(?=^### |^## |\Z)")
LABELED_FIELD = re.compile(r"^- ([A-Za-z][A-Za-z /_-]*):\s*(.*?)\s*$")
EVIDENCE_REFERENCE = re.compile(r"E-\d{3,}")


class BlackboardError(Exception):
    """Report a user-correctable run error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlackboardError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BlackboardError(f"expected a JSON object in {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def templates(
    question: str,
    severity: str,
    revision: str,
    time_budget_minutes: int,
    token_budget: int,
    created_at: str,
    deadline_at: str,
) -> dict[str, str]:
    return {
        "00-context.md": f"""# E0 Frozen Context

## Decision metadata

- Question: {question}
- Severity: {severity}
- Snapshot revision/hash: {revision}
- Rebuttal rounds: 1
- Time budget: {time_budget_minutes} minutes
- Token budget: {token_budget}
- Created at: {created_at}
- Deadline at: {deadline_at}

## Hard constraints

TODO: Replace with pre-agreed constraints.

## Evidence register

### E-001

- Source: TODO: Add the source.
- Revision/hash: TODO: Add the evidence revision or hash.
- Reproduction: TODO: Add the reproduction method.
- Verification state: unverified
- Verification scope: TODO: Use record_presence or independent_operational.
- Instruction scan: TODO: Use passed or not_applicable.

## Known facts, hypotheses, and conflicts

TODO: Separate verified facts from assumptions and conflicts.
""",
        "10-proposal.md": """# A Proposal

## Position

TODO: State what is and is not proposed.

## Claims

### C-001

- Claim: TODO: Add a falsifiable claim.
- Evidence: E-001
- Mechanism: TODO: Add a concrete mechanism.
- Assumptions/limits: TODO: Add conditions and limits.
- Falsifier: TODO: Add an observation that defeats the claim.
""",
        "20-critique.md": """# B Critique

Do not propose a replacement design. A minimal falsification test is allowed.

## Critique coverage

- Critique coverage: TODO: Set to complete after reviewing all claims.
- Reviewer: TODO: Add reviewer identity.

## Attacks

### ATK-001

- Target claim: C-001
- Type: TODO: Use disproof, missing_evidence, or risk.
- Severity: TODO: Use low, medium, high, or critical.
- Evidence: E-001
- Attack: TODO: Add the defeater.
- Minimal falsification test: TODO: Add a test or write none.

Remove this record and write `No attacks found` only after completed coverage finds no attacks.
""",
        "25-rebuttal.md": """# A2 Rebuttal or Revision

Use one pass. Cite only E0 evidence. Return the run if outside evidence is needed.

## Responses

### RSP-001

- Attack: ATK-001
- Action: TODO: Use rebut, accept_and_revise, downgrade_to_hypothesis, or withdraw.
- Evidence: E-001
- Response or exact revision: TODO: Add the response or exact revision.

Remove this record and write `No responses required` only for an explicit zero-attack run.

## Consolidated effective proposal

TODO: Restate the effective proposal after all revisions, downgrades, and withdrawals.
""",
        "30-verdict.md": """# J Verdict

Do not invent attacks or designs. Abstain or return when the record is insufficient.

## Rulings

### V-001

- Attack: ATK-001
- Status: TODO: Add a ruling status.
- Evidence: E-001
- Reason and evidence: TODO: Add the reason.

Remove this record and write `No rulings required` only for an explicit zero-attack run.

## Run decision

### D-001

- Decision status: pending
- Rationale: TODO: Add the decision rationale.
""",
    }


def initial_checks(
    question: str,
    severity: str,
    revision: str,
    time_budget_minutes: int,
    token_budget: int,
    created_at: str,
    deadline_at: str,
) -> dict[str, Any]:
    return {
        "run": {
            "question": question,
            "severity": severity,
            "revision": revision,
            "created_at": created_at,
            "deadline_at": deadline_at,
            "finalized_at": None,
            "limits": {
                "rebuttal_rounds": 1,
                "time_budget_minutes": time_budget_minutes,
                "token_budget": token_budget,
            },
        },
        "evidence": [
            {
                "id": "E-001",
                "source": "TODO: Add the source.",
                "revision_or_hash": "TODO: Add the evidence revision or hash.",
                "reproduction": "TODO: Add the reproduction method.",
                "verification_state": "unverified",
                "verification_scope": "TODO: Use record_presence or independent_operational.",
                "instruction_scan": "TODO: Use passed or not_applicable.",
            }
        ],
        "claims": [
            {
                "id": "C-001",
                "evidence_ids": ["E-001"],
                "summary": "TODO: Add the claim.",
                "mechanism": "TODO: Add the mechanism.",
                "assumptions_limits": "TODO: Add assumptions and limits.",
                "falsifier": "TODO: Add the falsifier.",
            }
        ],
        "attacks": [
            {
                "id": "ATK-001",
                "claim_id": "C-001",
                "evidence_ids": ["E-001"],
                "type": "TODO: Use disproof, missing_evidence, or risk.",
                "severity": "TODO: Use low, medium, high, or critical.",
                "summary": "TODO: Add the defeater.",
            }
        ],
        "responses": [
            {
                "id": "RSP-001",
                "attack_id": "ATK-001",
                "action": "TODO: Add the response action.",
                "evidence_ids": ["E-001"],
                "summary": "TODO: Add the response or exact revision.",
            }
        ],
        "rulings": [
            {
                "id": "V-001",
                "attack_id": "ATK-001",
                "status": "TODO: Add the ruling status.",
                "evidence_ids": ["E-001"],
                "reason": "TODO: Add the reason.",
            }
        ],
        "review_completion": {
            "critique_completed": False,
            "coverage": "TODO: Use all_claims.",
            "reviewer": "TODO: Add reviewer identity.",
        },
        "deterministic_checks": [
            {
                "id": "CHK-001",
                "method": "TODO: Add the command or method.",
                "status": "not_run",
                "evidence_ids": ["E-001"],
                "result": "TODO: Add the result artifact or output.",
            }
        ],
        "decision": {"id": "D-001", "status": "pending", "summary": "TODO: Add rationale."},
        "human_signoff": {
            "required": severity in {"high", "critical"},
            "status": "pending" if severity in {"high", "critical"} else "not_required",
            "reviewer": "",
            "note": "",
        },
    }


def init_run(
    run_dir: Path,
    question: str,
    severity: str,
    revision: str,
    time_budget_minutes: int = 30,
    token_budget: int = 20_000,
) -> None:
    question, revision = question.strip(), revision.strip()
    if severity not in SEVERITIES:
        raise BlackboardError(f"severity must be one of: {', '.join(SEVERITIES)}")
    if not question or not revision:
        raise BlackboardError("question and revision must be non-empty")
    if "\n" in question or "\n" in revision:
        raise BlackboardError("question and revision must each fit on one line")
    if time_budget_minutes < 1 or token_budget < 1:
        raise BlackboardError("time and token budgets must be positive")
    if run_dir.exists():
        raise BlackboardError(f"run directory already exists: {run_dir}")
    created = datetime.now(timezone.utc).replace(microsecond=0)
    created_at = created.isoformat()
    deadline_at = (created + timedelta(minutes=time_budget_minutes)).isoformat()
    run_dir.mkdir(parents=True)
    for name, content in templates(
        question,
        severity,
        revision,
        time_budget_minutes,
        token_budget,
        created_at,
        deadline_at,
    ).items():
        (run_dir / name).write_text(content, encoding="utf-8")
    atomic_json(
        run_dir / "40-checks.json",
        initial_checks(
            question,
            severity,
            revision,
            time_budget_minutes,
            token_budget,
            created_at,
            deadline_at,
        ),
    )
    atomic_json(
        run_dir / "manifest.json",
        {
            "schema_version": 2,
            "question": question,
            "severity": severity,
            "revision": revision,
            "created_at": created_at,
            "deadline_at": deadline_at,
            "stage_order": STAGES,
            "limits": {
                "rebuttal_rounds": 1,
                "time_budget_minutes": time_budget_minutes,
                "token_budget": token_budget,
            },
            "seals": [],
        },
    )
    print(f"initialized: {run_dir}")


def manifest_errors(run_dir: Path, manifest: dict[str, Any], complete: bool) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 2:
        errors.append("unsupported manifest schema_version")
    if manifest.get("stage_order") != STAGES:
        errors.append("manifest stage_order does not match the protocol")
    if manifest.get("severity") not in SEVERITIES:
        errors.append("manifest severity is invalid")
    limits = manifest.get("limits")
    if not isinstance(limits, dict):
        errors.append("manifest limits must be an object")
        limits = {}
    if limits.get("rebuttal_rounds") != 1:
        errors.append("the protocol allows exactly one rebuttal round")
    for field in ("time_budget_minutes", "token_budget"):
        value = limits.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"manifest {field} must be a positive integer")
    seals = manifest.get("seals")
    if not isinstance(seals, list):
        return errors + ["manifest seals must be a list"]
    if complete and len(seals) != len(STAGES):
        errors.append(f"incomplete stage seals: {len(seals)}/{len(STAGES)}")
    if len(seals) > len(STAGES):
        errors.append("manifest contains too many seals")
    seal_times: list[datetime] = []
    for index, seal in enumerate(seals):
        expected = STAGES[index] if index < len(STAGES) else None
        if not isinstance(seal, dict) or seal.get("stage") != expected:
            errors.append(f"seal {index + 1} is out of order")
            continue
        path = run_dir / expected
        if not path.is_file():
            errors.append(f"sealed stage is missing: {expected}")
        elif seal.get("sha256") != digest(path):
            errors.append(f"sealed stage was mutated: {expected}")
        try:
            sealed_at = datetime.fromisoformat(seal["sealed_at"])
            if sealed_at.tzinfo is None:
                raise ValueError("timestamp must include timezone")
            seal_times.append(sealed_at)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid sealed_at for {expected}: {exc}")
    try:
        created_at = datetime.fromisoformat(manifest["created_at"])
        deadline_at = datetime.fromisoformat(manifest["deadline_at"])
        if created_at.tzinfo is None or deadline_at.tzinfo is None:
            raise ValueError("timestamps must include timezones")
        if deadline_at != created_at + timedelta(minutes=limits.get("time_budget_minutes", 0)):
            errors.append("manifest deadline_at does not match created_at plus the time budget")
        previous = created_at
        for sealed_at in seal_times:
            if sealed_at < previous:
                errors.append("stage sealed_at timestamps are not monotonic")
                break
            previous = sealed_at
        if complete and len(seal_times) == len(STAGES) and seal_times[-1] > deadline_at:
            errors.append("run exceeded its deadline before the final seal")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid run timing metadata: {exc}")
    return errors


def seal_stage(run_dir: Path, stage: str) -> None:
    manifest_path = run_dir / "manifest.json"
    manifest = read_json(manifest_path)
    errors = manifest_errors(run_dir, manifest, complete=False)
    if errors:
        raise BlackboardError("; ".join(errors))
    seals = manifest["seals"]
    if len(seals) >= len(STAGES):
        raise BlackboardError("all stages are already sealed")
    expected = STAGES[len(seals)]
    if stage != expected:
        raise BlackboardError(f"next stage must be {expected}, not {stage}")
    path = run_dir / stage
    if not path.is_file():
        raise BlackboardError(f"stage does not exist: {path}")
    sealed_at = utc_now()
    if stage == "40-checks.json":
        structured = read_json(path)
        run = structured.get("run")
        if not isinstance(run, dict):
            raise BlackboardError("40-checks.json run metadata must be an object")
        if run.get("deadline_at") != manifest.get("deadline_at"):
            raise BlackboardError("structured deadline_at does not match manifest")
        try:
            now = datetime.fromisoformat(sealed_at)
            deadline = datetime.fromisoformat(run["deadline_at"])
            if deadline.tzinfo is None:
                raise ValueError("deadline must include timezone")
        except (KeyError, TypeError, ValueError) as exc:
            raise BlackboardError(f"invalid structured deadline_at: {exc}") from exc
        if now > deadline:
            raise BlackboardError("cannot seal 40-checks.json after the run deadline")
        run["finalized_at"] = sealed_at
        atomic_json(path, structured)
    seals.append({"stage": stage, "sha256": digest(path), "sealed_at": sealed_at})
    atomic_json(manifest_path, manifest)
    print(f"sealed: {stage}")


def valid_id(errors: list[str], seen: set[str], kind: str, value: Any, location: str) -> bool:
    if not isinstance(value, str) or not ID_PATTERNS[kind].fullmatch(value):
        errors.append(f"invalid {kind} id at {location}: {value!r}")
        return False
    if value in seen:
        errors.append(f"duplicate {kind} id: {value}")
        return False
    seen.add(value)
    return True


def object_list(errors: list[str], data: dict[str, Any], field: str, required: bool = False) -> list[dict[str, Any]]:
    value = data.get(field)
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return []
    objects = [item for item in value if isinstance(item, dict)]
    if len(objects) != len(value):
        errors.append(f"every {field} item must be an object")
    if required and not objects:
        errors.append(f"at least one {field} record is required")
    return objects


def require_text(errors: list[str], item: dict[str, Any], field: str, owner: str) -> None:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{owner} lacks {field}")


def reference_ids(
    errors: list[str], item: dict[str, Any], field: str, allowed: set[str], owner: str, required: bool = False
) -> None:
    values = item.get(field)
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        errors.append(f"{owner} {field} must be a list of IDs")
        return
    if required and not values:
        errors.append(f"{owner} requires at least one {field} entry")
    for value in values:
        if value not in allowed:
            errors.append(f"{owner} references unknown evidence: {value}")


def markdown_errors(run_dir: Path) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    documents: dict[str, str] = {}
    for name, sections in MARKDOWN_SECTIONS.items():
        try:
            text = (run_dir / name).read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read {name}: {exc}")
            continue
        documents[name] = text
        if len(text.strip()) < 40:
            errors.append(f"Markdown stage is empty or incomplete: {name}")
        if "TODO:" in text:
            errors.append(f"TODO marker remains in {name}")
        for section in sections:
            if section not in text:
                errors.append(f"required section missing from {name}: {section}")
    return errors, documents


def markdown_records(errors: list[str], stage: str, text: str) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for match in ID_SECTION.finditer(text):
        record_id, body = match.groups()
        if record_id in records:
            errors.append(f"duplicate Markdown record in {stage}: {record_id}")
            continue
        fields: dict[str, str] = {}
        for line in body.splitlines():
            field_match = LABELED_FIELD.fullmatch(line)
            if not field_match:
                continue
            label, value = field_match.groups()
            if label in fields:
                errors.append(f"duplicate Markdown field in {stage} {record_id}: {label}")
            fields[label] = value.strip()
        records[record_id] = fields
    return records


def markdown_field(
    errors: list[str], records: dict[str, dict[str, str]], record_id: str, label: str, stage: str
) -> str | None:
    record = records.get(record_id)
    if record is None:
        errors.append(f"{record_id} is missing from {stage}")
        return None
    value = record.get(label)
    if value is None or not value.strip():
        errors.append(f"{stage} {record_id} lacks {label}")
        return None
    return value.strip()


def compare_markdown_field(
    errors: list[str], records: dict[str, dict[str, str]], record_id: str, label: str, expected: Any, stage: str
) -> None:
    actual = markdown_field(errors, records, record_id, label, stage)
    if actual is not None and actual != expected:
        errors.append(f"{stage} {record_id} {label} disagrees with 40-checks.json")


def compare_markdown_evidence(
    errors: list[str], records: dict[str, dict[str, str]], record_id: str, expected: Any, stage: str
) -> None:
    actual = markdown_field(errors, records, record_id, "Evidence", stage)
    if actual is None:
        return
    actual_ids = EVIDENCE_REFERENCE.findall(actual)
    if not isinstance(expected, list) or actual_ids != expected:
        errors.append(f"{stage} {record_id} Evidence disagrees with 40-checks.json")


def required_subsection(errors: list[str], text: str, start: str, end: str, label: str) -> None:
    start_marker, end_marker = f"{start}\n", f"{end}\n"
    start_index = text.find(start_marker)
    end_index = text.find(end_marker, start_index + len(start_marker)) if start_index >= 0 else -1
    if start_index < 0 or end_index < 0:
        errors.append(f"required proposal subsection is missing: {label}")
        return
    value = text[start_index + len(start_marker) : end_index].strip()
    if not value:
        errors.append(f"proposal {label} must be non-empty")


def metadata_errors(
    manifest: dict[str, Any], structured: dict[str, Any], context: str
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    run = structured.get("run")
    if not isinstance(run, dict):
        return ["40-checks.json run metadata must be an object"], {}
    for field in ("question", "severity", "revision", "limits", "created_at", "deadline_at"):
        if run.get(field) != manifest.get(field):
            errors.append(f"manifest and final structured metadata disagree on {field}")
    limits = run.get("limits") if isinstance(run.get("limits"), dict) else {}
    expected_context = [
        f"- Question: {run.get('question')}",
        f"- Severity: {run.get('severity')}",
        f"- Snapshot revision/hash: {run.get('revision')}",
        f"- Rebuttal rounds: {limits.get('rebuttal_rounds')}",
        f"- Time budget: {limits.get('time_budget_minutes')} minutes",
        f"- Token budget: {limits.get('token_budget')}",
        f"- Created at: {run.get('created_at')}",
        f"- Deadline at: {run.get('deadline_at')}",
    ]
    for value in expected_context:
        if value not in context:
            errors.append(f"frozen context does not contain final metadata: {value}")
    try:
        created_at = datetime.fromisoformat(run["created_at"])
        deadline_at = datetime.fromisoformat(run["deadline_at"])
        final_sealed_at = datetime.fromisoformat(manifest["seals"][-1]["sealed_at"])
        if created_at.tzinfo is None or deadline_at.tzinfo is None or final_sealed_at.tzinfo is None:
            raise ValueError("timestamps must include timezones")
        if deadline_at != created_at + timedelta(minutes=limits.get("time_budget_minutes", 0)):
            errors.append("final structured deadline_at does not match created_at plus the time budget")
        if final_sealed_at > deadline_at:
            errors.append("run exceeded its sealed deadline before the final seal")
        if run.get("finalized_at") != manifest["seals"][-1].get("sealed_at"):
            errors.append("finalized_at does not match the final manifest sealed_at")
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid final structured timing metadata: {exc}")
    return errors, run


def gate_errors(run_dir: Path, manifest: dict[str, Any]) -> list[str]:
    errors = manifest_errors(run_dir, manifest, complete=True)
    try:
        structured = read_json(run_dir / "40-checks.json")
    except BlackboardError as exc:
        return errors + [str(exc)]
    md_errors, documents = markdown_errors(run_dir)
    errors.extend(md_errors)
    records = {
        stage: markdown_records(errors, stage, text) for stage, text in documents.items()
    }
    if "TODO:" in json.dumps(structured, ensure_ascii=False):
        errors.append("TODO marker remains in 40-checks.json")
    metadata, run = metadata_errors(manifest, structured, documents.get("00-context.md", ""))
    errors.extend(metadata)

    evidence = object_list(errors, structured, "evidence", required=True)
    evidence_ids: set[str] = set()
    operational_evidence_ids: set[str] = set()
    for index, item in enumerate(evidence):
        evidence_id = item.get("id")
        owner = f"evidence {evidence_id or index}"
        valid_id(errors, evidence_ids, "evidence", evidence_id, f"evidence[{index}]")
        for field in ("source", "revision_or_hash", "reproduction"):
            require_text(errors, item, field, owner)
        if item.get("verification_state") != "verified":
            errors.append(f"{owner} is not verified")
        if item.get("verification_scope") not in VERIFICATION_SCOPES:
            errors.append(f"{owner} has invalid verification_scope")
        if item.get("instruction_scan") not in INSTRUCTION_SCAN_STATUSES:
            errors.append(f"{owner} has invalid instruction_scan")
        if item.get("verification_scope") == "independent_operational" and isinstance(
            evidence_id, str
        ):
            operational_evidence_ids.add(evidence_id)
        if isinstance(evidence_id, str):
            context_records = records.get("00-context.md", {})
            compare_markdown_field(
                errors,
                context_records,
                evidence_id,
                "Source",
                item.get("source"),
                "00-context.md",
            )
            compare_markdown_field(
                errors,
                context_records,
                evidence_id,
                "Revision/hash",
                item.get("revision_or_hash"),
                "00-context.md",
            )
            compare_markdown_field(
                errors,
                context_records,
                evidence_id,
                "Reproduction",
                item.get("reproduction"),
                "00-context.md",
            )
            compare_markdown_field(
                errors,
                context_records,
                evidence_id,
                "Verification state",
                item.get("verification_state"),
                "00-context.md",
            )
            compare_markdown_field(
                errors,
                context_records,
                evidence_id,
                "Verification scope",
                item.get("verification_scope"),
                "00-context.md",
            )
            compare_markdown_field(
                errors,
                context_records,
                evidence_id,
                "Instruction scan",
                item.get("instruction_scan"),
                "00-context.md",
            )

    claims = object_list(errors, structured, "claims", required=True)
    proposal = documents.get("10-proposal.md", "")
    required_subsection(errors, proposal, "## Position", "## Claims", "position")
    claim_ids: set[str] = set()
    for index, item in enumerate(claims):
        claim_id = item.get("id")
        owner = f"claim {claim_id or index}"
        valid_id(errors, claim_ids, "claim", claim_id, f"claims[{index}]")
        for field in ("summary", "mechanism", "assumptions_limits", "falsifier"):
            require_text(errors, item, field, owner)
        reference_ids(errors, item, "evidence_ids", evidence_ids, owner, required=True)
        if isinstance(claim_id, str):
            proposal_records = records.get("10-proposal.md", {})
            compare_markdown_field(
                errors,
                proposal_records,
                claim_id,
                "Claim",
                item.get("summary"),
                "10-proposal.md",
            )
            compare_markdown_evidence(
                errors, proposal_records, claim_id, item.get("evidence_ids"), "10-proposal.md"
            )
            compare_markdown_field(
                errors,
                proposal_records,
                claim_id,
                "Mechanism",
                item.get("mechanism"),
                "10-proposal.md",
            )
            compare_markdown_field(
                errors,
                proposal_records,
                claim_id,
                "Falsifier",
                item.get("falsifier"),
                "10-proposal.md",
            )
            compare_markdown_field(
                errors,
                proposal_records,
                claim_id,
                "Assumptions/limits",
                item.get("assumptions_limits"),
                "10-proposal.md",
            )

    attacks = object_list(errors, structured, "attacks")
    attack_ids: set[str] = set()
    attack_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(attacks):
        attack_id = item.get("id")
        owner = f"attack {attack_id or index}"
        if valid_id(errors, attack_ids, "attack", attack_id, f"attacks[{index}]"):
            attack_by_id[attack_id] = item
        if item.get("claim_id") not in claim_ids:
            errors.append(f"{owner} references unknown claim: {item.get('claim_id')}")
        reference_ids(errors, item, "evidence_ids", evidence_ids, owner)
        if item.get("type") not in ATTACK_TYPES:
            errors.append(f"{owner} has invalid type")
        if item.get("severity") not in SEVERITIES:
            errors.append(f"{owner} has invalid severity")
        require_text(errors, item, "summary", owner)
        if isinstance(attack_id, str):
            critique_records = records.get("20-critique.md", {})
            compare_markdown_field(
                errors,
                critique_records,
                attack_id,
                "Target claim",
                item.get("claim_id"),
                "20-critique.md",
            )
            compare_markdown_field(
                errors, critique_records, attack_id, "Type", item.get("type"), "20-critique.md"
            )
            compare_markdown_field(
                errors,
                critique_records,
                attack_id,
                "Severity",
                item.get("severity"),
                "20-critique.md",
            )
            compare_markdown_evidence(
                errors, critique_records, attack_id, item.get("evidence_ids"), "20-critique.md"
            )
            compare_markdown_field(
                errors,
                critique_records,
                attack_id,
                "Attack",
                item.get("summary"),
                "20-critique.md",
            )

    completion = structured.get("review_completion")
    if not isinstance(completion, dict):
        errors.append("review_completion must be an object")
    else:
        if completion.get("critique_completed") is not True:
            errors.append("critique review is not completed")
        if completion.get("coverage") != "all_claims":
            errors.append("critique coverage must be all_claims")
        require_text(errors, completion, "reviewer", "review_completion")
    critique = documents.get("20-critique.md", "")
    if "Critique coverage: complete" not in critique:
        errors.append("20-critique.md lacks explicit completed critique coverage")
    if not attacks and "No attacks found" not in critique:
        errors.append("zero attacks require an explicit `No attacks found` statement")

    responses = object_list(errors, structured, "responses")
    response_ids: set[str] = set()
    response_attack_ids: list[str] = []
    for index, item in enumerate(responses):
        response_id = item.get("id")
        owner = f"response {response_id or index}"
        valid_id(errors, response_ids, "response", response_id, f"responses[{index}]")
        attack_id = item.get("attack_id")
        response_attack_ids.append(attack_id) if isinstance(attack_id, str) else None
        if attack_id not in attack_ids:
            errors.append(f"{owner} references unknown attack: {attack_id}")
        if item.get("action") not in RESPONSE_ACTIONS:
            errors.append(f"{owner} has invalid action")
        reference_ids(errors, item, "evidence_ids", evidence_ids, owner)
        require_text(errors, item, "summary", owner)
        if isinstance(response_id, str):
            rebuttal_records = records.get("25-rebuttal.md", {})
            compare_markdown_field(
                errors,
                rebuttal_records,
                response_id,
                "Attack",
                item.get("attack_id"),
                "25-rebuttal.md",
            )
            compare_markdown_field(
                errors,
                rebuttal_records,
                response_id,
                "Action",
                item.get("action"),
                "25-rebuttal.md",
            )
            compare_markdown_evidence(
                errors, rebuttal_records, response_id, item.get("evidence_ids"), "25-rebuttal.md"
            )
            compare_markdown_field(
                errors,
                rebuttal_records,
                response_id,
                "Response or exact revision",
                item.get("summary"),
                "25-rebuttal.md",
            )
    for attack_id in attack_ids:
        if response_attack_ids.count(attack_id) != 1:
            errors.append(f"attack {attack_id} requires exactly one response")

    rebuttal = documents.get("25-rebuttal.md", "")
    if not attacks and responses:
        errors.append("a zero-attack run cannot contain responses")
    if not attacks and "No responses required" not in rebuttal:
        errors.append("zero attacks require `No responses required` in 25-rebuttal.md")

    rulings = object_list(errors, structured, "rulings")
    ruling_ids: set[str] = set()
    ruling_attack_ids: list[str] = []
    for index, item in enumerate(rulings):
        ruling_id = item.get("id")
        owner = f"ruling {ruling_id or index}"
        valid_id(errors, ruling_ids, "ruling", ruling_id, f"rulings[{index}]")
        attack_id = item.get("attack_id")
        ruling_attack_ids.append(attack_id) if isinstance(attack_id, str) else None
        if attack_id not in attack_ids:
            errors.append(f"{owner} references unknown attack: {attack_id}")
        if item.get("status") not in RULING_STATUSES:
            errors.append(f"{owner} has invalid status")
        reference_ids(errors, item, "evidence_ids", evidence_ids, owner)
        require_text(errors, item, "reason", owner)
        if isinstance(ruling_id, str):
            verdict_records = records.get("30-verdict.md", {})
            compare_markdown_field(
                errors,
                verdict_records,
                ruling_id,
                "Attack",
                item.get("attack_id"),
                "30-verdict.md",
            )
            compare_markdown_field(
                errors,
                verdict_records,
                ruling_id,
                "Status",
                item.get("status"),
                "30-verdict.md",
            )
            compare_markdown_evidence(
                errors, verdict_records, ruling_id, item.get("evidence_ids"), "30-verdict.md"
            )
            compare_markdown_field(
                errors,
                verdict_records,
                ruling_id,
                "Reason and evidence",
                item.get("reason"),
                "30-verdict.md",
            )
        attack = attack_by_id.get(attack_id, {})
        if attack.get("severity") in {"high", "critical"} and item.get("status") in BLOCKING_RULINGS:
            errors.append(f"blocking ruling remains for attack {attack_id}")
    for attack_id in attack_ids:
        if ruling_attack_ids.count(attack_id) != 1:
            errors.append(f"attack {attack_id} requires exactly one ruling")
    if not attacks and rulings:
        errors.append("a zero-attack run cannot contain rulings")
    if not attacks and "No rulings required" not in documents.get("30-verdict.md", ""):
        errors.append("zero attacks require `No rulings required` in 30-verdict.md")

    deterministic = object_list(errors, structured, "deterministic_checks", required=True)
    check_ids: set[str] = set()
    check_evidence_ids: list[list[str]] = []
    for index, item in enumerate(deterministic):
        check_id = item.get("id")
        owner = f"deterministic check {check_id or index}"
        valid_id(errors, check_ids, "check", check_id, f"deterministic_checks[{index}]")
        require_text(errors, item, "method", owner)
        require_text(errors, item, "result", owner)
        reference_ids(errors, item, "evidence_ids", evidence_ids, owner, required=True)
        values = item.get("evidence_ids")
        if isinstance(values, list) and all(isinstance(value, str) for value in values):
            check_evidence_ids.append(values)
        if item.get("status") != "passed":
            errors.append(f"{owner} did not pass")

    decision = structured.get("decision")
    if not isinstance(decision, dict):
        errors.append("decision must be an object")
    else:
        decision_id = decision.get("id")
        valid_id(errors, set(), "decision", decision_id, "decision")
        require_text(errors, decision, "summary", "decision")
        status = decision.get("status")
        if status not in TERMINAL_DECISIONS:
            errors.append(f"decision is not terminal: {status!r}")
        if isinstance(decision_id, str):
            compare_markdown_field(
                errors,
                records.get("30-verdict.md", {}),
                decision_id,
                "Decision status",
                status,
                "30-verdict.md",
            )
            compare_markdown_field(
                errors,
                records.get("30-verdict.md", {}),
                decision_id,
                "Rationale",
                decision.get("summary"),
                "30-verdict.md",
            )
        final_severity = run.get("severity")
        if status == "accept" and final_severity in {"high", "critical"}:
            has_operational_check = any(
                operational_evidence_ids.intersection(values) for values in check_evidence_ids
            )
            if not has_operational_check:
                errors.append(
                    "high/critical accept requires a deterministic check tied to independent_operational evidence"
                )

    signoff = structured.get("human_signoff")
    if not isinstance(signoff, dict):
        errors.append("human_signoff must be an object")
    else:
        required = signoff.get("required")
        status = signoff.get("status")
        if not isinstance(required, bool):
            errors.append("human_signoff.required must be a boolean")
        if run.get("severity") in {"high", "critical"} and required is not True:
            errors.append("high/critical run must set human_signoff.required to true")
        if required is True and status != "approved":
            errors.append("required human approval is missing")
        if status == "approved":
            require_text(errors, signoff, "reviewer", "approved human signoff")
    return errors


def validate_run(run_dir: Path, quiet: bool = False) -> list[str]:
    manifest = read_json(run_dir / "manifest.json")
    errors = gate_errors(run_dir, manifest)
    if not quiet:
        print("validation: PASS" if not errors else "validation: FAIL")
        for error in errors:
            print(f"- {error}")
    return errors


def write_complete_run(
    run_dir: Path,
    *,
    severity: str = "low",
    attacks: bool = True,
    check_status: str = "passed",
    decision_status: str = "accept",
    markdown_decision: str | None = None,
    attack_severity: str = "low",
    ruling_status: str = "rejected",
    approve: bool = True,
) -> None:
    question, revision = "Should we accept the fixture?", "abc123"
    init_run(run_dir, question, severity, revision)
    manifest = read_json(run_dir / "manifest.json")
    created_at, deadline_at = manifest["created_at"], manifest["deadline_at"]
    (run_dir / "00-context.md").write_text(
        f"""# E0 Frozen Context

## Decision metadata

- Question: {question}
- Severity: {severity}
- Snapshot revision/hash: {revision}
- Rebuttal rounds: 1
- Time budget: 30 minutes
- Token budget: 20000
- Created at: {created_at}
- Deadline at: {deadline_at}

## Hard constraints

- Preserve data integrity.

## Evidence register

### E-001

- Source: fixture
- Revision/hash: abc123
- Reproduction: read fixture
- Verification state: verified
- Verification scope: independent_operational
- Instruction scan: passed

## Known facts, hypotheses, and conflicts

- Fixture result is reproducible; no conflicts found.
""",
        encoding="utf-8",
    )
    (run_dir / "10-proposal.md").write_text(
        """# A Proposal

## Position

Accept the fixture only when its deterministic check passes.

## Claims

### C-001

- Claim: The fixture is safe under the stated constraint.
- Evidence: E-001
- Mechanism: The deterministic assertion checks the constraint.
- Assumptions/limits: Applies only to revision abc123.
- Falsifier: A failed deterministic assertion.
""",
        encoding="utf-8",
    )
    critique_body = (
        f"""## Attacks

### ATK-001

- Target claim: C-001
- Type: risk
- Severity: {attack_severity}
- Evidence: E-001
- Attack: The fixture could drift after the recorded revision.
- Minimal falsification test: Re-run the assertion on abc123.
"""
        if attacks
        else "## Attacks\n\nNo attacks found.\n"
    )
    (run_dir / "20-critique.md").write_text(
        "# B Critique\n\n## Critique coverage\n\n- Critique coverage: complete\n- Reviewer: fixture-critic\n\n"
        + critique_body,
        encoding="utf-8",
    )
    response_body = (
        """## Responses

### RSP-001

- Attack: ATK-001
- Action: rebut
- Evidence: E-001
- Response or exact revision: The sealed revision and rerun address drift for this decision.
"""
        if attacks
        else "## Responses\n\nNo responses required.\n"
    )
    (run_dir / "25-rebuttal.md").write_text(
        "# A2 Rebuttal or Revision\n\n"
        + response_body
        + "\n## Consolidated effective proposal\n\nAccept only revision abc123 after the assertion passes.\n",
        encoding="utf-8",
    )
    ruling_body = (
        f"""## Rulings

### V-001

- Attack: ATK-001
- Status: {ruling_status}
- Evidence: E-001
- Reason and evidence: E-001 plus the deterministic rerun.
"""
        if attacks
        else "## Rulings\n\nNo rulings required.\n"
    )
    (run_dir / "30-verdict.md").write_text(
        "# J Verdict\n\n"
        + ruling_body
        + f"\n## Run decision\n\n### D-001\n\n- Decision status: {markdown_decision or decision_status}\n"
        + "- Rationale: The structured record and deterministic check support the decision.\n",
        encoding="utf-8",
    )
    data = initial_checks(question, severity, revision, 30, 20_000, created_at, deadline_at)
    data["evidence"] = [
        {
            "id": "E-001",
            "source": "fixture",
            "revision_or_hash": "abc123",
            "reproduction": "read fixture",
            "verification_state": "verified",
            "verification_scope": "independent_operational",
            "instruction_scan": "passed",
        }
    ]
    data["claims"] = [
        {
            "id": "C-001",
            "evidence_ids": ["E-001"],
            "summary": "The fixture is safe under the stated constraint.",
            "mechanism": "The deterministic assertion checks the constraint.",
            "assumptions_limits": "Applies only to revision abc123.",
            "falsifier": "A failed deterministic assertion.",
        }
    ]
    data["attacks"] = []
    data["responses"] = []
    data["rulings"] = []
    if attacks:
        data["attacks"] = [
            {
                "id": "ATK-001",
                "claim_id": "C-001",
                "evidence_ids": ["E-001"],
                "type": "risk",
                "severity": attack_severity,
                "summary": "The fixture could drift after the recorded revision.",
            }
        ]
        data["responses"] = [
            {
                "id": "RSP-001",
                "attack_id": "ATK-001",
                "action": "rebut",
                "evidence_ids": ["E-001"],
                "summary": "The sealed revision and rerun address drift for this decision.",
            }
        ]
        data["rulings"] = [
            {
                "id": "V-001",
                "attack_id": "ATK-001",
                "status": ruling_status,
                "evidence_ids": ["E-001"],
                "reason": "E-001 plus the deterministic rerun.",
            }
        ]
    data["review_completion"] = {
        "critique_completed": True,
        "coverage": "all_claims",
        "reviewer": "fixture-critic",
    }
    data["deterministic_checks"] = [
        {
            "id": "CHK-001",
            "method": "fixture assertion",
            "status": check_status,
            "evidence_ids": ["E-001"],
            "result": "fixture output: ok",
        }
    ]
    data["decision"] = {
        "id": "D-001",
        "status": decision_status,
        "summary": "The structured record and deterministic check support the decision.",
    }
    if severity in {"high", "critical"}:
        data["human_signoff"] = {
            "required": True,
            "status": "approved" if approve else "pending",
            "reviewer": "fixture-human" if approve else "",
            "note": "fixture",
        }
    atomic_json(run_dir / "40-checks.json", data)


def seal_all(run_dir: Path) -> None:
    for stage in STAGES:
        seal_stage(run_dir, stage)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise BlackboardError(f"self-test failed: {message}")


def expect_error(errors: list[str], fragment: str, label: str) -> None:
    expect(any(fragment in error for error in errors), f"{label}: missing `{fragment}` in {errors}")
