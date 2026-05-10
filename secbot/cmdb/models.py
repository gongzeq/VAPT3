"""SQLAlchemy 2.x ORM models for the local CMDB.

Schema contract: `.trellis/spec/backend/cmdb-schema.md`.

Every business table carries ``actor_id`` (multi-tenant reservation, §4 of
the spec). The default ``'local'`` lets v1 run single-user; the column is
NOT NULL so future RBAC migrations stay non-breaking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DEFAULT_ACTOR = "local"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all CMDB tables."""


class Scan(Base):
    __tablename__ = "scan"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    target: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    scope_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_scan_actor_status", "actor_id", "status"),
        Index("ix_scan_actor_created", "actor_id", "created_at"),
    )


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scan.id", ondelete="RESTRICT"), nullable=False
    )
    target: Mapped[str] = mapped_column(String, nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hostname: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    os_guess: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Reserved keys: ``system`` (business system name) and ``type`` (asset
    # class: web_app|api|database|server|network|other). See
    # `.trellis/spec/backend/cmdb-schema.md` §2.1.1. Free-form extras are
    # allowed alongside the reserved keys.
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    services: Mapped[list["Service"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    vulnerabilities: Mapped[list["Vulnerability"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_asset_actor_ip", "actor_id", "ip"),
        Index("ix_asset_actor_hostname", "actor_id", "hostname"),
        Index("ix_asset_scan", "scan_id"),
    )


class Service(Base):
    __tablename__ = "service"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String, nullable=False)
    service: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="open")

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    asset: Mapped[Asset] = relationship(back_populates="services")
    vulnerabilities: Mapped[list["Vulnerability"]] = relationship(back_populates="service")

    __table_args__ = (
        UniqueConstraint("asset_id", "port", "protocol", name="uq_service_asset_port_proto"),
    )


class Vulnerability(Base):
    __tablename__ = "vulnerability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("service.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    cve_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raw_log_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discovered_by: Mapped[str] = mapped_column(String, nullable=False)

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    asset: Mapped[Asset] = relationship(back_populates="vulnerabilities")
    service: Mapped[Optional[Service]] = relationship(back_populates="vulnerabilities")

    __table_args__ = (
        Index("ix_vuln_actor_severity_created", "actor_id", "severity", "created_at"),
        Index("ix_vuln_asset", "asset_id"),
    )


class ReportMeta(Base):
    """Persistent metadata row for a generated report.

    Contract: `.trellis/spec/backend/report-meta.md` + `cmdb-schema.md` §2.5.
    Written by each report skill handler (markdown/docx/pdf) **after** the
    render artefacts have been flushed to ``~/.secbot/reports/`` — the
    ``build_report_model`` helper remains pure per the spec §3.1 rule.
    """

    __tablename__ = "report_meta"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # RPT-YYYY-MMDD-<seq>
    scan_id: Mapped[str] = mapped_column(
        String, ForeignKey("scan.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="published", server_default="published"
    )
    critical_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    author: Mapped[str] = mapped_column(String, nullable=False)
    download_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_report_meta_actor_status_created",
            "actor_id",
            "status",
            "created_at",
        ),
        Index("ix_report_meta_scan", "scan_id"),
    )


VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
VALID_SCAN_STATUSES = frozenset(
    {"queued", "running", "awaiting_user", "completed", "failed", "cancelled"}
)
VALID_VULN_CATEGORIES = frozenset(
    {
        # Authoritative list per `.trellis/spec/backend/cmdb-schema.md` §2.3.1.
        # Order here is display-independent; the dashboard contract declares
        # bucket order separately in `.trellis/spec/backend/dashboard-aggregation.md`.
        "injection",
        "auth",
        "xss",
        "misconfig",
        "exposure",
        "weak_password",
        "cve",
        "other",
    }
)

# Reserved vocabulary for the `asset.tags.type` JSON key (spec §2.1.1).
VALID_ASSET_TYPES = frozenset(
    {"web_app", "api", "database", "server", "network", "other"}
)

# Allowed ``report_meta.type`` / ``report_meta.status`` values.
# Spec: `.trellis/spec/backend/report-meta.md` §2.
VALID_REPORT_TYPES = frozenset(
    {"compliance_monthly", "vuln_summary", "asset_inventory", "custom"}
)
VALID_REPORT_STATUSES = frozenset(
    {"published", "pending_review", "editing", "archived"}
)

# Legal status transitions per report-meta.md §3.3. Enforced at the repo layer
# (``update_report_status``); insert_report_meta may set any starting state.
REPORT_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "editing": frozenset({"pending_review", "published"}),
    "pending_review": frozenset({"published"}),
    "published": frozenset({"archived"}),
    "archived": frozenset({"published"}),
}
