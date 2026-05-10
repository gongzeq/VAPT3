"""Report pipeline.

Spec: `.trellis/spec/backend/report-pipeline.md`.

Builds a typed :class:`ReportModel` from the CMDB, then renders it to
Markdown (canonical), HTML→PDF, or DOCX. Markdown is the SSoT: DOCX and
PDF derive from it rather than re-querying the CMDB.
"""

from secbot.report.builder import (
    ReportAppendix,
    ReportAsset,
    ReportFinding,
    ReportModel,
    ReportRenderError,
    ReportService,
    ReportSummary,
    build_report_model,
    record_report_meta,
)
from secbot.report.render import render_docx, render_markdown, render_pdf

__all__ = [
    "ReportAppendix",
    "ReportAsset",
    "ReportFinding",
    "ReportModel",
    "ReportRenderError",
    "ReportService",
    "ReportSummary",
    "build_report_model",
    "record_report_meta",
    "render_docx",
    "render_markdown",
    "render_pdf",
]
