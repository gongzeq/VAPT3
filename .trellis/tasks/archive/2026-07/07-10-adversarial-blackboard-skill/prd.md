# Create Adversarial Blackboard Review Skill

## Goal

Create a project-local Codex skill that turns difficult, high-impact decisions into a bounded, evidence-driven adversarial review. The skill must close the missing evidence, rebuttal, abstention, artifact-isolation, deterministic-check, and human-signoff loops identified in the design review.

## Requirements

- Create the skill at `.agents/skills/run-adversarial-blackboard/` so it is versioned with the repository and available through the shared skill layer.
- Trigger for high-impact architecture, security, privacy, compatibility, data-integrity, or repeatedly stuck decisions where cheap deterministic checks cannot settle the question.
- Do not use the protocol for routine, low-risk, reversible work or when a direct experiment is cheaper.
- Implement the bounded flow `E0 evidence freeze -> A proposal -> B critique -> A2 rebuttal/revision -> J verdict -> deterministic checks -> human signoff`.
- Treat E0 as coordinator-owned evidence preparation, not an ungoverned Agent opinion. Require source, revision/hash, reproduction method, and verification state.
- Give proposal claims, attacks, responses, and verdicts stable identifiers and explicit cross-references.
- Classify attacks as `disproof`, `missing_evidence`, or `risk`; allow B to propose a minimal falsification test but not a replacement design.
- Let A2 respond once to existing attacks using only rebut, accept-and-revise, downgrade-to-hypothesis, or withdraw.
- Let J sustain, reject, mark unresolved/out-of-scope/resolved-by-revision, abstain, or return the run. J must not silently invent new attacks or approve its own new design.
- Block automatic acceptance on unresolved high-severity attacks, failed deterministic checks, unverifiable evidence, or missing required human signoff.
- Stop when no new verifiable evidence appears, evidence versions conflict, the round/time/token budget is exhausted, or a high-risk decision lacks a deterministic oracle.
- Store stages as separate artifacts with coordinator-owned writes and SHA-256 seals; a shared Markdown section convention alone is insufficient.
- Include one dependency-free Python CLI to initialize a run, seal ordered stages, validate hashes and final gates, and run a self-test.
- Include `agents/openai.yaml` with matching UI metadata.
- Keep the skill concise and use no new dependency.

## Acceptance Criteria

- [x] `SKILL.md` has only `name` and `description` in frontmatter, uses imperative instructions, and stays below 500 lines.
- [x] The skill clearly defines trigger, non-trigger, roles, evidence rules, bounded rounds, statuses, stop conditions, and final gates.
- [x] The initializer creates `manifest.json`, `00-context.md`, `10-proposal.md`, `20-critique.md`, `25-rebuttal.md`, `30-verdict.md`, and `40-checks.json`.
- [x] Stage sealing is ordered and records SHA-256 hashes; later mutation of a sealed artifact makes validation fail.
- [x] Validation fails for failed/not-run deterministic checks, unresolved high-severity issues, incomplete stage seals, or missing high/critical human approval.
- [x] Validation succeeds for a complete low-risk run with passing checks and a terminal verdict.
- [x] The script's self-test passes in normal and optimized Python modes.
- [x] `skill-creator/scripts/quick_validate.py` passes for the new skill.
- [x] Independent forward-testing applied the skill to a production-migration decision without design-context leakage.

## Definition of Done

- Skill files are implemented using repository conventions.
- Deterministic script checks and skill validation pass.
- Independent forward-test findings are addressed or documented.
- Trellis quality verification is complete.

## Technical Approach

Use a compact `SKILL.md` for routing and protocol rules plus a single standard-library `scripts/blackboard.py` CLI. The CLI owns deterministic artifact creation, ordered sealing, mutation detection, and final gate validation. Markdown remains the human-readable reasoning surface; `manifest.json` and `40-checks.json` carry machine-verifiable state.

## Decision (ADR-lite)

**Context**: A single shared Markdown file provides role cues but not evidence ownership, hard write separation, rebuttal closure, or deterministic enforcement.

**Decision**: Use a project-local shared skill, separate stage artifacts, a coordinator-owned evidence phase, one bounded A2 response, explicit unresolved states, and a dependency-free verifier.

**Consequences**: The protocol costs several serial model calls and is therefore restricted to high-value cases. SHA-256 seals provide drift detection and auditability, not protection from a malicious actor with full repository write access.

## Out of Scope

- Integrating this review protocol into the runtime `secbot` skill contract or `BlackboardRegistry` API.
- Automatically invoking models or spawning roles from the Python script.
- Treating same-model personas as statistically independent reviewers.
- Providing cryptographic non-repudiation or a security boundary against a malicious coordinator.
- Making the protocol mandatory for every task.

## Technical Notes

- Skill creation rules: `/Users/shan/.codex/skills/.system/skill-creator/SKILL.md`.
- Local skill customization rules: `.agents/skills/trellis-meta/references/customize-local/change-skills-or-commands.md`.
- Relevant quality principles: `.trellis/spec/backend/quality-guidelines.md`.
- `.trellis/spec/backend/skill-contract.md` describes runtime `secbot/skills/` and is explicitly not the target contract for this `.agents/skills/` capability.
- No `.trellis/spec/` update is needed: this is a project-local AI workflow whose complete executable contract lives in the skill, and duplicating it in backend runtime specs would create two sources of truth.

## Verification

- Ruff: passed for all skill Python files.
- Python compilation: passed with a temporary bytecode cache.
- CLI self-test: passed under normal Python and `python3 -O`.
- Skill quick validation: passed.
- Independent Trellis review: no findings after regression checks for evidence/claim conflicts, signoff, operational evidence, prompt-injection status, ordered seals, deadlines, and timestamp backdating.
