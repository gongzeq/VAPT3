# secbot Context

secbot is a conversational VAPT system where a surface sends user work to an Orchestrator, the Orchestrator delegates to Expert Agents, and Expert Agents invoke Skills that may update the CMDB or produce report artifacts.

## Language

**Surface**:
The user-facing entry point that transports messages, events, and approvals between a user and the Agent Turn Runtime.
_Avoid_: client, channel, UI layer

**Agent Turn Runtime**:
The runtime that executes one conversational turn, including streaming text, tool progress, checkpointing, cancellation, and final turn completion.
_Avoid_: main loop, agent loop internals

**Session**:
A conversation container for a user's ongoing VAPT work.
_Avoid_: chat id, browser tab

**Scan**:
A VAPT task started within a Session.
_Avoid_: chat, turn

**Orchestrator**:
Formerly the top-level reactive agent; now redesignated as the **Plan Compiler** — the LLM component that produces a structured ExecutionGraph from a VAPT goal, and is re-invoked only for replan / exception / final synthesis. The host-state Phase Graph Scheduler executes the plan deterministically.
_Avoid_: coordinator, reactive loop, always-on agent

**Expert Agent**:
A scoped agent declared in YAML that performs one security domain of work through its allowed Skills.
_Avoid_: subagent, worker, specialist service

**Skill**:
A packaged security capability with metadata, schemas, and a handler that returns structured results.
_Avoid_: tool script, command wrapper

**Skill Finding**:
A structured security observation returned by a Skill, classified as either a confirmed Vulnerability or a Vulnerability Candidate.
_Avoid_: raw log line, narrative summary, scanner-only text

**CMDB**:
The local inventory of scans, assets, services, vulnerabilities, white-box assessment records, and report metadata.
_Avoid_: database, asset store

**Asset**:
A host or domain discovered during VAPT work; the same real host or domain remains one Asset across scans.
_Avoid_: URL, endpoint, port, service

**Asset Type**:
The primary business classification for an Asset in dashboard distribution: 业务, 智能体, OA, 中间件, 支撑, 内网, or 其他.
_Avoid_: web_app, api, database, server, network

**Service**:
A network port on an Asset, including its last known state and service fingerprint.
_Avoid_: asset, middleware asset

**Managed Asset**:
A scan-discovered asset that has been accepted into the CMDB and participates in dashboard aggregation, topology, and vulnerability matching.
_Avoid_: free asset, owned asset, persisted asset, asset store entry

**Public Asset Candidate**:
A public-internet host or domain discovered from an external asset search source whose organizational ownership has not been confirmed.
_Avoid_: Managed Asset, owned asset, scan asset

**Public Asset Candidate Status**:
The review lifecycle for a Public Asset Candidate: unreviewed, promoted, or dismissed.
_Avoid_: scan status, vulnerability status

**Public Asset Discovery Notification**:
A grouped notification emitted when Scheduled Public Asset Discovery creates new unreviewed Public Asset Candidates for an Organization Scope.
_Avoid_: evidence refresh alert, dismissed rediscovery alert

**Public Asset Evidence**:
A source-returned observation that explains why a Public Asset Candidate was discovered or may belong to an Organization Scope.
_Avoid_: Service, confirmed fingerprint, vulnerability evidence

**Organization Scope**:
The organization whose public-internet assets are being searched for, identified by a required name and optional ownership evidence such as aliases, root domains, ICP subjects, certificate subjects, ASNs, IP ranges, include terms, and exclude terms.
_Avoid_: search keyword, customer, tenant

**Scheduled Public Asset Discovery**:
A configured recurring job that queries external asset search sources on a user-selected daily cadence of every 4, 8, or 12 hours to refresh Public Asset Candidates for an Organization Scope without active probing.
_Avoid_: scheduled scan, automatic vulnerability scan, active scan

**External Asset Search Source**:
A supported third-party index of public-internet assets used for passive asset discovery; the initial canonical sources are FOFA, Quake, and Shodan.
_Avoid_: sodan, quark, search engine

**External Asset Search Credential**:
A platform-level credential used to query one External Asset Search Source.
_Avoid_: search rule secret, organization credential, scan credential

**Public Asset Discovery Workspace**:
The asset/CMDB frontend area for Organization Scopes, Asset Search Rules, Scheduled Public Asset Discoveries, Public Asset Candidates, and promotion into Managed Assets.
_Avoid_: White-Box Workspace, Session page, scan detail page

**Scan Prompt Draft**:
A generated natural-language scan request prepared from selected Managed Assets and shown in a Session for user confirmation before any Scan starts.
_Avoid_: automatic scan, one-click scan execution, scan job

**Asset Search Rule**:
A source-specific query rule used to find Public Asset Candidates for an Organization Scope from an external asset search source.
_Avoid_: keyword, scan keyword, dork

**Asset Auto-Management**:
A session-level mode that is off by default and accepts scan discoveries into the CMDB as Managed Assets only after the user explicitly enables it for the session; when disabled, discoveries remain transient and do not enter dashboard, topology, or vulnerability matching views.
_Avoid_: one-off asset import, per-row asset button

**Asset Risk Topology**:
A graph of Managed Assets, their Services, and related vulnerabilities, used to show asset risk relationships rather than physical network links.
_Avoid_: physical network topology, switch topology

**Topology Focus**:
The node chosen as the visual center of the Asset Risk Topology.
_Avoid_: root asset, ownership parent

**Vulnerability Identity**:
The stable grouping key for a vulnerability, merging CVE and CNVD aliases into one logical finding when they refer to the same issue.
_Avoid_: scan hit, duplicate CVE/CNVD node

**Vulnerability Candidate**:
A possible vulnerability inferred from a Service fingerprint or vulnerability database match before active verification; its lifecycle is candidate, verified, or dismissed.
_Avoid_: confirmed vulnerability, scan finding

**Vulnerability**:
A runtime security issue confirmed by verification evidence during a Scan.
_Avoid_: possible issue, raw scanner hit, summary-only finding

**Vulnerability Verification**:
An LLM-assisted stage in the VAPT pipeline where an Expert Agent invokes Skills and knowledge base to reproduce candidate vulnerabilities, eliminate false positives, and confirm severity. Not a manual human pause — the Expert Agent actively probes and reports evidence.
_Avoid_: manual verification, human review, pause-and-wait

