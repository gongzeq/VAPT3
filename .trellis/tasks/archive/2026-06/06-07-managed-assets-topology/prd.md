# 纳管资产、资产风险拓扑与候选漏洞

## Problem Statement

当前系统已经能在扫描过程中通过实时资产流展示扫描发现，也能从 CMDB 聚合安全大屏指标，但“实时发现”和“长期治理”之间缺少清晰边界。测试阶段不希望所有扫描结果都自动落盘；正式治理阶段又需要把扫描发现的资产纳入 CMDB，让安全大屏、资产聚类、资产分布、拓扑和后续漏洞库匹配都围绕纳管资产运行。

同时，现有 CMDB 资产去重以扫描为中心，容易让同一个主机或域名在多次扫描后出现重复资产。端口和服务状态也需要保留历史语义：如果后续扫描确认端口关闭，不能删除服务记录，而应更新状态。中间件版本、漏洞库匹配、候选漏洞和已确认漏洞也需要明确分层，避免把“版本可能受影响”误计为“已确认漏洞”，更不能因为版本命中就自动发起漏洞扫描。

最后，安全大屏需要新增资产风险拓扑。它应展示纳管资产、服务、已确认漏洞和候选漏洞之间的关系，但不能伪装成物理网络链路拓扑。用户还需要能自定义拓扑中心点，并让影响资产更多的漏洞节点更醒目。

## Solution

新增会话级 **Asset Auto-Management** 开关，放在会话页面框中，默认关闭。关闭时，扫描发现只保留在会话实时资产流中，不进入 CMDB、安全大屏、资产风险拓扑或漏洞库匹配视图。开启后，该 Session 内的 Scan 发现可进入 CMDB，成为 **Managed Asset**，并参与安全大屏资产分布、资产聚类、资产风险拓扑和被动漏洞库匹配。

CMDB 以真实主机或域名为 **Asset** 主体，同一资产跨扫描只保留一条记录；端口、服务、中间件、URL、指纹和漏洞都作为资产关联信息。重复扫描不能创建重复资产，也不能覆盖用户手工编辑的治理标签。服务状态支持 open / filtered / closed；只有当本次扫描明确覆盖了对应端口时，才允许把服务标记为 closed 或 filtered。

安全大屏的资产分布采用中文业务分类：业务、智能体、OA、中间件、支撑、内网、其他。资产聚类优先按业务系统聚类，没有业务系统归属的资产归入“其他”，用户可后续手工修改标签。

新增 **Asset Risk Topology**，默认展示全部 Managed Assets，并提供业务系统、网段、资产类型、漏洞身份、候选/已确认状态和最近扫描等筛选。拓扑是 CMDB 派生视图，不维护单独拓扑表；从 Asset、Service、已确认 Vulnerability 和 Vulnerability Candidate 聚合生成。用户可以把任意拓扑节点设为 **Topology Focus**，中心点只影响布局，不改变 CMDB 关系。漏洞节点按受影响唯一 Managed Asset 数量缩放；候选漏洞和已确认漏洞都可以展示，但必须视觉区分。

新增 **Vulnerability Candidate** 概念。服务指纹与漏洞库进行被动匹配后生成候选漏洞，候选漏洞持久化但不计入已确认漏洞总数、风险趋势、高危告警或正式报告。候选状态流转为 candidate → verified / dismissed。系统不自动发起漏洞扫描；只有用户明确请求验证时才执行主动检测，验证命中后生成 confirmed vulnerability。

## User Stories

