# PRD: Recoverable Expert Agent Interruption Handling

## Problem Statement

Recent VAPT sessions show a recurring failure mode: an Expert Agent reaches its iteration or context budget after running useful Skills, but the runtime treats the attempt inconsistently. Some paths surface the attempt as completed, some surface it as incomplete, and structured Skill findings may remain only in tool results instead of becoming Vulnerabilities or Vulnerability Candidates.

From the user's perspective this causes three concrete problems: token usage grows through repeated no-delta polling, report-html contains fewer vulnerabilities than the scan actually found, and the system cannot reliably decide whether to continue, replan, or ask the user after an interrupted Expert Agent.

## Solution

Introduce a single runtime contract for **Recoverable Execution Interruption** across the legacy Agent Turn Runtime and the future Phase Graph Scheduler path.

When an Expert Agent exhausts `max_iterations` or `context_exhausted`, the attempt must enter bounded wind-down, persist any structured Skill Findings through the host execution layer, produce a tool-free structured **Handoff Summary**, and report outward status as `interrupted`. The Phase Graph Scheduler decides whether to redispatch the same PlanNode as a new Attempt, trigger replan, request user input, or allow an explicitly partial report.

The user's expected outcome is that confirmed findings are not lost, interrupted work is not mislabeled as completed, and automatic continuation is bounded by progress and budget rather than becoming another hidden loop.

## User Stories

1. As a security engineer, I want an Expert Agent that reaches its iteration limit to summarize what happened, so that useful progress is not lost.
2. As a security engineer, I want an interrupted Expert Agent to be shown as interrupted rather than completed, so that I can trust scan state.
3. As a security engineer, I want confirmed Skill Findings to be persisted as Vulnerabilities even if the Expert Agent has no remaining model turns, so that reports include everything already found.
4. As a security engineer, I want unverified scanner hits to become Vulnerability Candidates rather than confirmed findings, so that reports do not overstate risk.
5. As a security engineer, I want repeated `read_assets` calls with no new assets to stop qualifying as progress, so that scans do not burn tokens in a polling loop.
6. As a security engineer, I want interrupted work to continue only when there is real progress and a clear continuation point, so that the system does not blindly retry a dead end.
7. As a security engineer, I want an interrupted vulnerability scan to be redispatched at most once by default, so that token usage stays bounded.
8. As a security engineer, I want the second repeated interruption to trigger replan or user input, so that the system changes strategy instead of repeating the same path.
9. As a security engineer, I want report generation to wait for unresolved required scan work by default, so that a normal report means the scan is complete.
10. As a security engineer, I want to explicitly request a partial report when I only need current results, so that I can still export findings during unresolved work.
11. As a security engineer, I want partial reports to mark incomplete coverage, so that the report is not mistaken for complete assessment output.
12. As a platform operator, I want `max_iterations` and `context_exhausted` to share the same interruption contract, so that status, reporting, and redispatch behavior are consistent.
13. As a platform operator, I want `context_exhausted` to prefer compaction or State View rematerialization before redispatch, so that continuation does not immediately overflow context again.
14. As a platform operator, I want the Handoff Summary to be structured, so that the scheduler can make deterministic continuation decisions.
15. As a platform operator, I want Handoff Summary generation to have a deterministic fallback, so that model summary failures do not turn recoverable interruptions into hard failures.
16. As a platform operator, I want Skill Findings returned during wind-down to be persisted by host code, so that evidence arriving at the boundary is not lost.
17. As a platform operator, I want PlanNode identity to remain stable across redispatch attempts, so that audit, dedupe, budgets, and report metadata remain coherent.
18. As a platform operator, I want PlanNode Budget to be cumulative across attempts, so that redispatch does not reset the safety limit.
19. As a platform developer, I want status aggregation APIs and events to expose interrupted attempts consistently, so that UI and automation do not infer false completion.
20. As a platform developer, I want the legacy reactive path to honor the same contract as the Phase Graph Scheduler, so that migration does not leave the current product broken.
21. As a platform developer, I want Skill execution to bridge known finding schemas into structured state, so that Expert Agents do not need to manually restate every scanner result.
22. As a platform developer, I want no-delta reads and no-result scans to be tracked by host-observed Progress Delta, so that continuation decisions are testable.
23. As a platform developer, I want dependency handling to treat interrupted upstream PlanNodes as unresolved, so that downstream report nodes do not silently run too early.
24. As a platform developer, I want telemetry to show completed actions, persisted results, blockers, and recommended next action, so that debugging recent sessions is straightforward.
25. As an orchestrator, I want to use `wait_subagent` to wait for a specific Expert Agent attempt, so that I do not burn turns polling `read_assets` while work is still running.
26. As an orchestrator, I want to use `check_subagents` to inspect child attempt status and summaries, so that I can make dispatch decisions from subagent state instead of inferring it from asset-feed deltas.
27. As a security engineer, I want `asset_push(kind=vuln)` to be host-owned after a vulnerability is discovered, so that vulnerabilities found by Skills are not lost when the model reaches an interruption boundary.
28. As a platform operator, I want report-html to merge structured vulnerability state with session artifacts, so that the generated report is not smaller than the scan evidence already persisted.

