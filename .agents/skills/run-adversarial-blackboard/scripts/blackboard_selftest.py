"""Regression checks for the adversarial blackboard helper."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from blackboard_core import (
    STAGES,
    BlackboardError,
    atomic_json,
    expect,
    expect_error,
    init_run,
    read_json,
    seal_all,
    seal_stage,
    validate_run,
    write_complete_run,
)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)

        good = root / "good"
        write_complete_run(good)
        seal_all(good)
        expect(not validate_run(good, quiet=True), "complete low-risk run should pass")
        (good / "10-proposal.md").write_text("mutated\n", encoding="utf-8")
        expect_error(validate_run(good, quiet=True), "mutated", "sealed mutation")
        template = root / "template"
        init_run(template, "Is the template complete?", "low", "abc123")
        seal_all(template)
        expect_error(validate_run(template, quiet=True), "TODO marker", "template stage")
        incomplete = root / "incomplete"
        init_run(incomplete, "Is the run complete?", "low", "abc123")
        expect_error(validate_run(incomplete, quiet=True), "incomplete stage seals", "incomplete seals")
        blank = root / "blank"
        write_complete_run(blank)
        (blank / "10-proposal.md").write_text("\n", encoding="utf-8")
        seal_all(blank)
        expect_error(validate_run(blank, quiet=True), "empty or incomplete", "blank stage")
        disagreement = root / "disagreement"
        write_complete_run(disagreement, markdown_decision="reject")
        seal_all(disagreement)
        expect_error(
            validate_run(disagreement, quiet=True), "Decision status disagrees", "decision mismatch"
        )
        ruling_conflict = root / "ruling-conflict"
        write_complete_run(ruling_conflict)
        verdict_path = ruling_conflict / "30-verdict.md"
        verdict_path.write_text(
            verdict_path.read_text(encoding="utf-8").replace(
                "- Status: rejected", "- Status: sustained"
            ),
            encoding="utf-8",
        )
        seal_all(ruling_conflict)
        expect_error(
            validate_run(ruling_conflict, quiet=True), "Status disagrees", "ruling mismatch"
        )
        evidence_conflict = root / "evidence-conflict"
        write_complete_run(evidence_conflict)
        context_path = evidence_conflict / "00-context.md"
        context_path.write_text(
            context_path.read_text(encoding="utf-8").replace(
                "- Revision/hash: abc123", "- Revision/hash: wrong-revision"
            ),
            encoding="utf-8",
        )
        seal_all(evidence_conflict)
        expect_error(
            validate_run(evidence_conflict, quiet=True),
            "Revision/hash disagrees",
            "E0 revision mismatch",
        )
        claim_conflict = root / "claim-conflict"
        write_complete_run(claim_conflict)
        proposal_path = claim_conflict / "10-proposal.md"
        proposal_path.write_text(
            proposal_path.read_text(encoding="utf-8").replace(
                "- Claim: The fixture is safe under the stated constraint.",
                "- Claim: The fixture is always safe.",
            ),
            encoding="utf-8",
        )
        seal_all(claim_conflict)
        expect_error(
            validate_run(claim_conflict, quiet=True), "Claim disagrees", "claim text mismatch"
        )
        incomplete_proposal = root / "incomplete-proposal"
        write_complete_run(incomplete_proposal)
        proposal_path = incomplete_proposal / "10-proposal.md"
        proposal_path.write_text(
            proposal_path.read_text(encoding="utf-8").replace(
                "- Falsifier: A failed deterministic assertion.\n", ""
            ),
            encoding="utf-8",
        )
        seal_all(incomplete_proposal)
        expect_error(
            validate_run(incomplete_proposal, quiet=True), "lacks Falsifier", "incomplete proposal"
        )
        bad_ref = root / "bad-ref"
        write_complete_run(bad_ref)
        data = read_json(bad_ref / "40-checks.json")
        data["responses"][0]["attack_id"] = "ATK-999"
        atomic_json(bad_ref / "40-checks.json", data)
        seal_all(bad_ref)
        expect_error(validate_run(bad_ref, quiet=True), "unknown attack", "cross-reference")
        no_attacks = root / "no-attacks"
        write_complete_run(no_attacks, attacks=False)
        seal_all(no_attacks)
        expect(not validate_run(no_attacks, quiet=True), "explicit zero-attack run should pass")
        not_run = root / "not-run"
        write_complete_run(not_run, check_status="not_run")
        seal_all(not_run)
        expect_error(validate_run(not_run, quiet=True), "did not pass", "not-run check")

        empty_check_evidence = root / "empty-check-evidence"
        write_complete_run(empty_check_evidence)
        data = read_json(empty_check_evidence / "40-checks.json")
        data["deterministic_checks"][0]["evidence_ids"] = []
        atomic_json(empty_check_evidence / "40-checks.json", data)
        seal_all(empty_check_evidence)
        expect_error(
            validate_run(empty_check_evidence, quiet=True),
            "requires at least one evidence_ids entry",
            "empty deterministic evidence",
        )

        medium_signoff = root / "medium-signoff"
        write_complete_run(medium_signoff, severity="medium")
        data = read_json(medium_signoff / "40-checks.json")
        data["human_signoff"] = {
            "required": True,
            "status": "pending",
            "reviewer": "",
            "note": "fixture",
        }
        atomic_json(medium_signoff / "40-checks.json", data)
        seal_all(medium_signoff)
        medium_errors = validate_run(medium_signoff, quiet=True)
        expect(
            medium_errors.count("required human approval is missing") == 1,
            f"medium required signoff should emit one approval error: {medium_errors}",
        )

        high_without_operational = root / "high-without-operational"
        write_complete_run(high_without_operational, severity="high")
        context_path = high_without_operational / "00-context.md"
        context_path.write_text(
            context_path.read_text(encoding="utf-8").replace(
                "Verification scope: independent_operational", "Verification scope: record_presence"
            ),
            encoding="utf-8",
        )
        data = read_json(high_without_operational / "40-checks.json")
        data["evidence"][0]["verification_scope"] = "record_presence"
        atomic_json(high_without_operational / "40-checks.json", data)
        seal_all(high_without_operational)
        expect_error(
            validate_run(high_without_operational, quiet=True),
            "accept requires a deterministic check tied to independent_operational evidence",
            "high accept without operational evidence",
        )

        high_reject = root / "high-reject"
        write_complete_run(high_reject, severity="high", decision_status="reject")
        context_path = high_reject / "00-context.md"
        context_path.write_text(
            context_path.read_text(encoding="utf-8").replace(
                "Verification scope: independent_operational", "Verification scope: record_presence"
            ),
            encoding="utf-8",
        )
        data = read_json(high_reject / "40-checks.json")
        data["evidence"][0]["verification_scope"] = "record_presence"
        atomic_json(high_reject / "40-checks.json", data)
        seal_all(high_reject)
        expect(
            not validate_run(high_reject, quiet=True),
            "high reject should allow absence of independent_operational evidence",
        )

        missing_scan = root / "missing-scan"
        write_complete_run(missing_scan)
        data = read_json(missing_scan / "40-checks.json")
        del data["evidence"][0]["instruction_scan"]
        atomic_json(missing_scan / "40-checks.json", data)
        seal_all(missing_scan)
        expect_error(
            validate_run(missing_scan, quiet=True), "invalid instruction_scan", "instruction scan"
        )

        blocked = root / "blocked"
        write_complete_run(
            blocked,
            severity="high",
            attack_severity="high",
            ruling_status="unresolved",
            approve=False,
        )
        seal_all(blocked)
        blocked_errors = validate_run(blocked, quiet=True)
        expect_error(blocked_errors, "blocking ruling", "unresolved high-severity attack")
        expect_error(blocked_errors, "required human approval is missing", "missing high-risk signoff")

        tampered = root / "severity-tamper"
        write_complete_run(tampered, severity="high", approve=False)
        seal_all(tampered)
        manifest = read_json(tampered / "manifest.json")
        manifest["severity"] = "low"
        atomic_json(tampered / "manifest.json", manifest)
        tamper_errors = validate_run(tampered, quiet=True)
        expect_error(tamper_errors, "metadata disagree on severity", "manifest severity tamper")
        expect_error(tamper_errors, "required human approval is missing", "sealed severity signoff")

        elapsed = root / "elapsed"
        write_complete_run(elapsed)
        seal_all(elapsed)
        manifest = read_json(elapsed / "manifest.json")
        structured = read_json(elapsed / "40-checks.json")
        original_deadline = datetime.fromisoformat(structured["run"]["deadline_at"])
        final_seal = original_deadline + timedelta(minutes=1)
        manifest["seals"][-1]["sealed_at"] = final_seal.isoformat()
        manifest["created_at"] = (final_seal - timedelta(minutes=29)).isoformat()
        manifest["deadline_at"] = (final_seal + timedelta(minutes=1)).isoformat()
        atomic_json(elapsed / "manifest.json", manifest)
        elapsed_errors = validate_run(elapsed, quiet=True)
        expect_error(elapsed_errors, "metadata disagree on created_at", "created_at binding")
        expect_error(elapsed_errors, "metadata disagree on deadline_at", "deadline_at binding")
        expect_error(elapsed_errors, "exceeded its sealed deadline", "elapsed time budget")

        late = root / "late-final-seal"
        write_complete_run(late)
        manifest = read_json(late / "manifest.json")
        original_created = datetime.fromisoformat(manifest["created_at"])
        original_deadline = datetime.fromisoformat(manifest["deadline_at"])
        past_created = (original_created - timedelta(minutes=31)).isoformat()
        past_deadline = (original_deadline - timedelta(minutes=31)).isoformat()
        manifest["created_at"], manifest["deadline_at"] = past_created, past_deadline
        atomic_json(late / "manifest.json", manifest)
        structured = read_json(late / "40-checks.json")
        structured["run"]["created_at"] = past_created
        structured["run"]["deadline_at"] = past_deadline
        atomic_json(late / "40-checks.json", structured)
        context = late / "00-context.md"
        context.write_text(
            context.read_text(encoding="utf-8")
            .replace(original_created.isoformat(), past_created)
            .replace(original_deadline.isoformat(), past_deadline),
            encoding="utf-8",
        )
        for stage in STAGES[:-1]:
            seal_stage(late, stage)
        try:
            seal_stage(late, STAGES[-1])
            expect(False, "late final seal should be rejected")
        except BlackboardError as exc:
            expect("after the run deadline" in str(exc), f"unexpected late-seal error: {exc}")

        backdated = root / "backdated-final-seal"
        write_complete_run(backdated)
        seal_all(backdated)
        structured = read_json(backdated / "40-checks.json")
        manifest = read_json(backdated / "manifest.json")
        finalized_at = datetime.fromisoformat(structured["run"]["finalized_at"])
        manifest["seals"][-1]["sealed_at"] = (finalized_at - timedelta(seconds=1)).isoformat()
        atomic_json(backdated / "manifest.json", manifest)
        expect_error(
            validate_run(backdated, quiet=True),
            "finalized_at does not match",
            "post-seal sealed_at backdating",
        )

    print("self-test: PASS")
