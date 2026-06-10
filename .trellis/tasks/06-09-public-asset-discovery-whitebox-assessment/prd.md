# 公网资产发现与白盒评估 PRD

## Problem Statement

安全运营人员需要持续发现可能属于指定企业或单位的公网资产，并将确认归属后的资产纳入现有 CMDB 和 VAPT 扫描流程。当前系统已有 Asset、Managed Asset、Scan、Session、CMDB、Vulnerability Candidate 和报告链路，但缺少面向 FOFA、Quake、Shodan 等外部资产搜索源的被动发现、候选资产审核、定时发现和候选晋升能力。

同时，安全测试人员需要上传源码包进行自动化 White-Box Assessment，输出可审计的 White-Box Findings、结构化 White-Box Evidence 和 Markdown Reproduction Documents。现有 vuln_detec 面向运行中 Web endpoint 的动态验证，不适合作为源码级白盒评估入口；白盒结果也不能直接污染 confirmed Vulnerability、Scan 统计或资产拓扑。

## Solution

新增两个互相独立但能接入现有安全作业流程的能力：

1. **Public Asset Discovery Workspace**：在资产/CMDB 区域增加 Organization Scope、Asset Search Rule、Scheduled Public Asset Discovery、Public Asset Candidate、Public Asset Evidence 和候选晋升流程。FOFA、Quake、Shodan 的搜索结果先进入候选池；用户确认归属并晋升后才成为 Managed Asset。资产页不直接创建 Scan，而是基于选中的 Managed Assets 生成 Scan Prompt Draft 并跳转到 Session，由用户发送确认后进入现有 Orchestrator 和 Scan 流程。

2. **White-Box Workspace**：在主导航新增独立入口，上传 Source Package 后异步创建 White-Box Assessment。系统只做静态源码分析，不执行上传代码、不安装依赖、不启动服务。Analyzer Adapter 为首批 Java/Spring、JavaScript/TypeScript/Node.js、Python Web 框架提供高置信源码证据链；其它语言仍可上传，但只能产出通用分析和低/中置信线索。White-Box Findings 存在 CMDB 的独立白盒表中，不进入 confirmed Vulnerability，除非经 Document-Guided Verification 或人工流程 promoted。

## User Stories