**White-Box Assessment**:
A source-code-level security assessment started from an uploaded source package, separate from conversational VAPT scanning.
_Avoid_: Scan, vuln_detec, dynamic scan, URL probe

**White-Box Assessment Lifecycle**:
The independent task state model for a White-Box Assessment, separate from the Scan lifecycle.
_Avoid_: scan status, conversation turn status

**White-Box Finding**:
A source-code-level security finding produced by a White-Box Assessment before runtime verification or manual confirmation.
_Avoid_: Vulnerability, confirmed vulnerability, scan finding

**White-Box Evidence**:
Structured source-code evidence for a White-Box Finding, including entry points, sources, sinks, sanitizers, data-flow paths, file locations, and analyzer identifiers.
_Avoid_: Markdown report, model explanation, raw log

**White-Box Finding Status**:
The review lifecycle for a White-Box Finding: open, needs_review, confirmed, dismissed, or promoted.
_Avoid_: Vulnerability Candidate status, scan status

**White-Box Assessment Notification**:
A task-level notification emitted when a White-Box Assessment completes, fails, or is cancelled.
_Avoid_: per-finding alert, scan notification

**Analyzer Adapter**:
A language- or framework-aware analysis capability that can extract source-code structure, entry points, data flow, sinks, sanitizers, and line-level evidence for White-Box Findings.
_Avoid_: prompt template, regex rule, language whitelist

**Reproduction Document**:
A Markdown artifact for a White-Box Finding that records source evidence and runnable reproduction guidance for later vulnerability verification.
_Avoid_: model summary, informal notes, confirmed PoC

**Reproduction Document Template**:
The required Markdown structure for a Reproduction Document so humans and Document-Guided Verification can consume it consistently.
_Avoid_: free-form report, analyst notes

**Document-Guided Verification**:
A user-initiated verification flow that consumes a Reproduction Document and, when runtime targets are required, creates an explicit Scan under the existing authorization and high-risk safety model.
_Avoid_: automatic PoC, background verification, source analysis

**White-Box Workspace**:
The dedicated frontend area for creating, tracking, reviewing, and verifying White-Box Assessments.
_Avoid_: Session page, chat panel, scan detail page

**Source Package**:
An uploaded `.zip` or `.tar.gz` archive containing source code for a White-Box Assessment.
_Avoid_: repository URL, local path, project directory

**Report Artifact**:
A generated VAPT deliverable such as HTML, Markdown, DOCX, or PDF.
_Avoid_: output file, export

**Partial Report Artifact**:
A Report Artifact generated while one or more upstream PlanNodes remain unresolved, explicitly carrying coverage and incomplete-work metadata.
_Avoid_: complete report, silent best-effort report, failed report

**ExecutionGraph**:
A structured, validated DAG of PlanNodes produced by the Plan Compiler. Each node declares its kind, handler, dependencies, state inputs, budget class, dedupe key, success criteria, and failure policy. The Phase Graph Scheduler executes this graph deterministically.
_Avoid_: execution plan, batch list, task list

**PlanNode**:
One unit of work within an ExecutionGraph — represents a single agent invocation, batch tool call, evaluator gate, or report generation step.
_Avoid_: task, step, batch item

**PlanNode Attempt**:
One execution try of a PlanNode, preserving the PlanNode identity while recording a new attempt number after redispatch.
_Avoid_: duplicate PlanNode, new scan task, ad-hoc retry

**PlanNode Budget**:
The cumulative execution budget for a PlanNode across all PlanNode Attempts, including iteration, token, tool-call, and wall-clock limits.
_Avoid_: per-attempt reset, unlimited retry budget, session-wide only limit

**Interrupted Attempt Status**:
The outward status for a PlanNode Attempt that stopped after a Recoverable Execution Interruption and produced a Handoff Summary while the PlanNode remains unfinished.
_Avoid_: completed, error, failed task

**Recoverable Execution Interruption**:
A non-terminal PlanNode execution outcome where an Expert Agent exhausts its iteration or context budget after producing a handoff summary.
_Avoid_: completed task, crashed agent, hard failure

**Handoff Summary**:
A tool-free Expert Agent summary that records completed work, evidence found, unfinished branches, blockers, and recommended continuation after a Recoverable Execution Interruption.
_Avoid_: final report, continued probing, tool retry

**Attempt Wind-Down**:
The bounded closing phase after a PlanNode Attempt exhausts its budget, where no new Skills are started and already-running Skills are allowed to finish or time out.
_Avoid_: immediate abort, unlimited wait, continued exploration

**Phase Graph Scheduler**:
The host-state component that receives an ExecutionGraph from the Plan Compiler, resolves dependencies, dispatches ready nodes through the Tool Gateway, evaluates phase gates, and triggers replan when needed. Reuses WorkflowRunner step-execution logic.
_Avoid_: workflow engine, orchestrator loop, reactive scheduler

**Tool Gateway**:
The middleware layer between the Phase Graph Scheduler and Skill/Agent executors. Responsible for argument canonicalization, semantic deduplication, in-flight join, batch fusion, budget guarding, result caching, and no-delta blocking.
_Avoid_: tool executor, skill adapter, direct tool call

**State View**:
A typed, minimal, read-only projection of Blackboard + AssetFeed + CMDB, materialized per PlanNode before execution. Replaces the pattern of LLM calling read_blackboard / read_assets / read_file to manually gather context.
_Avoid_: state snapshot, context dump, transcript

**Progress Delta**:
A host-observed state change that proves a PlanNode Attempt advanced the Scan, such as new structured findings, newly covered targets, new verification evidence, or new persisted result references.
_Avoid_: repeated polling, repeated context reads, self-reported progress only

## Relationships

