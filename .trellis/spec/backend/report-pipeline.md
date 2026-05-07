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

---

## Origin

Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"Report" + ADR-005 (Markdown-canonical pipeline).
