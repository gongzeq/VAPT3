"""Report render helpers: Markdown (canonical), HTML, DOCX, PDF.

Spec: `.trellis/spec/backend/report-pipeline.md` §3.

Markdown is the canonical format. HTML is derived from Markdown for PDF
rendering via WeasyPrint. DOCX is built programmatically from the
:class:`ReportModel` because python-docx has no native Markdown ingest.
"""

from __future__ import annotations

import html as _html_mod
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from secbot.report.builder import ReportModel, ReportRenderError, SEVERITY_ORDER


def _esc(s: str) -> str:
    """HTML-escape a string (short alias to keep render lines readable)."""
    return _html_mod.escape(str(s), quote=True)

if TYPE_CHECKING:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


_SEV_LABELS: dict[str, str] = {
    "critical": "严重",
    "high": "高危",
    "medium": "中危",
    "low": "低危",
    "info": "信息",
}


def _fmt_dt(dt) -> str:
    return dt.isoformat() if dt else "—"


def render_markdown(model: ReportModel) -> str:
    """Render *model* to Markdown (canonical)."""
    out: list[str] = []
    out.append(f"# 安全扫描报告")
    out.append("")
    out.append(f"- **扫描 ID**: `{model.scan_id}`")
    out.append(f"- **目标**: {model.target}")
    out.append(f"- **开始时间**: {_fmt_dt(model.started_at)}")
    out.append(f"- **结束时间**: {_fmt_dt(model.finished_at)}")
    out.append("")
    out.append("## 摘要")
    out.append("")
    out.append(f"- 资产: **{model.summary.asset_count}**")
    out.append(f"- 服务: **{model.summary.service_count}**")
    out.append(f"- 发现: **{model.summary.finding_count}**")
    out.append("")
    out.append("| 严重级别 | 数量 |")
    out.append("|---|---|")
    for sev in SEVERITY_ORDER:
        out.append(f"| {_SEV_LABELS.get(sev, sev)} | {model.summary.severity_counts.get(sev, 0)} |")
    out.append("")

    if model.is_empty():
        out.append("_本次扫描未记录任何资产。_")
        out.append("")
    else:
        out.append("## 资产")
        out.append("")
        for a in model.assets:
            label = a.hostname or a.ip or a.target
            out.append(f"### {label}")
            out.append("")
            out.append(f"- 目标: `{a.target}`")
            if a.ip:
                out.append(f"- IP: `{a.ip}`")
            if a.hostname:
                out.append(f"- 主机名: {a.hostname}")
            if a.os_guess:
                out.append(f"- 操作系统推测: {a.os_guess}")
            out.append("")

            if a.services:
                out.append("#### 开放服务")
                out.append("")
                out.append("| 端口 | 协议 | 服务 | 产品 | 版本 |")
                out.append("|---|---|---|---|---|")
                for s in a.services:
                    out.append(
                        f"| {s.port} | {s.protocol} | {s.service or '—'} | "
                        f"{s.product or '—'} | {s.version or '—'} |"
                    )
                out.append("")

            if a.findings:
                out.append("#### 漏洞详情")
                out.append("")
                for f in a.findings:
                    sev_label = _SEV_LABELS.get(f.severity, f.severity)
                    out.append(f"##### [{sev_label}] {f.title}")
                    out.append("")
                    meta = f"- **类别**: {f.category}  "
                    meta += f"**发现工具**: {f.discovered_by}"
                    if f.cve_id:
                        meta += f"  \n- **CVE**: `{f.cve_id}`"
                    out.append(meta)
                    if f.affected_url:
                        out.append(f"- **受影响端点**: `{f.affected_url}`")
                    if f.evidence_summary:
                        out.append(f"- **漏洞描述**: {f.evidence_summary}")
                    out.append("")
                    if f.verification_steps:
                        out.append("**验证步骤**:")
                        out.append("")
                        for i, step in enumerate(f.verification_steps, 1):
                            out.append(f"{i}. {step}")
                        out.append("")
                    if f.evidence_detail:
                        out.append("**证据详情**:")
                        out.append("")
                        out.append("```")
                        out.append(f.evidence_detail)
                        out.append("```")
                        out.append("")
                    if f.remediation:
                        out.append(f"**修复建议**: {f.remediation}")
                        out.append("")
                    if f.references:
                        out.append("**参考资料**:")
                        out.append("")
                        for ref in f.references:
                            out.append(f"- {ref}")
                        out.append("")
                    out.append("---")
                    out.append("")

    if model.appendix.raw_log_paths:
        out.append("## 附录：原始日志")
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
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #0F172A;
      background: #F8FAFC;
      margin: 0;
      padding: 0;
      line-height: 1.6;
    }
    .toolbar {
      position: sticky;
      top: 0;
      z-index: 100;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 24px;
      background: linear-gradient(90deg, #0F172A 0%, #1E293B 100%);
      border-bottom: 1px solid #334155;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }
    .toolbar-title {
      color: #F8FAFC;
      font-size: 16px;
      font-weight: 600;
      letter-spacing: 0.3px;
    }
    .toolbar-actions { display: flex; gap: 10px; }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      border-radius: 6px;
      border: 1px solid #475569;
      background: #1E293B;
      color: #E2E8F0;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
      text-decoration: none;
    }
    .btn:hover { background: #334155; border-color: #64748B; }
    .btn svg { width: 14px; height: 14px; fill: currentColor; }
    .container {
      max-width: 960px;
      margin: 0 auto;
      padding: 32px 24px;
    }
    h1, h2, h3 { color: #1E3A8A; margin-top: 1.5em; margin-bottom: 0.6em; }
    h1 { font-size: 28px; margin-top: 0; border-bottom: 2px solid #E2E8F0; padding-bottom: 12px; }
    h2 { font-size: 20px; }
    h3 { font-size: 16px; color: #334155; }
    table { border-collapse: collapse; margin-bottom: 1.5rem; width: 100%; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
    th, td { border: 1px solid #E2E8F0; padding: 10px 14px; font-size: 13px; }
    th { background: #F1F5F9; font-weight: 600; text-align: left; }
    .badge { padding: 3px 10px; border-radius: 999px; color: #fff; font-size: 12px; font-weight: 500; display: inline-block; }
    .sev-critical { background: #991B1B; }
    .sev-high { background: #DC2626; }
    .sev-medium { background: #D97706; }
    .sev-low { background: #2563EB; }
    .sev-info { background: #475569; }
    ul { padding-left: 20px; }
    code { background: #F1F5F9; padding: 2px 6px; border-radius: 4px; font-size: 12px; color: #334155; }
    .finding-card { background: #fff; border-radius: 8px; border: 1px solid #E2E8F0; padding: 16px 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .finding-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .finding-title { font-weight: 600; font-size: 14px; color: #0F172A; }
    .finding-meta { font-size: 12px; color: #64748B; }
    .finding-section { margin-top: 10px; }
    .finding-section-title { font-weight: 600; font-size: 12px; color: #475569; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
    .finding-detail { font-size: 13px; color: #334155; white-space: pre-wrap; word-break: break-word; }
    .finding-steps { padding-left: 18px; margin: 4px 0 0 0; }
    .finding-steps li { font-size: 13px; color: #334155; margin-bottom: 3px; }
    .finding-refs { font-size: 12px; }
    .finding-refs a { color: #2563EB; text-decoration: none; }
    .finding-refs a:hover { text-decoration: underline; }
    pre.evidence { background: #1E293B; color: #E2E8F0; padding: 12px 16px; border-radius: 6px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; max-height: 300px; overflow-y: auto; }
    @media print {
      .toolbar { display: none !important; }
      body { background: #fff; }
      .container { padding: 16px; }
    }
    """
    lines: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>安全扫描报告</title>",
        f"<style>{css}</style></head><body>",
        '<div class="toolbar">',
        '  <span class="toolbar-title">🔒 安全扫描报告</span>',
        '  <div class="toolbar-actions">',
        '    <button class="btn" onclick="window.print()" title="打印报告">',
        '      <svg viewBox="0 0 24 24"><path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm-1-9H6v4h12V3z"/></svg>',
        '      打印报告',
        "    </button>",
        "  </div>",
        "</div>",
        '<div class="container">',
        "<h1>安全扫描报告</h1>",
        "<ul>",
        f"<li><strong>扫描 ID:</strong> <code>{model.scan_id}</code></li>",
        f"<li><strong>目标:</strong> {model.target}</li>",
        f"<li><strong>开始时间:</strong> {_fmt_dt(model.started_at)}</li>",
        f"<li><strong>结束时间:</strong> {_fmt_dt(model.finished_at)}</li>",
        "</ul>",
        "<h2>摘要</h2>",
        "<table><thead><tr><th>严重级别</th><th>数量</th></tr></thead><tbody>",
    ]
    for sev in SEVERITY_ORDER:
        count = model.summary.severity_counts.get(sev, 0)
        lines.append(
            f"<tr><td><span class=\"badge sev-{sev}\">{_SEV_LABELS.get(sev, sev)}</span></td>"
            f"<td>{count}</td></tr>"
        )
    lines.append("</tbody></table>")

    for a in model.assets:
        label = a.hostname or a.ip or a.target
        lines.append(f"<h3>{label}</h3>")
        lines.append("<ul>")
        lines.append(f"<li>目标: <code>{a.target}</code></li>")
        if a.ip:
            lines.append(f"<li>IP: <code>{a.ip}</code></li>")
        if a.os_guess:
            lines.append(f"<li>操作系统推测: {a.os_guess}</li>")
        lines.append("</ul>")
        if a.services:
            lines.append("<h4>开放服务</h4>")
            lines.append("<table><thead><tr><th>端口</th><th>协议</th>"
                         "<th>服务</th><th>产品</th><th>版本</th></tr></thead><tbody>")
            for s in a.services:
                lines.append(
                    f"<tr><td>{s.port}</td><td>{s.protocol}</td>"
                    f"<td>{s.service or '—'}</td><td>{s.product or '—'}</td>"
                    f"<td>{s.version or '—'}</td></tr>"
                )
            lines.append("</tbody></table>")
        if a.findings:
            lines.append("<h4>漏洞详情</h4>")
            for f in a.findings:
                sev_label = _SEV_LABELS.get(f.severity, f.severity)
                lines.append('<div class="finding-card">')
                # Header
                lines.append('<div class="finding-header">')
                lines.append(f'<span class="badge sev-{f.severity}">{sev_label}</span>')
                lines.append(f'<span class="finding-title">{_esc(f.title)}</span>')
                lines.append('</div>')
                # Meta row
                meta_parts = [f'类别: {f.category}', f'发现工具: {f.discovered_by}']
                if f.cve_id:
                    meta_parts.append(f'CVE: {f.cve_id}')
                lines.append(f'<div class="finding-meta">{" · ".join(_esc(p) for p in meta_parts)}</div>')
                # Affected URL
                if f.affected_url:
                    lines.append('<div class="finding-section">')
                    lines.append('<div class="finding-section-title">受影响端点</div>')
                    lines.append(f'<code>{_esc(f.affected_url)}</code>')
                    lines.append('</div>')
                # Evidence summary
                if f.evidence_summary:
                    lines.append('<div class="finding-section">')
                    lines.append('<div class="finding-section-title">漏洞描述</div>')
                    lines.append(f'<div class="finding-detail">{_esc(f.evidence_summary)}</div>')
                    lines.append('</div>')
                # Verification steps
                if f.verification_steps:
                    lines.append('<div class="finding-section">')
                    lines.append('<div class="finding-section-title">验证步骤</div>')
                    lines.append('<ol class="finding-steps">')
                    for step in f.verification_steps:
                        lines.append(f'<li>{_esc(step)}</li>')
                    lines.append('</ol>')
                    lines.append('</div>')
                # Evidence detail (request/response/curl)
                if f.evidence_detail:
                    lines.append('<div class="finding-section">')
                    lines.append('<div class="finding-section-title">证据详情</div>')
                    lines.append(f'<pre class="evidence">{_esc(f.evidence_detail)}</pre>')
                    lines.append('</div>')
                # Remediation
                if f.remediation:
                    lines.append('<div class="finding-section">')
                    lines.append('<div class="finding-section-title">修复建议</div>')
                    lines.append(f'<div class="finding-detail">{_esc(f.remediation)}</div>')
                    lines.append('</div>')
                # References
                if f.references:
                    lines.append('<div class="finding-section">')
                    lines.append('<div class="finding-section-title">参考资料</div>')
                    lines.append('<div class="finding-refs">')
                    for ref in f.references:
                        ref_escaped = _esc(ref)
                        if ref.startswith("http"):
                            lines.append(f'<a href="{ref_escaped}" target="_blank">{ref_escaped}</a><br>')
                        else:
                            lines.append(f'{ref_escaped}<br>')
                    lines.append('</div>')
                    lines.append('</div>')
                lines.append('</div>')
    lines.append("</div></body></html>")
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
    doc.add_heading("安全扫描报告", level=1)
    p = doc.add_paragraph()
    p.add_run("扫描 ID: ").bold = True
    p.add_run(model.scan_id)
    p = doc.add_paragraph()
    p.add_run("目标: ").bold = True
    p.add_run(model.target)
    doc.add_paragraph(f"开始时间: {_fmt_dt(model.started_at)}")
    doc.add_paragraph(f"结束时间: {_fmt_dt(model.finished_at)}")

    doc.add_heading("摘要", level=2)
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Light List Accent 1"
    hdr = tbl.rows[0].cells
    hdr[0].text = "严重级别"
    hdr[1].text = "数量"
    for sev in SEVERITY_ORDER:
        row = tbl.add_row().cells
        row[0].text = _SEV_LABELS.get(sev, sev)
        row[1].text = str(model.summary.severity_counts.get(sev, 0))

    if model.is_empty():
        doc.add_paragraph("本次扫描未记录任何资产。")
    else:
        doc.add_heading("资产", level=2)
        for a in model.assets:
            doc.add_heading(a.hostname or a.ip or a.target, level=3)
            doc.add_paragraph(f"目标: {a.target}")
            if a.ip:
                doc.add_paragraph(f"IP: {a.ip}")
            if a.os_guess:
                doc.add_paragraph(f"操作系统推测: {a.os_guess}")

            if a.findings:
                doc.add_heading("漏洞详情", level=4)
                for f in a.findings:
                    sev_label = _SEV_LABELS.get(f.severity, f.severity)
                    doc.add_heading(f"[{sev_label}] {f.title}", level=5)
                    p = doc.add_paragraph()
                    p.add_run("类别: ").bold = True
                    p.add_run(f.category)
                    p.add_run("  ·  ")
                    p.add_run("发现工具: ").bold = True
                    p.add_run(f.discovered_by)
                    if f.cve_id:
                        p.add_run("  ·  ")
                        p.add_run("CVE: ").bold = True
                        p.add_run(f.cve_id)
                    if f.affected_url:
                        p2 = doc.add_paragraph()
                        p2.add_run("受影响端点: ").bold = True
                        p2.add_run(f.affected_url)
                    if f.evidence_summary:
                        p3 = doc.add_paragraph()
                        p3.add_run("漏洞描述: ").bold = True
                        p3.add_run(f.evidence_summary)
                    if f.verification_steps:
                        doc.add_paragraph("验证步骤:").bold = True
                        for i, step in enumerate(f.verification_steps, 1):
                            doc.add_paragraph(f"{i}. {step}", style="List Number")
                    if f.evidence_detail:
                        doc.add_paragraph("证据详情:").bold = True
                        doc.add_paragraph(f.evidence_detail, style="No Spacing")
                    if f.remediation:
                        p4 = doc.add_paragraph()
                        p4.add_run("修复建议: ").bold = True
                        p4.add_run(f.remediation)
                    if f.references:
                        doc.add_paragraph("参考资料:").bold = True
                        for ref in f.references:
                            doc.add_paragraph(ref, style="List Bullet")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


__all__ = [
    "render_docx",
    "render_html",
    "render_markdown",
    "render_pdf",
]