- A **Surface** sends a user message into exactly one **Agent Turn Runtime** execution.
- A **Session** contains one or more **Agent Turn Runtime** executions.
- A **Session** may start one or more **Scans**.
- A **Scan** belongs to exactly one **Session**.
- The **Agent Turn Runtime** runs the **Orchestrator** for the turn.
- The **Orchestrator** delegates operational work to one or more **Expert Agents**.
- An **Expert Agent** invokes one or more **Skills**.
- A **Skill** may persist structured findings into the **CMDB**.
- An **Asset** may expose one or more **Services**.
- An **Asset** has at most one primary **Asset Type** for dashboard distribution.
- A repeated discovery of the same **Asset** updates related **Services**, vulnerabilities, fingerprints, and topology state without creating a duplicate **Asset**.
- A **Service** that is found closed in a later scan is marked closed rather than deleted.
- A **Service** state is updated only when the latest scan explicitly covered that port.
- A **Managed Asset** is persisted in the **CMDB** after being discovered by a **Skill**.
- An **Organization Scope** has a required name and may have optional ownership evidence to improve asset search precision.
- An **Organization Scope** may produce zero or more **Public Asset Candidates**.
- An **Organization Scope** may have zero or more **Scheduled Public Asset Discoveries**.
- An **Organization Scope** may have one or more **Asset Search Rules**.
- An **Asset Search Rule** belongs to exactly one **Organization Scope** and one **External Asset Search Source**.
- An **External Asset Search Credential** belongs to one **External Asset Search Source** and is configured at platform level, not per **Organization Scope** or **Asset Search Rule**.
- An **Asset Search Rule** references an **External Asset Search Source** but does not store credentials.
- A default **Asset Search Rule** may be generated from the **Organization Scope** name, and users may add, edit, disable, or annotate source-specific rules.
- A **Scheduled Public Asset Discovery** runs on a user-selected daily cadence of every 4, 8, or 12 hours.
- A **Scheduled Public Asset Discovery** executes enabled **Asset Search Rules** for its **Organization Scope**.
- A **Scheduled Public Asset Discovery** updates **Public Asset Candidates** and must not run port scans, vulnerability scans, weak-password checks, or PoC verification.
- The **Public Asset Discovery Workspace** belongs to the asset/CMDB area and separates **Public Asset Candidates** from **Managed Assets**.
- A **Public Asset Candidate** has a **Public Asset Candidate Status**.
- **Public Asset Candidate Status** values are `unreviewed`, `promoted`, and `dismissed`.
- A **Public Asset Candidate** may become a **Managed Asset** only after a user confirms organizational ownership and authorization scope.
- A `dismissed` **Public Asset Candidate** remains dismissed when rediscovered; rediscovery updates evidence and last-seen metadata without returning it to `unreviewed`.
- A **Public Asset Candidate** does not participate in dashboard aggregation, topology, vulnerability matching, or active scanning.
- A **Public Asset Candidate** represents a host or domain; source-returned ports, URLs, titles, banners, certificates, and protocols are **Public Asset Evidence** until active scanning creates **Services**.
- A **Public Asset Candidate** may have one or more **Public Asset Evidence** records from one or more **External Asset Search Sources**.
- When a **Public Asset Candidate** is promoted to a **Managed Asset**, its **Public Asset Evidence** is retained for discovery-source audit, but source-returned ports do not become **Services** until active scanning observes them.
- **Public Asset Candidates** are deduplicated by **Organization Scope** and normalized host or domain; repeated matches merge **Public Asset Evidence** rather than creating duplicate candidates.
- The same host or domain may appear as separate **Public Asset Candidates** under different **Organization Scopes** because organizational ownership is scope-specific.
- The **Public Asset Discovery Workspace** may create a **Scan Prompt Draft** from selected **Managed Assets** and redirect the user to a **Session** for confirmation.
- A **Scan Prompt Draft** may target **Managed Assets** only; **Public Asset Candidates** must be promoted first.
- A **Scan Prompt Draft** does not create a **Scan** until the user confirms it in the **Session**.
- A **Scan Prompt Draft** lists selected **Managed Assets** and the intended scan request, but does not repeat an authorization confirmation statement.
- A **Scheduled Public Asset Discovery** emits a **Public Asset Discovery Notification** only when it creates new `unreviewed` **Public Asset Candidates**.
- Evidence refreshes, rediscovered dismissed candidates, and already promoted candidates do not emit **Public Asset Discovery Notifications**.
- User-edited **Asset Type** and business-system tags take precedence over automatic scan classification.
- **Asset Auto-Management** turns scan discoveries into **Managed Assets** during a **Session**.
- **Asset Auto-Management** is scoped to the session that owns the scan discoveries; scans in that session use the session's current auto-management state.
- When **Asset Auto-Management** is disabled, scan discoveries stay outside the **CMDB** and do not update existing **Managed Assets**.
- The **Asset Risk Topology** includes **Managed Assets** and updates when asset, service, fingerprint, or vulnerability observations change.
- The **Asset Risk Topology** defaults to all **Managed Assets**; recent scans, business systems, subnets, asset types, and vulnerability status are filters.
- The **Asset Risk Topology** sizes vulnerability nodes by the number of unique **Managed Assets** affected by each **Vulnerability Identity**.
- A **Topology Focus** changes the topology layout center without changing CMDB relationships.
- A **Service** fingerprint can produce a **Vulnerability Candidate** through passive version matching.
- A **Vulnerability Candidate** does not trigger active vulnerability scanning automatically; the user must explicitly start verification.
- A **Vulnerability Candidate** is displayed separately from confirmed vulnerabilities and is not counted in confirmed vulnerability totals, alerts, trends, or report findings.
- A **Vulnerability Candidate** is persisted separately from confirmed vulnerabilities so it can appear in asset detail and topology before verification.
- The **Asset Risk Topology** may show both confirmed vulnerabilities and **Vulnerability Candidates**, but they must be visually distinct.
- A verified **Vulnerability Candidate** produces a confirmed vulnerability record.
- A **White-Box Assessment** analyzes an uploaded source package rather than network targets and is not a **Scan**.
- A **White-Box Assessment** uses a **White-Box Assessment Lifecycle** and must not reuse **Scan** rows, **Scan** status transitions, or **Scan** dashboard counts.
- A **White-Box Assessment Lifecycle** includes queued, unpacking, analyzing, generating_docs, completed, failed, and cancelled states.
- A **White-Box Assessment** runs asynchronously after upload; the frontend observes lifecycle progress and reads results after completion.
- A **White-Box Assessment** emits **White-Box Assessment Notifications** when it completes, fails, or is cancelled.
- A completed **White-Box Assessment Notification** includes finding counts and confidence distribution, not one notification per **White-Box Finding**.
- A **White-Box Assessment** and its **White-Box Findings** are persisted in the **CMDB** using white-box-specific tables, not the existing **Scan** or confirmed **Vulnerability** tables.
- A **White-Box Assessment** is started from the **White-Box Workspace**, not from the existing **Session** conversation page.
- The **White-Box Workspace** is a top-level frontend navigation entry with assessment list, create assessment, assessment detail, finding review, Reproduction Document, and Document-Guided Verification views.
- A **White-Box Assessment** may produce vulnerabilities, a vulnerability list, and reproduction paths, but does not execute active PoC traffic against public assets unless the user explicitly starts a **Scan**.
- A **White-Box Assessment** treats uploaded source as untrusted input and must not execute project code, install project dependencies, run project tests, or start project services in the MVP.
- An **Analyzer Adapter** reads files, parses source structure, extracts evidence, and generates findings without executing uploaded code.
- A **White-Box Assessment** accepts a **Source Package** in `.zip` or `.tar.gz` format, up to 200 MB compressed and 1 GB after extraction.
- A **Source Package** must be rejected when encrypted, path-traversing, absolute-path-based, symlink-escaping, or otherwise unsafe to extract.
- A **Source Package** and its extracted workspace are retained until the user deletes the **White-Box Assessment** or explicitly purges source material for that assessment.
- Purging source material keeps **White-Box Findings** and **Reproduction Documents** while deleting the uploaded archive and extracted source workspace.
- A **White-Box Assessment** skips dependency/vendor/build directories and large binary files by default, including `node_modules`, `.git`, `dist`, `build`, and `target`.
- A **White-Box Assessment** produces **White-Box Findings** rather than confirmed **Vulnerabilities** by default.
- A **White-Box Finding** is grounded in **White-Box Evidence** stored as structured data.
- A **White-Box Finding** uses the same severity vocabulary as confirmed **Vulnerabilities**: `critical`, `high`, `medium`, `low`, and `info`.
- A **White-Box Finding** severity is scored from source evidence quality, vulnerability type, data-flow completeness, authorization boundary impact, sensitive data or dangerous operation impact, sanitizer absence, and confidence, not copied blindly from a static rule default.
- **White-Box Findings** are deduplicated within a **White-Box Assessment** by analyzer, vulnerability type, primary file, primary sink line, and normalized source-to-sink path.
- Similar **White-Box Findings** across different **White-Box Assessments** are not automatically deduplicated because source versions may differ.
- A **White-Box Finding** has a **White-Box Finding Status**.
- **White-Box Finding Status** values are `open`, `needs_review`, `confirmed`, `dismissed`, and `promoted`.
- A `confirmed` **White-Box Finding** means the source-level conclusion is accepted, not that a runtime **Vulnerability** has been verified.
- A `promoted` **White-Box Finding** has been associated with or promoted to a confirmed **Vulnerability** after runtime verification or manual promotion.
- A **White-Box Finding** may be associated with or promoted to a confirmed **Vulnerability** only after runtime verification or manual confirmation.
- Dashboard confirmed vulnerability totals must not count **White-Box Findings** unless they are promoted to confirmed **Vulnerabilities**.
- A **White-Box Assessment** may accept any source language, but high-confidence **White-Box Findings** require an **Analyzer Adapter** for that language or framework.
- The first supported **Analyzer Adapters** are Java/Spring MVC/Spring Boot, JavaScript/TypeScript/Node.js/Express/NestJS, and Python/FastAPI/Django/Flask.
- An **Analyzer Adapter** provides structured evidence; model-generated explanations must not invent findings that lack analyzer evidence.
- A **White-Box Finding** has a **Reproduction Document** written to disk as Markdown.
- A **Reproduction Document** is rendered from **White-Box Evidence** and is not the source of truth for the finding.
- A **Reproduction Document** must ground later vulnerability verification in source evidence and reproduction guidance rather than unsupported model inference.
- A **Reproduction Document** follows a **Reproduction Document Template** with finding metadata, impact, source evidence, data-flow or call path, prerequisites, trigger steps or request sample, expected behavior, remediation, analyzer evidence ID, and generation time.
- A **Reproduction Document** may be consumed by **Document-Guided Verification** only after a user explicitly starts verification.
- **Document-Guided Verification** that needs a live runtime target requires the user to select or provide that target and must use the existing **Scan** authorization and high-risk safety model.
- A **White-Box Assessment** must not automatically start **Document-Guided Verification**.
- A **Managed Asset** without business-system attribution is grouped under 其他 until a user edits its tags.
- A **Report Artifact** is generated from structured findings in the **CMDB**.
- The **Orchestrator** (Plan Compiler) produces an **ExecutionGraph** rather than issuing reactive `create_agent` calls.
- An **ExecutionGraph** contains one or more **PlanNodes** with declared dependencies forming a DAG.
- A **PlanNode** may have one or more **PlanNode Attempts**.
- A redispatched **PlanNode Attempt** keeps the same **PlanNode** identity and increments the attempt number.
- A **PlanNode Budget** is cumulative across all **PlanNode Attempts** for the same **PlanNode**.
- A redispatched **PlanNode Attempt** may have a per-attempt limit but consumes only the remaining **PlanNode Budget**.
- A **PlanNode Attempt** with a **Recoverable Execution Interruption** is externally reported with **Interrupted Attempt Status**, not as completed or failed.
- The **Phase Graph Scheduler** executes an **ExecutionGraph** deterministically, dispatching each ready **PlanNode** through the **Tool Gateway**.
- A **Recoverable Execution Interruption** enters **Attempt Wind-Down** before producing a **Handoff Summary**.
- During **Attempt Wind-Down**, no new **Skills** are invoked, and already-running **Skills** are awaited until success, failure, or their bounded timeout.
- **Skill Findings** returned during **Attempt Wind-Down** are bridged into structured state by the host execution layer before the **Handoff Summary** is generated.
- A **Recoverable Execution Interruption** produces a **Handoff Summary** without invoking additional Skills or tools.
- A **Handoff Summary** is structured and includes progress, completed actions, persisted result references, unfinished actions, continuation point, blockers, recommended next action, user-input need, and confidence.
- A **Handoff Summary** recommends one next action from redispatch, replan, or ask user, while the **Phase Graph Scheduler** makes the final decision.
- A **Handoff Summary** references persisted result IDs or dedupe keys rather than carrying **Vulnerability**, **Asset**, or **Service** records as narrative text.
- When a structured **Handoff Summary** cannot be produced, the host runtime generates a deterministic fallback summary with low confidence and a replan recommendation while preserving **Interrupted Attempt Status**.
- A **Recoverable Execution Interruption** is reported to the **Phase Graph Scheduler**, which decides whether to redispatch the **PlanNode**, trigger replan, or request user input.
- `max_iterations` and `context_exhausted` both produce a **Recoverable Execution Interruption**.
- A `max_iterations` interruption may be automatically redispatched when a **Progress Delta** and continuation point exist.
- A `context_exhausted` interruption defaults to context compaction or **State View** rematerialization before redispatch or replan.
- The **Phase Graph Scheduler** automatically redispatches a **Recoverable Execution Interruption** at most once by default; a repeated interruption triggers replan or user input instead of another automatic attempt.
- The **Phase Graph Scheduler** automatically redispatches an interrupted **PlanNode** only when a **Progress Delta** exists, the **Handoff Summary** gives an explicit continuation point, and no user-decision blocker exists.
- A **Recoverable Execution Interruption** without meaningful progress or with repeated same-class blockers triggers replan instead of automatic redispatch.
- Repeated context reads, repeated asset polling with no new assets, or repeated scans with no new result references are not **Progress Deltas**.
- A **Recoverable Execution Interruption** caused by missing authorization, target scope, risk confirmation, or user-owned information triggers user input instead of automatic redispatch.
- A downstream **PlanNode** dependency is not satisfied by an upstream **Interrupted Attempt Status** unless the **Phase Graph Scheduler** explicitly skips or dismisses that upstream work.
- A **Report Artifact** may be generated after unresolved upstream work only as a **Partial Report Artifact**.
- A **Partial Report Artifact** includes persisted findings that already exist, while marking unresolved **PlanNodes** and uncovered scope as incomplete.
- An **Expert Agent** must persist confirmed **Vulnerabilities**, discovered **Assets**, and observed **Services** as structured state when they are found, before any **Handoff Summary**.
- A **Handoff Summary** is not the source of truth for **Vulnerabilities**, **Assets**, **Services**, or **Report Artifacts**.
- A **Skill Finding** is bridged into structured state by the **Tool Gateway** or Skill execution layer, not by waiting for an **Expert Agent** to restate it.
- A verified or confirmed **Skill Finding** becomes a confirmed **Vulnerability**; an unverified or low-confidence **Skill Finding** becomes a **Vulnerability Candidate**.
- The **Tool Gateway** sits between the **Phase Graph Scheduler** and **Skill** / **Expert Agent** executors; all tool invocations pass through it.
- A **State View** is materialized per **PlanNode** before execution, replacing manual `read_blackboard` / `read_assets` / `read_file` calls.
- The **Phase Graph Scheduler** re-invokes the **Orchestrator** (Plan Compiler) only for replan, exception recovery, or final synthesis.
- During migration, the legacy reactive **Agent Turn Runtime** must honor the same **Recoverable Execution Interruption**, **Interrupted Attempt Status**, **Handoff Summary**, and **Skill Finding** persistence semantics as the **Phase Graph Scheduler** path.