1. As a security operator, I want to create an Organization Scope with only a required organization name, so that I can start public asset discovery without collecting every ownership clue upfront.
2. As a security operator, I want to optionally add aliases, root domains, ICP subjects, certificate subjects, ASNs, IP ranges, include terms, and exclude terms to an Organization Scope, so that discovery precision improves over time.
3. As a security operator, I want the system to generate default Asset Search Rules from an Organization Scope name, so that the first discovery setup is quick.
4. As a security operator, I want to edit Asset Search Rules per External Asset Search Source, so that FOFA, Quake, and Shodan can use source-specific query syntax.
5. As a security operator, I want to disable noisy Asset Search Rules, so that recurring discovery stops producing known false positives.
6. As a security operator, I want to annotate Asset Search Rules, so that future reviewers understand why a rule exists.
7. As a platform administrator, I want to configure External Asset Search Credentials globally per source, so that API keys are not duplicated in Organization Scopes or rules.
8. As a platform administrator, I want FOFA, Quake, and Shodan to be canonical source names, so that aliases or misspellings do not create inconsistent data.
9. As a security operator, I want to schedule public asset discovery every 4, 8, or 12 hours, so that candidate assets stay fresh without arbitrary high-frequency polling.
10. As a security operator, I want Scheduled Public Asset Discovery to perform only passive external search, so that it never runs port scans, vulnerability scans, weak-password checks, or PoC verification automatically.
11. As a security operator, I want source-returned ip:port, URLs, titles, banners, protocols, and certificate data stored as Public Asset Evidence, so that I can review why a candidate was discovered.
12. As a security operator, I want Public Asset Candidates deduplicated by Organization Scope and normalized host/domain, so that repeated cross-source matches merge evidence instead of cluttering the review queue.
13. As a security operator, I want the same host/domain to remain separate across Organization Scopes, so that ownership review remains scope-specific.
14. As a security operator, I want Public Asset Candidate statuses of unreviewed, promoted, and dismissed, so that candidate review is simple and auditable.
15. As a security operator, I want dismissed candidates to remain dismissed when rediscovered, so that known false positives do not repeatedly interrupt review.
16. As a security operator, I want promoted candidates to retain Public Asset Evidence, so that discovery-source audit remains available in Managed Asset detail.
17. As a security operator, I want source-returned ports to remain evidence until active scanning observes them, so that Services are created only by active scan evidence.
18. As a security operator, I want Public Asset Candidates visually separated from Managed Assets, so that uncertain ownership is not confused with managed inventory.
19. As a security operator, I want to promote only reviewed Public Asset Candidates into Managed Assets, so that active scanning is limited to managed inventory.
20. As a security operator, I want to generate a Scan Prompt Draft from selected Managed Assets, so that I can move quickly from asset review into the existing Session workflow.
21. As a security operator, I want the Scan Prompt Draft to omit repeated authorization-confirmation wording, so that the generated prompt is concise.
22. As a security operator, I want a Scan Prompt Draft to avoid creating a Scan until I send it in a Session, so that asset pages do not become automatic scan launchers.
23. As a security operator, I want notifications only when new unreviewed Public Asset Candidates are created, so that evidence refreshes and dismissed rediscoveries do not produce noise.
24. As a security operator, I want public asset notifications grouped by Organization Scope, so that I can triage new candidates efficiently.
25. As a white-box reviewer, I want a dedicated White-Box Workspace outside the existing Session page, so that source-code assessment is not mixed with conversational VAPT scanning.
26. As a white-box reviewer, I want to upload a Source Package, so that I can assess code without giving the system Git credentials or repository access.
27. As a white-box reviewer, I want `.zip` and `.tar.gz` support, so that common source delivery formats work.
28. As a platform operator, I want Source Package limits of 200 MB compressed and 1 GB extracted, so that uploads cannot exhaust local storage.
29. As a platform operator, I want unsafe archives rejected, so that encrypted packages, path traversal, absolute paths, and symlink escapes cannot compromise the host.
30. As a white-box reviewer, I want dependency/vendor/build directories skipped by default, so that analysis focuses on project source rather than generated or third-party code.
31. As a platform operator, I want uploaded source treated as untrusted, so that the system never executes project code, installs dependencies, runs tests, or starts services in MVP.
32. As a white-box reviewer, I want White-Box Assessments to run asynchronously, so that large source packages can be analyzed without blocking upload requests.
33. As a white-box reviewer, I want lifecycle states of queued, unpacking, analyzing, generating_docs, completed, failed, and cancelled, so that I can understand assessment progress.
34. As a white-box reviewer, I want assessment completion notifications with finding counts and confidence distribution, so that I know when review is ready.
35. As a white-box reviewer, I want task-level failure and cancellation notifications, so that I can act on broken or stopped assessments.
36. As a white-box reviewer, I want White-Box Findings separate from confirmed Vulnerabilities, so that source-level findings do not inflate runtime vulnerability metrics.
37. As a white-box reviewer, I want White-Box Finding statuses of open, needs_review, confirmed, dismissed, and promoted, so that source review and runtime verification have separate states.
38. As a white-box reviewer, I want confirmed White-Box Findings to mean source-level acceptance only, so that they are not mistaken for runtime-verified Vulnerabilities.
39. As a white-box reviewer, I want promoted White-Box Findings to link to confirmed Vulnerabilities after verification or manual promotion, so that validated source issues can enter existing vulnerability reporting.
40. As a white-box reviewer, I want White-Box Evidence stored as structured data, so that findings remain grounded in parser/analyzer evidence rather than model summaries.
41. As a white-box reviewer, I want Reproduction Documents rendered from White-Box Evidence, so that Markdown output is useful but not the fact source.
42. As a white-box reviewer, I want a fixed Reproduction Document Template, so that generated Markdown is consistent, reviewable, and consumable by Document-Guided Verification.
43. As a white-box reviewer, I want Reproduction Documents to include file paths, line numbers, entry points, sources, sinks, sanitizers, data-flow paths, prerequisites, request samples or trigger steps, expected behavior, remediation, analyzer evidence ID, and generation time, so that later verification is grounded.
44. As a white-box reviewer, I want Analyzer Adapters for Java/Spring, JavaScript/TypeScript/Node.js, and Python Web frameworks, so that high-confidence findings include real source-to-sink evidence.
45. As a white-box reviewer, I want uploads for unsupported languages to still run generic analysis, so that I can get low/medium-confidence review hints without blocking the workflow.
46. As a white-box reviewer, I want high-confidence findings only when an Analyzer Adapter has evidence, so that the model cannot invent vulnerabilities.
47. As a white-box reviewer, I want findings deduplicated within an assessment, so that multiple rules pointing to the same source-to-sink path produce one consolidated finding.
48. As a white-box reviewer, I want findings not deduplicated across different assessments, so that source version differences do not hide regressions.
49. As a white-box reviewer, I want severity to use the same vocabulary as confirmed Vulnerabilities, so that UI and reports remain consistent.
50. As a white-box reviewer, I want severity calculated from white-box evidence quality and impact, so that static rule defaults do not overstate or understate risk.
51. As a white-box reviewer, I want to purge uploaded archives and extracted workspaces while keeping findings and documents, so that sensitive source can be removed after review.
52. As a white-box reviewer, I want to keep source material by default until deletion or purge, so that reviewers can audit evidence when needed.
53. As a security tester, I want to start Document-Guided Verification from a Reproduction Document, so that runtime checks follow the source-backed reproduction path.
54. As a security tester, I want Document-Guided Verification to require an explicit runtime target when needed, so that verification does not silently attack unknown systems.
55. As a security tester, I want live-target verification to route through existing Scan authorization and high-risk safety behavior, so that current operational guardrails remain effective.

