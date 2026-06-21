# Threat Intelligence Module as an Independent APT-Centric Workspace

The threat intelligence module serves a fundamentally different purpose from the conversational VAPT pipeline: it consumes, stores, and presents open-source threat intelligence focused on the Chinese transportation and maritime industries, rather than actively probing targets. We give it an independent SQLite store (`threat_intel.sqlite3`), its own Workflow-scheduled ingestion jobs, dedicated API routes, and a top-level frontend navigation entry, rather than extending the CMDB or nesting under the existing Dashboard.

## Context

The VAPT pipeline produces scan-scoped findings tied to specific assets and sessions. Threat intelligence is a persistent, cross-scan knowledge base of adversaries, their infrastructure, and known vulnerabilities. Mixing the two would conflate scan lifecycle state with long-lived intelligence records and make CMDB migration increasingly complex.

## Decision

- **Independent store**: `threat_intel.sqlite3` with its own ORM models, repository, and migrations. Not an extension of the CMDB or `detection_results.db`.
- **APT-centric star model**: **Threat Groups** are the central entity. Attack IPs (C2 infrastructure), malware families, and exploited vulnerabilities all associate to a Threat Group. Maritime events are the only standalone dimension.
- **Data sources**: MITRE ATT&CK Groups (base corpus) + AlienVault OTX (industry enrichment) + abuse.ch ThreatFox/Feodo/MalwareBazaar (C2 & malware) + CISA KEV + NVD (CVSS >= 7.0) + Chinese APT alias mapping. Chinese APT names (e.g., 海莲花, 蔓灵花) are maintained in a separate alias table.
- **Industry filter**: Relevance to the Chinese transportation/maritime sector. Supply chain vulnerabilities are identified via CPE matching against a maintained **Industry CPE List**, not via supply-chain-attack attribution.
- **Scheduled ingestion**: Workflow jobs on a configurable cadence. LLM-based extraction replaces dedicated crawlers for unstructured maritime sources (IMO GISIS HTML, UKMTO/ReCAAP PDFs).
- **Frontend**: Top-level navigation "威胁情报" → Dashboard overview (5 summary cards) → drill-down detail views per dimension.
- **User control**: Watchlist for priority monitoring of specific Threat Groups.

## Consequences

- Threat intelligence data never enters CMDB scan/vulnerability tables; the two systems communicate only at the UI level (e.g., a scanned asset may show a badge if its vulnerability matches a Threat Vulnerability).
- The Industry CPE List and Chinese APT alias table are configuration data that need initial seeding and periodic maintenance.
- LLM extraction for maritime sources introduces non-deterministic parsing quality; results should include source URLs for human verification.
- Workflow scheduling means intelligence freshness depends on job cadence, not real-time events.