## Example dialogue

> **Dev:** "Should the WebUI own tool-call streaming state?"
> **Domain expert:** "No - the **Surface** should render events emitted by the **Agent Turn Runtime**, not reconstruct runtime state from scattered hints."

## Flagged ambiguities

- "subagent" appears in implementation names, but domain discussion should use **Expert Agent** when referring to YAML-scoped security agents.
- "调度" around interrupted Expert Agent work was ambiguous with the reactive Orchestrator loop; resolved: use **Phase Graph Scheduler** for redispatch decisions after a **Recoverable Execution Interruption**.
- "总结阶段" after Expert Agent budget exhaustion was ambiguous with continued probing; resolved: produce a tool-free **Handoff Summary**, and let the **Phase Graph Scheduler** decide the next execution attempt.
- Budget exhaustion timing was ambiguous when Skills are still running; resolved: use **Attempt Wind-Down** to wait for already-started Skills to finish or time out before summarizing.
- Wind-down result ownership was ambiguous; resolved: **Skill Findings** produced during **Attempt Wind-Down** are still persisted by the host execution layer, not by another Expert Agent tool call.
- "重新派发" was ambiguous with creating a new task; resolved: redispatch creates a new **PlanNode Attempt** under the same **PlanNode** identity.
- Migration scope was ambiguous; resolved: recoverable interruption and Skill Finding persistence semantics apply to both the legacy reactive **Agent Turn Runtime** path and the future **Phase Graph Scheduler** path.
- Automatic redispatch count was ambiguous; resolved: the default is one automatic redispatch, after which repeated interruption escalates to replan or user input.
- Automatic redispatch conditions were ambiguous; resolved: redispatch requires meaningful progress, a clear continuation point, and no user-decision blocker.
- Meaningful progress was ambiguous as a narrative claim; resolved: require a host-observed **Progress Delta**, and repeated no-delta reads or scans do not qualify.
- Handoff content was ambiguous as free text; resolved: a **Handoff Summary** is structured, references persisted result identities, and only recommends redispatch, replan, or ask user.
- Handoff generation failure was ambiguous; resolved: host runtime emits a deterministic fallback **Handoff Summary** with low confidence and replan recommendation, keeping the attempt interrupted.
- `max_iterations` and `context_exhausted` were ambiguous as separate failure classes; resolved: both are **Recoverable Execution Interruption** outcomes, with `context_exhausted` prioritizing context compaction or **State View** rematerialization before continuation.
- Downstream dependency behavior was ambiguous for interrupted work; resolved: **Interrupted Attempt Status** does not satisfy dependencies by default, and reports generated before resolution are **Partial Report Artifacts** with explicit incomplete metadata.
- Redispatch budget was ambiguous; resolved: **PlanNode Budget** is cumulative and is not reset by a new **PlanNode Attempt**.
- `max_iterations` was mapped to `completed` in some runtime status surfaces; resolved: expose **Interrupted Attempt Status** for recoverable budget exhaustion because the **PlanNode** is not complete.
- "总结后上报" was ambiguous with extracting findings from narrative text; resolved: confirmed scan results are persisted as structured state when found, and **Handoff Summary** only carries execution continuity context.
- Skill-returned `findings` were ambiguous because Expert Agents could fail to restate them before interruption; resolved: use **Skill Finding** and bridge structured Skill results into **Vulnerabilities** or **Vulnerability Candidates** in the host execution layer.
- "free asset", "owned asset", and "persisted asset" were used around scan-discovered assets; resolved: use **Managed Asset** for assets accepted into the CMDB and governance views.
- "asset import button" was used for a continuous scan behavior; resolved: use **Asset Auto-Management** because the decision applies to a session's ongoing discoveries, not a single row.
- A disabled **Asset Auto-Management** toggle was ambiguous because some current asset feed events auto-flush to CMDB; resolved: disabled means no scan discovery updates the managed asset corpus.
- Auto-management scoping was described as a `chat_id` permission; resolved: it is a session-scoped ingestion state, and scan tasks belong to a session.
- "asset" could mean host, URL, port, or middleware; resolved: an **Asset** is a host or domain, while ports and middleware are represented as **Services** or service fingerprints.
- Existing assets were described as "not overwritten"; resolved: repeat discoveries do not duplicate the **Asset** and should only update related observations or fill missing automatically discovered fields.
- Closed ports were discussed as removals; resolved: a later scan that confirms closure updates the **Service** state instead of deleting the **Service**.
- A missing port in a partial scan is not evidence that the **Service** closed; only covered ports can change service state.
- "network topology" could imply physical links; resolved: use **Asset Risk Topology** for the scan-derived graph of managed assets, services, and vulnerabilities.
- CVE and CNVD identifiers were discussed as separate labels; resolved: they are aliases of one **Vulnerability Identity** when they refer to the same issue.
- "center point" could imply an ownership root; resolved: use **Topology Focus** as a view concern only.
- `chat_id` was discussed around CMDB writes; resolved: it is the implementation identifier for a **Session**, not a permission boundary.
- Old asset distribution labels (`web_app`, `api`, `database`, `server`, `network`) conflict with current business labels; resolved: use the **Asset Type** vocabulary `业务 / 智能体 / OA / 中间件 / 支撑 / 内网 / 其他`.
- Assets without business-system attribution were discussed as "unclassified"; resolved: group them as 其他 because users can manually edit tags later.
- Automatic classification was discussed alongside user tag edits; resolved: user-edited asset tags must not be overwritten by later scan classification.
- Version-based vulnerability matching was discussed as scanning; resolved: passive matching creates a **Vulnerability Candidate**, while active verification is a separate action.
- Automatic vulnerability scanning from version matches was considered; resolved: the system must not start active vulnerability scans without an explicit user request.
- Candidate vulnerabilities were discussed alongside confirmed findings; resolved: **Vulnerability Candidates** do not count as confirmed vulnerabilities.
- Candidate persistence was discussed; resolved: **Vulnerability Candidates** are stored separately from confirmed vulnerability records.
- Candidate lifecycle was discussed; resolved: use `candidate`, `verified`, and `dismissed`, with scan failures remaining `candidate` plus failure evidence.
- Topology vulnerability display was discussed; resolved: confirmed vulnerabilities and **Vulnerability Candidates** can appear together, but candidates are visually distinct and excluded from confirmed risk statistics.
- Topology scope was discussed; resolved: default scope is all **Managed Assets**, while recent scans are a filter rather than the default corpus.
- Search-engine-discovered public assets were discussed as assets that "may belong" to an organization; resolved: use **Public Asset Candidate** until a user confirms ownership and authorization, then promote it to **Managed Asset**.
- "指定企业或单位" was discussed as more than a free-text query; resolved: use **Organization Scope**, with only the organization name required and all other ownership evidence optional.
- "定时扫描公网资产" was ambiguous with active VAPT **Scan**; resolved: use **Scheduled Public Asset Discovery** for user-scheduled external search only, with no active probing.
- Public asset discovery frontend placement was discussed; resolved: use **Public Asset Discovery Workspace** inside the asset/CMDB area, with separate views for Organization Scopes, Asset Search Rules, schedules, Public Asset Candidates, and Managed Assets.
- Discovery timing was discussed as arbitrary scheduling; resolved: **Scheduled Public Asset Discovery** supports daily cadence options of every 4, 8, or 12 hours.
- "扫描关键词" was discussed as editable search input; resolved: use **Asset Search Rule** so each source-specific query can be traced, edited, disabled, and annotated.
- "一键扫描" was discussed around search-engine results; resolved: the asset workspace generates a **Scan Prompt Draft** for selected **Managed Assets** and redirects to a **Session** for user confirmation instead of directly creating a **Scan**.
- Source names were discussed as "sodan" and "quark"; resolved: use canonical **External Asset Search Source** names FOFA, Quake, and Shodan, with user-facing aliases normalized before persistence.
- External search credentials were discussed; resolved: use platform-level **External Asset Search Credentials** per source, and keep credentials out of **Organization Scopes** and **Asset Search Rules**.
- Search sources may return `ip:port`, URLs, banners, titles, protocols, and certificate data; resolved: **Public Asset Candidate** remains a host or domain, and these source-returned details are **Public Asset Evidence** rather than **Services**.
- Candidate deduplication was discussed; resolved: deduplicate **Public Asset Candidates** by **Organization Scope** plus normalized host/domain, merging cross-source evidence while keeping different scopes separate.
- Candidate review state was discussed; resolved: use **Public Asset Candidate Status** values `unreviewed`, `promoted`, and `dismissed`, and rediscovered dismissed candidates remain dismissed while evidence is refreshed.
- Candidate promotion evidence was discussed; resolved: promoted **Managed Assets** retain **Public Asset Evidence** for audit, while source-returned ports remain evidence until active scanning creates **Services**.
- Scan prompt wording was discussed; resolved: **Scan Prompt Drafts** should not repeat authorization-confirmation text, while still requiring **Public Asset Candidates** to be promoted before they can be included.
- Public asset discovery notifications were discussed; resolved: notify only for newly created `unreviewed` **Public Asset Candidates**, grouped by **Organization Scope**.
- "自动化白盒测试" was ambiguous with the existing `vuln_detec` dynamic Web endpoint verification; resolved: use **White-Box Assessment** for source-code-level assessment from an uploaded source package.
- White-box entry placement was discussed; resolved: **White-Box Assessment** has a dedicated frontend entry and does not run inside the existing **Session** conversation page.
- White-box frontend structure was discussed; resolved: use a top-level **White-Box Workspace** with assessment list, create assessment, assessment detail, finding review, Reproduction Document, and Document-Guided Verification views.
- White-box source input was discussed as repository, package, or local path; resolved: MVP accepts uploaded source packages only.
- White-box task modeling was discussed as possibly reusing **Scan**; resolved: **White-Box Assessment** uses an independent **White-Box Assessment Lifecycle** and does not reuse scan rows, scan status transitions, or scan dashboard counts.
- White-box persistence was discussed as a separate store versus existing inventory; resolved: persist **White-Box Assessments** and **White-Box Findings** in the **CMDB** with independent white-box tables.
- White-box execution timing was discussed; resolved: **White-Box Assessment** runs as an asynchronous background task after upload, with lifecycle progress exposed to the dedicated frontend entry.
- White-box notifications were discussed; resolved: emit task-level **White-Box Assessment Notifications** for completion, failure, and cancellation, with aggregate finding counts on completion.
- **Source Package** limits were discussed; resolved: MVP accepts `.zip` and `.tar.gz`, max 200 MB compressed and 1 GB extracted, rejects unsafe archives, and skips common dependency/vendor/build directories by default.
- **Source Package** retention was discussed; resolved: source archives and extracted workspaces are retained by default for review, and users can purge source material while keeping findings and reproduction documents.
- "漏洞清单" from source analysis was ambiguous with confirmed runtime vulnerabilities; resolved: use **White-Box Finding** for source-code-level findings, and promote only after runtime verification or manual confirmation.
- White-box finding deduplication was discussed; resolved: deduplicate within one **White-Box Assessment** by analyzer, vulnerability type, primary file, primary sink line, and normalized source-to-sink path, without cross-assessment deduplication.
- White-box severity was discussed; resolved: **White-Box Finding** uses the same severity vocabulary as confirmed **Vulnerabilities** but computes severity from white-box evidence rather than static rule defaults.
- **White-Box Finding** review state was discussed; resolved: use independent **White-Box Finding Status** values `open`, `needs_review`, `confirmed`, `dismissed`, and `promoted`, distinct from **Vulnerability Candidate** status and confirmed runtime vulnerabilities.
- White-box evidence storage was discussed; resolved: **White-Box Evidence** is structured data and the source of truth, while **Reproduction Documents** are Markdown artifacts rendered from that evidence.
- "复现路径" was discussed as a reusable Markdown artifact; resolved: use **Reproduction Document** for a source-evidence-backed file that later verification can consume to avoid hallucinated vulnerabilities.
- **Reproduction Document** structure was discussed; resolved: use a fixed **Reproduction Document Template** so the artifact is both readable and consumable by **Document-Guided Verification**.
- White-box execution safety was discussed; resolved: MVP performs static analysis only and does not execute uploaded code, install dependencies, run tests, or start services.
- Reproduction-document verification was discussed; resolved: use **Document-Guided Verification** as an explicit user action, and route any live-target verification through the existing **Scan** authorization and high-risk safety model.
- Language support was discussed as a potential upload restriction; resolved: uploads are not language-restricted, but high-confidence findings require an **Analyzer Adapter** with parser, entry-point extraction, source/sink/sanitizer rules, data-flow evidence, and line references.
- Initial **Analyzer Adapter** scope was discussed; resolved: MVP starts with Java/Spring MVC/Spring Boot, JavaScript/TypeScript/Node.js/Express/NestJS, and Python/FastAPI/Django/Flask.