## Implementation Decisions

- Use the existing domain vocabulary from `CONTEXT.md`: Organization Scope, Public Asset Candidate, Public Asset Evidence, Scheduled Public Asset Discovery, Asset Search Rule, Managed Asset, Scan Prompt Draft, White-Box Assessment, White-Box Finding, White-Box Evidence, Analyzer Adapter, Reproduction Document, Document-Guided Verification, and White-Box Workspace.
- Public asset discovery belongs in the asset/CMDB area as Public Asset Discovery Workspace, not in Session and not in White-Box Workspace.
- White-Box Assessment gets a top-level White-Box Workspace and does not run inside the existing Session conversation page.
- Public asset discovery is passive only. It queries External Asset Search Sources and updates Public Asset Candidates and Public Asset Evidence. It must not run active probing.
- External Asset Search Source canonical values are FOFA, Quake, and Shodan.
- External Asset Search Credentials are platform-level per source. Organization Scopes and Asset Search Rules do not store credentials.
- Organization Scope requires only a name. All ownership evidence fields are optional.
- Asset Search Rules are source-specific, editable, disableable, and traceable.
- Scheduled Public Asset Discovery supports daily cadence options of every 4, 8, or 12 hours.
- Public Asset Candidates are deduplicated by Organization Scope and normalized host/domain. Evidence is merged across sources and rules.
- Public Asset Candidate Status values are unreviewed, promoted, and dismissed.
- Dismissed candidates stay dismissed on rediscovery while evidence and last-seen metadata refresh.
- Promoting a Public Asset Candidate creates or updates a Managed Asset and retains Public Asset Evidence for audit.
- Source-returned ports, URLs, titles, banners, protocols, and certificates remain Public Asset Evidence until active scanning creates Services.
- Asset workspace scan action creates a Scan Prompt Draft and redirects to Session. It does not create a Scan directly.
- Scan Prompt Drafts list selected Managed Assets and intended scan request, but do not repeat an authorization-confirmation statement.
- Public Asset Discovery Notifications are emitted only for newly created unreviewed candidates and are grouped by Organization Scope.
- White-Box Assessment uses an independent task model and lifecycle. It must not reuse Scan rows, Scan status transitions, or Scan dashboard counts.
- White-Box Assessment and White-Box Findings are persisted in the CMDB using white-box-specific tables.
- White-Box Assessment runs asynchronously after upload.
- Source Package input supports only `.zip` and `.tar.gz` in MVP.
- Source Package limits are 200 MB compressed and 1 GB extracted.
- Unsafe archives are rejected before extraction. Dependency/vendor/build directories and large binaries are skipped by default.
- MVP white-box analysis is static only. Uploaded code is not executed, dependencies are not installed, tests are not run, and services are not started.
- White-Box Finding Status values are open, needs_review, confirmed, dismissed, and promoted.
- Confirmed White-Box Finding means source-level acceptance. Promoted means associated with or promoted to a confirmed Vulnerability after runtime verification or manual promotion.
- White-Box Findings do not count in confirmed vulnerability totals unless promoted to confirmed Vulnerabilities.
- White-Box Evidence is the source of truth. Reproduction Documents are Markdown artifacts rendered from structured evidence.
- Reproduction Documents must follow a fixed template so they are both human-readable and consumable by Document-Guided Verification.
- Analyzer Adapter is the deep module boundary for language/framework-specific parsing, entry-point extraction, source/sink/sanitizer rules, data-flow evidence, and line references.
- First Analyzer Adapters are Java/Spring MVC/Spring Boot, JavaScript/TypeScript/Node.js/Express/NestJS, and Python/FastAPI/Django/Flask.
- Unsupported languages are accepted for generic analysis, but high-confidence White-Box Findings require Analyzer Adapter evidence.
- White-Box Findings are deduplicated within a White-Box Assessment by analyzer, vulnerability type, primary file, primary sink line, and normalized source-to-sink path. They are not automatically deduplicated across assessments.
- White-Box Finding severity uses the existing severity vocabulary but is scored from white-box evidence quality, vulnerability type, data-flow completeness, authorization boundary impact, sensitive data or dangerous operation impact, sanitizer absence, and confidence.
- Source archives and extracted workspaces are retained by default. Users can purge source material while keeping findings and Reproduction Documents.
- Document-Guided Verification is explicit user action. When live runtime targets are required, it routes through existing Scan behavior and high-risk guardrails.
- ADR-0001 records that White-Box Assessment uses an independent lifecycle instead of Scan.
- ADR-0002 records that structured White-Box Evidence is the source of truth and Reproduction Documents are artifacts.