1. As a security operator, I want an Asset Auto-Management switch in the Session page, so that I can decide whether the current scanning work should update long-term governance data.
2. As a security operator, I want Asset Auto-Management to be off by default, so that test scans do not pollute the CMDB or dashboard.
3. As a security operator, I want enabling Asset Auto-Management to affect the current Session's scans, so that discoveries from that work can become Managed Assets.
4. As a security operator, I want disabling Asset Auto-Management to keep discoveries transient, so that ad hoc testing does not update Managed Assets.
5. As a security operator, I want the UI state to reflect the real backend state, so that a disabled switch cannot still write CMDB data in the background.
6. As a security operator, I want repeated discoveries of the same host or domain to resolve to one Asset, so that dashboard counts are not inflated by repeated scans.
7. As a security operator, I want Asset identity to be based on normalized IP, hostname, or target, so that the same real asset is recognized across Scans.
8. As a security operator, I want ports and services to belong to an Asset, so that a host with many ports does not become many fake assets.
9. As a security operator, I want middleware product and version information stored on Service fingerprints, so that one Asset can have many middleware signals.
10. As a security operator, I want a later scan that confirms a port closed to mark the Service closed, so that I preserve state history instead of losing evidence.
11. As a security operator, I want partial scans to leave uncovered ports unchanged, so that an omitted port is not mistaken for a closed port.
12. As a security operator, I want manually edited Asset tags to survive future scans, so that my business-system and type corrections are not overwritten.
13. As a security operator, I want assets without business-system attribution to appear under “其他”, so that all Managed Assets remain visible.
14. As a security operator, I want to manually edit Asset tags later, so that unknown or incorrectly classified assets can be cleaned up without rescanning.
15. As a security operator, I want security dashboard asset distribution to use business categories, so that the dashboard reflects operations language rather than technical enum labels.
16. As a security operator, I want asset clustering to use Managed Assets, so that the cluster chart represents the governed asset corpus.
17. As a security operator, I want all Managed Assets to appear in the Asset Risk Topology by default, so that the topology is a governance view, not just a latest-scan view.
18. As a security operator, I want to filter the Asset Risk Topology by business system, subnet, Asset Type, vulnerability identity, candidate status, and recent Scan, so that I can investigate focused areas.
19. As a security operator, I want to choose any topology node as the Topology Focus, so that I can explore relationships around a specific asset, service, vulnerability, or group.
20. As a security operator, I want vulnerability nodes to grow when they affect more unique Managed Assets, so that high-blast-radius issues stand out.
21. As a security operator, I want confirmed vulnerabilities and Vulnerability Candidates to look different, so that possible risk is not confused with verified risk.
22. As a security operator, I want Asset Risk Topology to show asset-service-vulnerability relationships, so that I understand risk relationships without implying physical network links.
23. As a security operator, I want topology updates to reflect CMDB changes, so that new assets, service state changes, middleware versions, and vulnerability state changes are visible without maintaining a separate topology model.
24. As a security operator, I want service fingerprints to be matched against a vulnerability database, so that outdated middleware can be identified as a candidate risk.
25. As a security operator, I want version-based matches to create Vulnerability Candidates, so that I can see what may need verification.
26. As a security operator, I want the system not to auto-run vulnerability scans from version matches, so that passive matching does not become active probing without intent.
27. As a security operator, I want to explicitly trigger verification for a Vulnerability Candidate, so that I control when active scanning is performed.
28. As a security operator, I want verification failures to keep a candidate as candidate with failure evidence, so that temporary scan errors do not dismiss possible risk.
29. As a security operator, I want successful verification to promote a candidate to a confirmed vulnerability, so that confirmed dashboards and reports only include validated findings.
30. As a security operator, I want dismissed candidates to be hidden from default risk views but preserved in history, so that false positives do not distract daily operations.
31. As a security operator, I want CVE and CNVD aliases for the same issue to merge into one Vulnerability Identity, so that the topology does not duplicate the same vulnerability.
32. As a security operator, I want candidate and confirmed vulnerability statistics to be separate, so that executive dashboard KPIs remain trustworthy.
33. As a report consumer, I want formal reports to count confirmed vulnerabilities, so that reports do not overstate unverified version matches.
34. As a developer, I want the auto-management decision to be enforceable in the backend, so that frontend-only state cannot be bypassed by agent tools.
35. As a developer, I want asset ingestion logic isolated behind a small interface, so that auto-management, deduplication, tag preservation, and service-state rules can be unit tested.
36. As a developer, I want topology generation isolated as a pure graph builder, so that filters, node sizing, candidate styling metadata, and focus behavior can be tested without rendering React.
37. As a developer, I want vulnerability candidate matching isolated from active verification, so that passive matching can be safe, deterministic, and testable.
38. As a developer, I want dashboard aggregation to ignore candidates unless an endpoint explicitly asks for them, so that existing confirmed vulnerability KPIs do not regress.

## Implementation Decisions