## Threat Intelligence Glossary

**Threat Intelligence Module**:
An independent security workspace for consuming, storing, and presenting open-source threat intelligence focused on the Chinese transportation and maritime industries. Separate from the conversational VAPT pipeline; has its own storage, scheduled ingestion, API routes, and frontend pages.
_Avoid_: scan feature, dashboard sub-tab, VAPT extension

**Threat Group**:
A named adversary (APT, cybercrime group, or state-sponsored actor) tracked in the threat intelligence store, with aliases, known TTPs, target sectors, and associated infrastructure. Sourced primarily from MITRE ATT&CK Groups and enriched via AlienVault OTX. Users may mark groups as watched for priority monitoring.
_Avoid_: threat actor (implementation detail), IOC source, scan target

**Threat Group Watchlist**:
A user-maintained list of **Threat Groups** flagged for priority monitoring. Watchlisted groups surface their latest activity (new C2 IPs, new malware families, new exploited vulnerabilities) prominently on the overview page.
_Avoid_: favorite, bookmark, auto-subscribe

**Threat Infrastructure IP**:
An IP address associated with a known **Threat Group** as command-and-control (C2) infrastructure, sourced from abuse.ch ThreatFox and Feodo Tracker. Not a standalone indicator — always linked to a **Threat Group**.
_Avoid_: attack IP (too generic), scan source, blacklisted IP