## Implementation Decisions

- **Recoverable Execution Interruption** is the canonical outcome for `max_iterations` and `context_exhausted`. It is not success and not a hard error.
- **Interrupted Attempt Status** is the outward status for recoverable budget exhaustion. Legacy internal labels may exist during migration, but UI/API/event surfaces must not map this state to completed.
- **Attempt Wind-Down** runs before summarization. It starts no new Skills, waits for already-running Skills to finish or time out, and captures their terminal results.
- **Handoff Summary** is a tool-free structured summary. It includes progress, completed actions, persisted result references, unfinished actions, continuation point, blockers, recommended next action, user-input need, and confidence.
- **Handoff Summary** generation has deterministic fallback. Fallback preserves interrupted status, sets low confidence, and recommends replan.
- **Skill Finding** persistence is host-owned. Verified or confirmed Skill Findings become Vulnerabilities; unverified or low-confidence Skill Findings become Vulnerability Candidates.
- The host execution layer must bridge Skill Findings even when they arrive during Attempt Wind-Down.
- Expert Agents may still explain and verify, but they are not the only path for structured Skill Findings to reach report data sources.
- `asset_push(kind=vuln)` is a persistence operation for already discovered vulnerability evidence. Discovery may come from Skill Findings, explicit Expert Agent validation, or other host-recognized vulnerability signals.
- `wait_subagent` is the scheduler/orchestrator primitive for waiting on a known child attempt to reach progress, interruption, completion, or timeout. It replaces repeated asset-feed polling when the orchestrator is waiting for a subagent.
- `check_subagents` is the scheduler/orchestrator primitive for listing child attempt state, summaries, blockers, and result references. It is the correct way to inspect active or interrupted work before redispatch or report generation.
- `read_assets` returning "No new assets" is a no-delta observation. Consecutive no-delta reads must not count as Progress Delta and must not justify continued polling.
- Redispatch preserves PlanNode identity and increments PlanNode Attempt. Redispatch is not a new task or a new scan.
- PlanNode Budget is cumulative across all attempts. A redispatched Attempt may have a per-attempt cap but consumes only remaining PlanNode Budget.
- Automatic redispatch is allowed at most once by default.
- Automatic redispatch requires a host-observed Progress Delta, an explicit continuation point, and no user-decision blocker.
- Missing authorization, missing target scope, high-risk confirmation, or user-owned missing information routes to user input instead of automatic redispatch.
- Repeated same-class blockers or no Progress Delta route to replan instead of automatic redispatch.
- `context_exhausted` uses the same interruption contract but defaults to compaction or State View rematerialization before continuation.
- Downstream dependencies are not satisfied by interrupted upstream work. The scheduler may continue only after upstream completion, explicit skip/dismissal, or an explicit partial-report decision.
- Report generation defaults to waiting for recovery. A Partial Report Artifact is generated only when the user asks for current results or the scheduler has marked remaining work skipped, dismissed, or blocked.
- Partial Report Artifacts include already persisted Vulnerabilities and Candidates while carrying incomplete coverage metadata.
- report-html must read the report data sources, not re-run vulnerability discovery. It may load its own Skill instructions as implementation context, but report completeness comes from merged VulnerabilityStore, AssetFeed/session pushes, and persisted session artifacts.
- The legacy reactive Agent Turn Runtime must implement the same semantics during the Phase Graph Scheduler migration.
- Status rollups, runtime snapshots, WebSocket events, and agent status APIs must use the same terminal-state mapping.

