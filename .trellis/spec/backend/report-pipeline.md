# Report Pipeline

> Defines how scan results become a deliverable report (Markdown / DOCX / PDF).
> Implementation: `secbot/skills/report-*` + `secbot/report/` rendering helpers.

---

## 1. Pipeline Stages

```
CMDB query  ──►  ReportModel  ──►  Markdown (canonical)  ──►  DOCX | PDF
              (Python dataclass)   (Jinja template)        (python-docx | weasyprint)
```

| Stage | Owner | Output |
|-------|-------|--------|
| Query | `secbot/report/builder.py::build_report_model(scan_id)` | `ReportModel` (typed) |
| Render Markdown | `report-markdown` skill | `.md` file under scan dir |
| Render DOCX | `report-docx` skill | `.docx` via python-docx, consumes Markdown AST |
| Render PDF | `report-pdf` skill | `.pdf` via weasyprint, consumes rendered HTML from Markdown |

Markdown is the **canonical** intermediate. DOCX / PDF MUST be derivable from the same Markdown — never query CMDB twice with formatting drift.

---

## 2. ReportModel Schema

```python
@dataclass(frozen=True)
class ReportModel:
    scan_id: str
    target: str
    started_at: datetime
    finished_at: datetime
    summary: ReportSummary           # severity counts, asset counts
    assets: list[ReportAsset]        # asset + nested services + vulns
    appendix: ReportAppendix         # raw_log_path references, scope opt-outs
```

- All datetimes UTC, formatted in templates with the user's locale.
- `summary.severity_counts` MUST be a `dict[Severity, int]` keyed by the 5 severity tokens defined in [theme-tokens.md §2](../frontend/theme-tokens.md#2-severity-palette). Adding a sixth severity requires updating both files.

---

## 3. Templates

- Location: `secbot/report/templates/`
- Engine: Jinja2, autoescape ON for HTML, OFF for Markdown.
- One template per output: `report.md.j2`, `report.html.j2` (PDF source), `report.docx.j2` is **not** Jinja — DOCX uses python-docx programmatically against `ReportModel`.
- All severity badges in HTML/PDF MUST use the `--severity-<level>` CSS variables from [theme-tokens.md](../frontend/theme-tokens.md#2-severity-palette). PDF inlines the variable values at render time so the printed PDF stays consistent with WebUI colors.

---

## 4. Output Location

```
~/.secbot/scans/<scan_id>/report/
├── report.md           # always produced
├── report.docx         # if user requested or default
├── report.pdf          # if user requested
└── assets/             # images, charts (PNG snapshots)
```

Files are immutable once written. A re-render produces a new `report-vN.{md,docx,pdf}` rather than overwriting.

---

## 5. Skill Wiring

Each report format is a separate skill so the Orchestrator can request them à la carte:

| Skill | risk_level | Inputs | Outputs |
|-------|------------|--------|---------|
| `report-markdown` | `low` | `scan_id` | `summary_json.report_path`, `raw_log_path` (none) |
| `report-docx` | `low` | `scan_id`, optional `template_id` | `summary_json.report_path` |
| `report-pdf` | `low` | `scan_id`, optional `template_id` | `summary_json.report_path` |

`risk_level=low` is mandatory — report skills MUST NOT touch external networks or shell out to scanners.

---

## 6. Failure Modes

| Failure | Behaviour |
|---------|-----------|
| Empty CMDB for `scan_id` | Skill returns `summary_json={"status":"empty","report_path":null}`, no file written. Orchestrator must inform the user. |
| Template render error | Skill raises `ReportRenderError`, NOT caught — Orchestrator surfaces a `tool_error` event. |
| weasyprint missing system dep (cairo / pango) | At startup, `secbot doctor` prints actionable hint; skill itself fails fast with `MissingDependencyError`. |

## 7. Scenario: Transient Asset Feed Fallback

### 1. Scope / Trigger

- Trigger: `report-html` is invoked for the current scan/session and the CMDB model is empty because Asset Auto-Management is disabled.
- Scope: current in-process `AssetFeed` only. This fallback is for rendering the current session's discoveries, not for promoting scan discoveries into Managed Assets.

### 2. Signatures

- Context binding: `bind_skill_context(scan_id, scan_dir, ..., asset_feed=<AssetFeed>)`.
- Report builder: `build_report_model_from_asset_entries(entries, *, scan_id, target=None) -> ReportModel`.
- `report-html` input may include optional `target: string`; when omitted, the builder infers target from feed payload URLs/hosts.

### 3. Contracts

- `report-html` MUST query CMDB first and use the CMDB model when it has assets.
- If the CMDB model is empty and an asset feed is bound, `report-html` reads `await asset_feed.to_dict_list()` and builds a normal `ReportModel`.
- The fallback MUST NOT insert `asset`, `service`, or `vulnerability` rows. It may still record `report_meta` after a successful render.
- Supported feed kinds: `url` creates/keeps the asset, `tech` enriches asset metadata, `port`/`service` create report services, `vuln` creates report findings.
- Severity/category values from free-form `asset_push(kind="vuln")` payloads are normalized into the standard report vocabularies.

### 4. Validation & Error Matrix

| Condition | Result |
|-----------|--------|
| CMDB has assets | Render from CMDB; ignore asset-feed fallback. |
| CMDB empty + bound asset feed has entries | Render HTML from asset-feed-derived model. |
| CMDB empty + no bound asset feed or empty feed | Return `status="empty"` with `report_path=null`. |
| Asset feed read raises | Log warning and continue as empty fallback. |
| Feed entry has invalid/non-object payload | Skip that entry. |

### 5. Good/Base/Bad Cases

- Good: WebSocket scan with Asset Auto-Management disabled pushes `url`, `tech`, and `vuln` entries; `report-html` generates `report.html` without CMDB asset rows.
- Base: A CMDB-backed scan exists; `report-html` renders the CMDB data exactly as before.
- Bad: Enabling report generation silently promotes transient discoveries into Managed Assets.

### 6. Tests Required

- Unit test for `build_report_model_from_asset_entries()` grouping host-level assets and normalizing vulnerability severity/category.
- Skill test where CMDB is empty but a bound `AssetFeed` has vuln entries; assert `status="ok"` and HTML contains findings.
- Persistence assertion: after fallback render, `list_assets(..., scan_id)` remains empty.

### 7. Wrong vs Correct

Wrong: Turn Asset Auto-Management on by default so `report-html` has CMDB rows.

Correct: Keep the CMDB ingestion gate default-off, and let `report-html` use the current session's read-only asset-feed snapshot as a render-only fallback.

---

## Origin

Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"Report" + ADR-005 (Markdown-canonical pipeline).