**Threat Vulnerability**:
A vulnerability tracked in the threat intelligence store because it is in CISA KEV or has CVSS >= 7.0, including transportation-industry supply chain vulnerabilities identified via CPE matching against a maintained industry product list.
_Avoid_: scan vulnerability, CMDB vulnerability, Vulnerability Candidate

**Industry CPE List**:
A maintained list of Common Platform Enumeration identifiers for software and hardware products commonly deployed in the transportation and maritime sectors (e.g., Siemens SIMATIC, Inmarsat terminals, port SCADA systems). Used to filter **Threat Vulnerabilities** for supply chain relevance.
_Avoid_: asset fingerprint, scan CPE, generic product list

**Threat Malware Family**:
A named malware family or sample set associated with a **Threat Group**, sourced from abuse.ch MalwareBazaar. Records include sample hashes (MD5/SHA256), YARA rules, and behavioral indicators. Always bound to a **Threat Group**.
_Avoid_: standalone sample, virus signature, scan finding

**Threat Group Vulnerability Association**:
Evidence that a **Threat Group** is known to exploit a **Threat Vulnerability**, distinct from the vulnerability's general existence in CISA KEV or NVD.
_Avoid_: vulnerability ownership, scan finding relation, inferred asset exposure

**Maritime Intelligence Event**:
A safety or security event in the maritime domain, such as piracy incidents, navigation warnings, or GNSS interference reports. Sourced from unstructured public sources (IMO GISIS, UKMTO, ReCAAP ISC) via LLM-assisted extraction rather than dedicated crawlers.
_Avoid_: ship tracking, AIS data, weather alert