Major modules to build or modify:

- Public asset discovery domain service: owns Organization Scopes, Asset Search Rules, candidate deduplication, evidence merging, candidate status changes, and promotion into Managed Assets.
- External asset search integration layer: provides a stable interface for FOFA, Quake, and Shodan clients, credential lookup, source normalization, result normalization, pagination, error handling, and rate-limit behavior.
- Scheduled discovery runner: executes enabled rules on the selected cadence, updates candidates/evidence, and emits grouped notifications.
- Candidate promotion service: converts reviewed candidates into Managed Assets while preserving Public Asset Evidence.
- Scan Prompt Draft builder: creates concise natural-language prompts from selected Managed Assets and redirects into Session without creating a Scan directly.
- White-box assessment service: owns upload records, lifecycle transitions, cancellation, retention, purge, and task-level notifications.
- Source package intake module: validates archive type/size, rejects unsafe archives, extracts into a controlled workspace, skips excluded directories/files, and records package metadata.
- Analyzer Adapter interface and registry: exposes a stable adapter contract and selects supported language/framework adapters.
- Language/framework Analyzer Adapters: Java/Spring, Node/Express/Nest, and Python/FastAPI/Django/Flask.
- White-box evidence and finding service: persists structured evidence, deduplicates findings, computes status/severity/confidence, and supports review transitions.
- Reproduction document renderer: renders fixed-template Markdown from White-Box Evidence and records artifacts.
- Document-guided verification bridge: reads Reproduction Documents or structured evidence and prepares an explicit verification flow through existing Scan behavior when runtime targets are supplied.
- Frontend Public Asset Discovery Workspace: Organization Scopes, rules, schedules, candidates, evidence review, promotion, and Managed Asset prompt drafting.
- Frontend White-Box Workspace: assessment list, upload/create assessment, lifecycle detail, finding review, Reproduction Document view/download, source purge, and Document-Guided Verification.

API and persistence contracts:

- Add CRUD endpoints for Organization Scopes, Asset Search Rules, schedules, candidates, evidence, candidate status changes, and promotion.
- Add platform-level configuration endpoints or settings for External Asset Search Credentials.
- Add upload/create endpoints for White-Box Assessment and read endpoints for lifecycle, findings, evidence, artifacts, status updates, purge, and document-guided verification.
- Add CMDB tables for public asset discovery objects and white-box objects without reusing existing Scan or confirmed Vulnerability rows for white-box tasks.
- Add notification payloads for Public Asset Discovery Notification and White-Box Assessment Notification.

## Testing Decisions

- Tests should exercise external behavior and domain contracts, not parser internals or UI implementation details.
- Public asset discovery tests should verify candidate deduplication, evidence merging, dismissed rediscovery behavior, promotion into Managed Assets, and that source-returned ports do not become Services before active scanning.
- Search integration tests should use fake FOFA/Quake/Shodan clients and assert normalized results, credential lookup behavior, source names, pagination/error handling, and rate-limit-safe failure behavior.
- Scheduled discovery tests should verify 4/8/12-hour cadence configuration, execution of enabled rules only, passive-only behavior, and grouped notifications for newly created unreviewed candidates.
- Scan Prompt Draft tests should verify that only Managed Assets can be included, that no Scan row is created, and that generated wording does not include repeated authorization-confirmation text.
- Source package intake tests should cover allowed formats, size limits, encrypted archive rejection, path traversal rejection, absolute path rejection, symlink escape rejection, skipped directories, and large binary skipping.
- White-box lifecycle tests should verify queued, unpacking, analyzing, generating_docs, completed, failed, and cancelled transitions without using Scan state.
- White-box persistence tests should verify that assessments and findings use independent CMDB tables and do not affect confirmed vulnerability totals.
- Analyzer Adapter tests should use small fixture projects for Java/Spring, Node/Express/Nest, and Python Web frameworks and assert entry-point extraction, source/sink/sanitizer evidence, file/line references, and confidence gating.
- White-Box Finding tests should verify deduplication within one assessment, no cross-assessment deduplication, status transitions, severity scoring inputs, and promotion linkage.
- Reproduction Document tests should verify template completeness and deterministic rendering from structured White-Box Evidence.
- Document-Guided Verification tests should verify explicit user trigger, runtime target requirement, and integration with existing Scan/high-risk behavior.
- Frontend tests should verify separate navigation for Public Asset Discovery Workspace and White-Box Workspace, candidate/managed separation, upload flow, lifecycle display, finding review, source purge, Markdown view/download, and prompt-draft-to-Session behavior.
- Prior test patterns to reuse include existing CMDB repository tests, API/WebSocket route tests, skill handler tests, and frontend dashboard/component behavior tests.

## Out of Scope

- Direct active scanning of Public Asset Candidates before promotion.
- Automatically running port scans, vulnerability scans, weak-password checks, PoC verification, or exploitation from Scheduled Public Asset Discovery.
- Arbitrary cron expressions or sub-4-hour public asset discovery polling.
- Per-Organization Scope or per-rule storage of FOFA/Quake/Shodan credentials.
- Git repository cloning, Git credentials, branch selection, or local path white-box input.
- Executing uploaded source code, installing dependencies, running project tests, starting project services, or building runtime sandboxes in MVP.
- High-confidence Analyzer Adapter support for PHP, Go, frontend-only projects, mobile apps, C/C++, or other stacks beyond the first adapter set.
- Automatically promoting White-Box Findings into confirmed Vulnerabilities without runtime verification or manual promotion.
- Automatically launching Document-Guided Verification after White-Box Assessment completion.
- Replacing existing vuln_detec, vuln_scan, report generation, Scan lifecycle, or high-risk confirmation behavior.

## Further Notes

- Triage label: needs-triage.
- This PRD is grounded in the updated domain glossary in `CONTEXT.md`.
- ADR-0001 and ADR-0002 should be treated as constraints for implementation planning.
- The implementation should prefer deep, independently testable modules for external source normalization, source package intake, Analyzer Adapter execution, White-Box Evidence persistence, and Reproduction Document rendering.