- **Asset Auto-Management is session-scoped and default off.** There is no global config default. The switch lives in the Session page UI and controls whether scan discoveries in that Session can update the Managed Asset corpus.
- **Backend must enforce the switch.** The frontend button is not enough; the backend ingestion path must check the Session's auto-management state before writing CMDB data from scan discoveries.
- **When disabled, no scan discovery updates Managed Assets.** Discovered assets remain in the transient asset feed and do not update CMDB, safety dashboard, topology, or vulnerability matching.
- **Asset identity is cross-scan.** Asset upsert must identify the same real host or domain across Scans, preferring normalized IP, then normalized hostname/target.
- **Asset is host/domain level.** URL, endpoint, port, service, middleware, and fingerprint are associated observations, not separate Asset records.
- **Services preserve state.** A Service can be open, filtered, or closed. Closing is a state transition, not deletion. State changes require the latest scan to explicitly cover the port.
- **User tag edits are authoritative.** User-edited `system` and `type` tags must not be overwritten by automatic scan classification. Automatic classification may fill missing values.
- **Asset Type vocabulary is Chinese business vocabulary.** The canonical Asset Type set is 业务, 智能体, OA, 中间件, 支撑, 内网, 其他.
- **Unknown business-system attribution groups as 其他.** Assets without business-system attribution still appear in clustering and topology.
- **Middleware information lives on Service fingerprints.** Asset Type can classify an asset's primary role, but concrete middleware product/version belongs to the Service layer.
- **Vulnerability Identity merges aliases.** Prefer CVE identifiers, then CNVD identifiers, then normalized category/title fallback; aliases for the same issue are one logical identity.
- **Vulnerability Candidates are separate from confirmed vulnerabilities.** Candidates are persisted separately and excluded from confirmed vulnerability KPIs, trends, alerts, and report findings.
- **Candidate lifecycle is candidate / verified / dismissed.** Verification success creates or links a confirmed vulnerability. Verification failure leaves the candidate in candidate state with failure evidence.
- **No automatic vulnerability scanning from version matches.** Version matching is passive and produces candidates. Active verification only runs after an explicit user request.
- **Asset Risk Topology is a derived CMDB view.** It should be generated from Managed Assets, Services, confirmed vulnerabilities, and candidates on request. Do not add a topology table in the first implementation.
- **Topology default scope is all Managed Assets.** Recent Scan is a filter, not the default corpus.
- **Topology focus is layout state.** Any node can be the focus; focus does not change CMDB relationships.
- **Vulnerability node size uses affected unique Managed Asset count.** Duplicate scan hits must not inflate node size.
- **Confirmed and candidate nodes are visually distinct.** Confirmed vulnerabilities should appear stronger; candidates should be marked as pending verification.
- **Frontend topology should use the approved graph library.** The existing visualization whitelist allows a React-first graph library for asset/service/vulnerability topology; do not add a new graph dependency.
- **Deep modules to build or modify:**
  - Session auto-management state service: small API for reading/updating the current Session's auto-management state.
  - Managed asset ingestion service: normalizes discoveries, checks auto-management state, upserts assets/services, preserves manual tags, and applies service-state rules.
  - Asset identity resolver: normalizes IP/hostname/target and provides stable cross-scan keys.
  - Service state reconciler: updates open/filtered/closed only for ports explicitly covered by a Scan.
  - Vulnerability candidate matcher: passively converts service fingerprints into candidates.
  - Vulnerability candidate repository: persists candidate lifecycle independently from confirmed vulnerabilities.
  - Asset risk topology builder: converts CMDB rows into nodes, edges, sizes, statuses, and focus metadata.
  - Dashboard aggregation adapters: ensure asset distribution, cluster, and confirmed vulnerability metrics follow the new vocabularies and exclusions.
  - Session page control: renders the auto-management switch and syncs it to backend state.
  - Dashboard topology widget: renders the topology, filters, focus behavior, and candidate/confirmed visual distinction.

## Testing Decisions

- Tests should assert external behavior and data contracts, not internal helper call order.
- Auto-management tests should verify that disabled sessions do not write Managed Assets from scan discoveries and enabled sessions do.
- Ingestion tests should verify cross-scan Asset de-duplication, service upserts, closed/filtered state changes, and partial-scan non-updates.
- Tag tests should verify user-edited `system` and `type` tags survive automatic classification.
- Dashboard aggregation tests should verify Chinese Asset Type buckets, “其他” grouping for missing business-system attribution, and candidate exclusion from confirmed vulnerability metrics.
- Candidate tests should verify insert/upsert uniqueness by asset/service/vulnerability identity, lifecycle transitions, verification failure behavior, and verified promotion to confirmed vulnerability.
- Topology builder tests should verify default all-Managed-Assets scope, filters, node/edge shape, vulnerability node sizing by unique affected assets, focus metadata, and candidate/confirmed distinction.
- Frontend tests should verify the Session switch defaults off, updates backend state, survives refresh while the runtime state exists, and does not imply global config.
- Frontend topology tests should verify filters, focus selection, node sizing display, and distinct candidate/confirmed rendering using stable test fixtures.
- API tests should follow existing dashboard and asset-feed patterns: empty-state shape, actor scoping, invalid filter handling, and no SPA fallback for API routes.
- Existing tests around asset feed CMDB flushing must be revisited because auto-management disabled now blocks scan discovery writes.

## Out of Scope

- Do not implement automatic vulnerability scanning from version matches.
- Do not treat Vulnerability Candidates as confirmed findings in reports, alerts, trends, or KPI cards.
- Do not build a physical network topology or infer switch/router links from scan results.
- Do not add a persistent topology table in the first implementation.
- Do not add a global config default for Asset Auto-Management.
- Do not overwrite user-edited asset governance tags during re-scans.
- Do not delete Service rows when a port closes.
- Do not replace the existing transient asset feed; it remains the live collaboration channel.
- Do not add a new graph/chart dependency outside the visualization whitelist.
- Do not solve full RBAC or multi-user ownership beyond the existing actor reservation.

## Further Notes

- This PRD intentionally separates transient scan discoveries from Managed Assets. That boundary is the core behavior that makes test-stage scans safe while still supporting future production governance.
- Existing report-pipeline work introduced automatic CMDB flushes for some asset-feed kinds. This PRD changes the policy: those writes must be gated by Asset Auto-Management.
- Existing dashboard aggregation code already moved toward Chinese Asset Type buckets; related specs were updated to match the confirmed vocabulary.
- The existing CMDB schema needs migrations for cross-scan Asset identity, manual tag preservation metadata, candidate persistence, and any Scan-to-Session association required by the runtime.
- The Asset Risk Topology should be a dashboard view over CMDB data, not a new source of truth.