**Threat Intel Store**:
An independent SQLite database (`threat_intel.sqlite3`) with its own ORM models, repository layer, and migration scripts. Separate from the CMDB and the detection results database. Scheduled ingestion is driven by the Workflow system.
_Avoid_: CMDB extension, detection_results table, scan database

**Threat Intel Feed Pull**:
A scheduled Workflow job that fetches data from configured external sources, applies severity and relevance filters, deduplicates against existing records, and upserts into the **Threat Intel Store**. LLM extraction is used for unstructured sources (maritime PDF/HTML reports).
_Avoid_: real-time stream, webhook listener, scan trigger

**Threat Intel Feed Run**:
One execution record for a **Threat Intel Feed Pull**, including source, trigger, freshness, inserted/updated/skipped counts, unmapped records, and failure details.
_Avoid_: scan task, workflow result blob, generic log line

**Threat Intel Knowledge Graph**:
An interactive graph visualization of the **Threat Intel Store** entities and their relationships, rendered with reactflow. Available in two modes: a local graph embedded in the **Threat Group** detail page (radial layout, single group center) and a global graph page at `/threat-intel/graph` (force-directed layout, multiple groups). Nodes represent Threat Groups, Threat Infrastructure IPs, Threat Malware Families, and Threat Vulnerabilities; edges represent uses_c2, uses_malware, exploits, and targets relationships. **Maritime Intelligence Events** are excluded from the graph as an independent time-series dimension.
_Avoid_: network topology, asset topology, maritime graph