## Testing Decisions

- Test external behavior, not implementation details: assert state transitions, persisted findings, report inputs, and redispatch decisions rather than private helper call order.
- Add runner-level tests for `max_iterations` and `context_exhausted` producing structured Handoff Summary or deterministic fallback.
- Add Expert Agent lifecycle tests for interrupted status, wind-down behavior, and no accidental mapping to completed.
- Add Skill execution tests where a Skill returns confirmed findings but the Expert Agent has no remaining turns; the finding must still reach structured vulnerability state.
- Add Skill execution tests where scanner hits are unverified; they must become Vulnerability Candidates and not confirmed report findings.
- Add no-delta progress tests for repeated asset reads and repeated scans with no new result references; these must not trigger automatic redispatch.
- Add subagent control tests for `wait_subagent` and `check_subagents`, proving orchestrators can wait for and inspect subagent attempts without polling `read_assets`.
- Add host persistence tests proving `asset_push(kind=vuln)` or equivalent vulnerability persistence occurs after Skill Findings are observed, including interruption-boundary cases.
- Add scheduler policy tests for redispatch, replan, and ask-user branching based on Progress Delta, continuation point, blockers, attempt count, and budget.
- Add budget tests proving redispatch consumes cumulative PlanNode Budget rather than resetting limits.
- Add status API and event tests proving interrupted attempts are not exposed as completed.
- Add report pipeline tests proving unresolved interrupted dependencies block normal reports, while explicit partial reports include persisted findings and incomplete metadata.
- Prior art exists in the current interruption-summary tests, Expert Agent lifecycle tests, subagent tool tests, and report pipeline tests. Extend those patterns rather than creating a separate bespoke harness.

## Out of Scope

- Full Phase Graph Scheduler implementation if this PRD is delivered as a legacy-path compatibility fix first.
- Changing the user-facing report design beyond adding incomplete coverage metadata for Partial Report Artifacts.
- Making all scanner hits confirmed findings by default.
- Unlimited automatic retries or automatic continuation without Progress Delta.
- Replacing CMDB, AssetFeed, Blackboard, or VulnerabilityStore storage models.
- Reworking unrelated frontend layout or scan dashboard design.
- Adding external orchestration frameworks.

## Further Notes

- This PRD sharpens and supersedes the earlier broad "agent iteration cap summary" behavior for Expert Agent interruption semantics.
- The current runtime already has partial pieces: interrupt summaries, incomplete subagent announce behavior, and wait/check subagent tools. The missing contract is consistent status semantics, host-owned Skill Finding persistence, bounded redispatch, and report dependency behavior.
- The domain glossary has been updated with the relevant terms: Recoverable Execution Interruption, Handoff Summary, Attempt Wind-Down, Interrupted Attempt Status, PlanNode Attempt, PlanNode Budget, Skill Finding, Progress Delta, and Partial Report Artifact.
- The core risk is accidentally turning the safety limit into a hidden continuation loop. The PRD intentionally requires cumulative budget, one automatic redispatch by default, and host-observed Progress Delta.
