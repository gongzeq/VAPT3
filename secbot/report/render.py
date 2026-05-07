"""Report render helpers: Markdown (canonical), HTML, DOCX, PDF.

Spec: `.trellis/spec/backend/report-pipeline.md` §3.

Markdown is the canonical format. HTML is derived from Markdown for PDF
rendering via WeasyPrint. DOCX is built programmatically from the
:class:`ReportModel` because python-docx has no native Markdown ingest.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from secbot.report.builder import ReportModel, ReportRenderError, SEVERITY_ORDER

if TYPE_CHECKING:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _fmt_dt(dt) -> str:
    return dt.isoformat() if dt else "—"


def render_markdown(model: ReportModel) -> str:
    """Render *model* to Markdown (canonical)."""
    out: list[str] = []
    out.append(f"# Security Scan Report")
    out.append("")
    out.append(f"- **Scan ID**: `{model.scan_id}`")
    out.append(f"- **Target**: {model.target}")
    out.append(f"- **Started**: {_fmt_dt(model.started_at)}")
    out.append(f"- **Finished**: {_fmt_dt(model.finished_at)}")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"- Assets: **{model.summary.asset_count}**")
    out.append(f"- Services: **{model.summary.service_count}**")
    out.append(f"- Findings: **{model.summary.finding_count}**")
    out.append("")
    out.append("| Severity | Count |")
    out.append("|---|---|")
    for sev in SEVERITY_ORDER:
        out.append(f"| {sev} | {model.summary.severity_counts.get(sev, 0)} |")
    out.append("")

    if model.is_empty():
        out.append("_No assets were recorded for this scan._")
        out.append("")
    else:
        out.append("## Assets")
        out.append("")
        for a in model.assets:
            label = a.hostname or a.ip or a.target
            out.append(f"### {label}")
            out.append("")
            out.append(f"- Target: `{a.target}`")
            if a.ip:
                out.append(f"- IP: `{a.ip}`")
            if a.hostname:
                out.append(f"- Hostname: {a.hostname}")
            if a.os_guess:
                out.append(f"- OS guess: {a.os_guess}")
            out.append("")

            if a.services:
                out.append("#### Open services")
                out.append("")
                out.append("| Port | Proto | Service | Product | Version |")
                out.append("|---|---|---|---|---|")
                for s in a.services:
                    out.append(
                        f"| {s.port} | {s.protocol} | {s.service or '—'} | "
                        f"{s.product or '—'} | {s.version or '—'} |"
                    )
                out.append("")

            if a.findings:
                out.append("#### Findings")
                out.append("")
                out.append("| Severity | Category | Title | CVE | Discovered by |")
                out.append("|---|---|---|---|---|")
                for f in a.findings:
                    out.append(
                        f"| {f.severity} | {f.category} | {f.title} | "
                        f"{f.cve_id or '—'} | {f.discovered_by} |"
                    )
                out.append("")

    if model.appendix.raw_log_paths:
        out.append("## Appendix: raw logs")
        out.append("")
        for p in model.appendix.raw_log_paths:
            out.append(f"- `{p}`")
        out.append("")

    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# HTML (for PDF)
# ---------------------------------------------------------------------------


def render_html(model: ReportModel) -> str:
    """Render an HTML document suitable for WeasyPrint PDF conversion.

    Inlines the severity color tokens so the printed PDF matches the WebUI.
    """
    css = """
    body { font-family: -apple-system, Segoe UI, sans-serif; color: #0F172A; }
    h1, h2, h3 { color: #1E3A8A; }
    table { border-collapse: collapse; margin-bottom: 1.5rem; }
    th, td { border: 1px solid #E2E8F0; padding: 6px 10px; font-size: 13px; }
    .badge { padding: 2px 8px; border-radius: 4px; color: #fff; font-size: 12px; }
    .sev-critical { background: #991B1B; }
    .sev-high { background: #DC2626; }
    .sev-medium { background: #D97706; }
    .sev-low { background: #2563EB; }
    .sev-info { background: #475569; }
    """
    lines: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset=\"utf-8\">",
        "<title>Security Scan Report</title>",
        f"<style>{css}</style></head><body>",
        "<h1>Security Scan Report</h1>",
        "<ul>",
        f"<li><strong>Scan ID:</strong> <code>{model.scan_id}</code></li>",
        f"<li><strong>Target:</strong> {model.target}</li>",
        f"<li><strong>Started:</strong> {_fmt_dt(model.started_at)}</li>",
        f"<li><strong>Finished:</strong> {_fmt_dt(model.finished_at)}</li>",
        "</ul>",
        "<h2>Summary</h2>",
        "<table><thead><tr><th>Severity</th><th>Count</th></tr></thead><tbody>",
    ]
    for sev in SEVERITY_ORDER:
        count = model.summary.severity_counts.get(sev, 0)
        lines.append(
            f"<tr><td><span class=\"badge sev-{sev}\">{sev}</span></td>"
            f"<td>{count}</td></tr>"
        )
    lines.append("</tbody></table>")

    for a in model.assets:
        label = a.hostname or a.ip or a.target
        lines.append(f"<h3>{label}</h3>")
        lines.append("<ul>")
        lines.append(f"<li>Target: <code>{a.target}</code></li>")
        if a.ip:
            lines.append(f"<li>IP: <code>{a.ip}</code></li>")
        if a.os_guess:
            lines.append(f"<li>OS guess: {a.os_guess}</li>")
        lines.append("</ul>")
        if a.findings:
            lines.append("<table><thead><tr><th>Severity</th><th>Title</th>"
                         "<th>CVE</th><th>Discovered by</th></tr></thead><tbody>")
            for f in a.findings:
                lines.append(
                    f"<tr><td><span class=\"badge sev-{f.severity}\">{f.severity}</span></td>"
                    f"<td>{f.title}</td><td>{f.cve_id or '—'}</td>"
                    f"<td>{f.discovered_by}</td></tr>"
                )
            lines.append("</tbody></table>")
    lines.append("</body></html>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PDF (WeasyPrint)
# ---------------------------------------------------------------------------


def render_pdf(model: ReportModel, out_path: Path) -> Path:
    """Render *model* as PDF via WeasyPrint.

    Raises :class:`ReportRenderError` if the optional ``weasyprint`` dep is
    not installed or its system libraries (cairo/pango) are missing.
    """
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError as exc:
        raise ReportRenderError(
            "weasyprint is not installed; run `pip install weasyprint` "
            "(requires cairo/pango system libraries)"
        ) from exc
    except OSError as exc:  # pragma: no cover - env specific
        raise ReportRenderError(
            f"weasyprint failed to load system libs: {exc}"
        ) from exc

    html = render_html(model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# DOCX (python-docx)
# ---------------------------------------------------------------------------


def render_docx(model: ReportModel, out_path: Path) -> Path:
    """Render *model* as DOCX via python-docx."""
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise ReportRenderError(
            "python-docx is not installed; run `pip install python-docx`"
        ) from exc

    doc = Document()
    doc.add_heading("Security Scan Report", level=1)
    p = doc.add_paragraph()
    p.add_run("Scan ID: ").bold = True
    p.add_run(model.scan_id)
    p = doc.add_paragraph()
    p.add_run("Target: ").bold = True
    p.add_run(model.target)
    doc.add_paragraph(f"Started: {_fmt_dt(model.started_at)}")
    doc.add_paragraph(f"Finished: {_fmt_dt(model.finished_at)}")

    doc.add_heading("Summary", level=2)
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Light List Accent 1"
    hdr = tbl.rows[0].cells
    hdr[0].text = "Severity"
    hdr[1].text = "Count"
    for sev in SEVERITY_ORDER:
        row = tbl.add_row().cells
        row[0].text = sev
        row[1].text = str(model.summary.severity_counts.get(sev, 0))

    if model.is_empty():
        doc.add_paragraph("No assets were recorded for this scan.")
    else:
        doc.add_heading("Assets", level=2)
        for a in model.assets:
            doc.add_heading(a.hostname or a.ip or a.target, level=3)
            doc.add_paragraph(f"Target: {a.target}")
            if a.ip:
                doc.add_paragraph(f"IP: {a.ip}")
            if a.os_guess:
                doc.add_paragraph(f"OS guess: {a.os_guess}")

            if a.findings:
                doc.add_paragraph("Findings:")
                ftbl = doc.add_table(rows=1, cols=4)
                ftbl.style = "Light List Accent 2"
                h = ftbl.rows[0].cells
                h[0].text, h[1].text, h[2].text, h[3].text = (
                    "Severity",
                    "Title",
                    "CVE",
                    "Discovered by",
                )
                for f in a.findings:
                    r = ftbl.add_row().cells
                    r[0].text = f.severity
                    r[1].text = f.title
                    r[2].text = f.cve_id or "—"
                    r[3].text = f.discovered_by

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


__all__ = [
    "render_docx",
    "render_html",
    "render_markdown",
    "render_pdf",
]