**Threat Intel Graph Cluster**:
An aggregated node in the **Threat Intel Knowledge Graph** that represents multiple same-type satellite entities collapsed into one (e.g., "C2 IP x67") when the count exceeds the configurable `top_n` threshold (default 30). Users can click a cluster node to expand it into individual entities via a follow-up API call.
_Avoid_: graph grouping, manual folder, pagination

## Threat Intelligence Relationships

- A **Threat Group** may have zero or more associated **Threat Infrastructure IPs**.
- A **Threat Group** may use zero or more **Threat Malware Families**.
- A **Threat Group** may have zero or more **Threat Group Vulnerability Associations**.
- A **Threat Group Vulnerability Association** links exactly one **Threat Group** to exactly one **Threat Vulnerability** it is known to exploit.
- A **Threat Group** may be on a user's **Threat Group Watchlist**.
- A **Threat Vulnerability** is identified by CVE ID and is included when it appears in CISA KEV or has CVSS severity of 7.0 or above.
- A **Threat Vulnerability** may be flagged as supply-chain-relevant when its CPE matches the **Industry CPE List**.
- A **Threat Infrastructure IP** belongs to exactly one **Threat Group**.
- A **Threat Malware Family** belongs to exactly one **Threat Group**.
- A **Maritime Intelligence Event** is independent of **Threat Groups** and stored as standalone time-series data.
- **Threat Intel Feed Pulls** run on a Workflow-defined schedule and upsert into the **Threat Intel Store**.
- A **Threat Intel Feed Pull** produces one **Threat Intel Feed Run** per execution.
- The **Threat Intelligence Module** has a dedicated top-level navigation entry in the frontend, separate from VAPT **Sessions**, **Dashboard**, and **Workflows**.
- The **Threat Intelligence Module** overview page presents summary cards for threat groups, vulnerabilities, C2 infrastructure, malware activity, and maritime events, each drillable to a detail view.
- The **Threat Intel Knowledge Graph** renders **Threat Groups** as central nodes with **Threat Infrastructure IPs**, **Threat Malware Families**, and **Threat Vulnerabilities** as satellite nodes connected by typed edges.
- The **Threat Intel Knowledge Graph** local mode is embedded in the **Threat Group** detail page and uses radial layout; the global mode is a standalone page at `/threat-intel/graph` using force-directed layout.
- A **Threat Intel Graph Cluster** replaces individual satellite nodes when a single group's association count for one entity type exceeds `top_n`, and expands on user click.
- **Maritime Intelligence Events** do not appear in the **Threat Intel Knowledge Graph** because they have no association with **Threat Groups**.

## Threat Intelligence Flagged Ambiguities

- "威胁情报" was discussed as either a VAPT enhancement or an independent module; resolved: independent module with its own storage, scheduling, and frontend, decoupled from the VAPT pipeline.
- Data ingestion was discussed as on-demand query vs. scheduled pull; resolved: scheduled pull via Workflow jobs, with LLM extraction for unstructured sources.
- Storage scope was discussed as all-source full ingest vs. filtered; resolved: high-value sources only, CISA KEV or severity >= high (CVSS 7.0+), China transportation/maritime industry relevance filter.
- Supply chain vulnerability was discussed as product-level or attack-level; resolved: product-level CPE matching against a maintained **Industry CPE List**, not supply-chain-attack attribution.
- Threat vulnerabilities were discussed as always APT-bound vs. independently tracked CVEs; resolved: **Threat Vulnerabilities** can exist independently, and known exploitation by a group is captured through **Threat Group Vulnerability Associations**.
- Attack IPs and malware were discussed as standalone dimensions; resolved: both are bound to **Threat Groups** as the central association hub (APT-centric star model).
- Maritime intelligence sources were discussed as dedicated crawlers vs. LLM extraction; resolved: LLM-based extraction from unstructured public sources (IMO GISIS HTML, UKMTO/ReCAAP PDFs), avoiding fragile dedicated crawlers.
- Threat group initial corpus was discussed; resolved: MITRE ATT&CK Groups as base data, AlienVault OTX for industry-tagged enrichment, Chinese APT alias mapping table maintained separately, user watchlist for priority monitoring.
- Frontend entry point was discussed as dashboard sub-tab vs. new nav item; resolved: top-level navigation entry "威胁情报" with a Dashboard-style overview page and drill-down detail views.
- Storage location was discussed as CMDB extension vs. independent database; resolved: independent `threat_intel.sqlite3` with its own ORM, repository, and migration, separate from CMDB and detection results.
- Knowledge graph visualization library was discussed; resolved: reuse reactflow (already in `package.json`), not introduce a new graph library.
- Knowledge graph scope was discussed as global-only vs. local-only; resolved: dual-mode — local graph in **Threat Group** detail page (radial layout) plus global page at `/threat-intel/graph` (force-directed layout).
- Knowledge graph node interaction was discussed; resolved: single-click opens a side drawer with summary and animates the graph to center on the clicked node, no navigation to a separate detail page.
- Knowledge graph performance was discussed for large datasets; resolved: configurable `top_n` clustering (default 30) with expandable cluster nodes, global graph initial render capped at 100-200 nodes.
- **Maritime Intelligence Events** were discussed for graph inclusion; resolved: excluded from the **Threat Intel Knowledge Graph** because they are an independent time-series dimension with no **Threat Group** associations.
- Knowledge graph MVP phase was discussed; resolved: placed entirely in P1 because P0 only has Group + IP (too sparse for a valuable graph), and P0 delivery is already heavy.
