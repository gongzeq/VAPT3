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
    BigInteger,
    Boolean,
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
    scan_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("scan.id", ondelete="SET NULL"), nullable=True
    )
    target: Mapped[str] = mapped_column(String, nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hostname: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    os_guess: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Reserved keys: ``system`` (business system name) and ``type`` (asset
    # class: 业务|智能体|OA|中间件|支撑|内网|其他). See
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
    vulnerability_candidates: Mapped[list["VulnerabilityCandidate"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    public_asset_candidates: Mapped[list["PublicAssetCandidate"]] = relationship(
        back_populates="managed_asset"
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
    vulnerability_candidates: Mapped[list["VulnerabilityCandidate"]] = relationship(
        back_populates="service"
    )

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


class VulnerabilityCandidate(Base):
    """Passive vulnerability database match awaiting explicit verification."""

    __tablename__ = "vulnerability_candidate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("service.id", ondelete="SET NULL"), nullable=True
    )
    identity_key: Mapped[str] = mapped_column(String, nullable=False)
    cve_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cnvd_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="candidate")
    last_verification_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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

    asset: Mapped[Asset] = relationship(back_populates="vulnerability_candidates")
    service: Mapped[Optional[Service]] = relationship(back_populates="vulnerability_candidates")

    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "asset_id",
            "service_id",
            "identity_key",
            name="uq_vuln_candidate_identity",
        ),
        Index("ix_vuln_candidate_actor_status", "actor_id", "status"),
        Index("ix_vuln_candidate_asset", "asset_id"),
    )


class OrganizationScope(Base):
    """Ownership scope for passive public asset discovery."""

    __tablename__ = "organization_scope"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    root_domains: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    icp_subjects: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    certificate_subjects: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    asns: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ip_ranges: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    include_terms: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    exclude_terms: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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

    search_rules: Mapped[list["AssetSearchRule"]] = relationship(
        back_populates="scope", cascade="all, delete-orphan"
    )
    schedules: Mapped[list["ScheduledPublicAssetDiscovery"]] = relationship(
        back_populates="scope", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["PublicAssetCandidate"]] = relationship(
        back_populates="scope", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_org_scope_actor_name", "actor_id", "name"),
    )


class ExternalAssetSearchCredential(Base):
    """Platform-level credential metadata for an external search source."""

    __tablename__ = "external_asset_search_credential"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    credential_ref: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

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

    __table_args__ = (
        UniqueConstraint("actor_id", "source", name="uq_external_asset_credential_source"),
        Index("ix_external_asset_credential_actor", "actor_id", "enabled"),
    )


class AssetSearchRule(Base):
    """Source-specific passive search query under an organization scope."""

    __tablename__ = "asset_search_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organization_scope.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    query: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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

    scope: Mapped[OrganizationScope] = relationship(back_populates="search_rules")
    evidence: Mapped[list["PublicAssetEvidence"]] = relationship(back_populates="rule")

    __table_args__ = (
        Index("ix_asset_search_rule_actor_scope", "actor_id", "scope_id"),
        Index("ix_asset_search_rule_actor_source", "actor_id", "source", "enabled"),
    )


class ScheduledPublicAssetDiscovery(Base):
    """Passive recurring discovery job for an organization scope."""

    __tablename__ = "scheduled_public_asset_discovery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organization_scope.id", ondelete="CASCADE"), nullable=False
    )
    cadence_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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

    scope: Mapped[OrganizationScope] = relationship(back_populates="schedules")

    __table_args__ = (
        Index("ix_public_discovery_schedule_actor", "actor_id", "enabled", "next_run_at"),
    )


class PublicAssetCandidate(Base):
    """Passive public-internet discovery awaiting ownership review."""

    __tablename__ = "public_asset_candidate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organization_scope.id", ondelete="CASCADE"), nullable=False
    )
    normalized_host: Mapped[str] = mapped_column(String, nullable=False)
    display_host: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="unreviewed")
    managed_asset_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("asset.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    review_note: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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

    scope: Mapped[OrganizationScope] = relationship(back_populates="candidates")
    managed_asset: Mapped[Optional[Asset]] = relationship(back_populates="public_asset_candidates")
    evidence: Mapped[list["PublicAssetEvidence"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "scope_id",
            "normalized_host",
            name="uq_public_asset_candidate_scope_host",
        ),
        Index("ix_public_asset_candidate_actor_status", "actor_id", "status"),
        Index("ix_public_asset_candidate_scope_status", "scope_id", "status"),
    )


class PublicAssetEvidence(Base):
    """Source-returned observation supporting a public asset candidate."""

    __tablename__ = "public_asset_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("public_asset_candidate.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("asset_search_rule.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    observed_host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    protocol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    banner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    certificate: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    candidate: Mapped[PublicAssetCandidate] = relationship(back_populates="evidence")
    rule: Mapped[Optional[AssetSearchRule]] = relationship(back_populates="evidence")

    __table_args__ = (
        Index("ix_public_asset_evidence_candidate", "candidate_id", "source"),
        Index("ix_public_asset_evidence_actor_source", "actor_id", "source"),
    )


class WhiteBoxAssessment(Base):
    """Independent source-code assessment task, separate from Scan."""

    __tablename__ = "white_box_assessment"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    package_name: Mapped[str] = mapped_column(String, nullable=False)
    package_format: Mapped[str] = mapped_column(String, nullable=False)
    compressed_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    extracted_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    language_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    archive_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extracted_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_retained: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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

    evidence: Mapped[list["WhiteBoxEvidence"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    findings: Mapped[list["WhiteBoxFinding"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    reproduction_documents: Mapped[list["WhiteBoxReproductionDocument"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_white_box_assessment_actor_status", "actor_id", "status"),
        Index("ix_white_box_assessment_actor_created", "actor_id", "created_at"),
    )


class WhiteBoxEvidence(Base):
    """Structured source-code evidence that grounds a White-Box Finding."""

    __tablename__ = "white_box_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(
        String, ForeignKey("white_box_assessment.id", ondelete="CASCADE"), nullable=False
    )
    analyzer: Mapped[str] = mapped_column(String, nullable=False)
    vulnerability_type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    primary_file: Mapped[str] = mapped_column(String, nullable=False)
    primary_sink_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_points: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sinks: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sanitizers: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    data_flow: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    prerequisites: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    request_samples: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    remediation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    assessment: Mapped[WhiteBoxAssessment] = relationship(back_populates="evidence")
    findings: Mapped[list["WhiteBoxFinding"]] = relationship(back_populates="evidence")
    reproduction_documents: Mapped[list["WhiteBoxReproductionDocument"]] = relationship(
        back_populates="evidence"
    )

    __table_args__ = (
        Index("ix_white_box_evidence_assessment", "assessment_id", "analyzer"),
        Index("ix_white_box_evidence_actor", "actor_id", "confidence"),
    )


class WhiteBoxFinding(Base):
    """Reviewable white-box finding that does not count as a confirmed Vulnerability."""

    __tablename__ = "white_box_finding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(
        String, ForeignKey("white_box_assessment.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("white_box_evidence.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    vulnerability_type: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, default="other")
    severity: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False)
    primary_file: Mapped[str] = mapped_column(String, nullable=False)
    primary_sink_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    promoted_vulnerability_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vulnerability.id", ondelete="SET NULL"), nullable=True
    )

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

    assessment: Mapped[WhiteBoxAssessment] = relationship(back_populates="findings")
    evidence: Mapped[WhiteBoxEvidence] = relationship(back_populates="findings")
    reproduction_documents: Mapped[list["WhiteBoxReproductionDocument"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("assessment_id", "dedupe_key", name="uq_white_box_finding_dedupe"),
        Index("ix_white_box_finding_actor_status", "actor_id", "status"),
        Index("ix_white_box_finding_assessment", "assessment_id", "severity"),
    )


class WhiteBoxReproductionDocument(Base):
    """Markdown artifact rendered from structured White-Box Evidence."""

    __tablename__ = "white_box_reproduction_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(
        String, ForeignKey("white_box_assessment.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("white_box_finding.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("white_box_evidence.id", ondelete="RESTRICT"), nullable=False
    )
    markdown: Mapped[str] = mapped_column(String, nullable=False)

    actor_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    assessment: Mapped[WhiteBoxAssessment] = relationship(back_populates="reproduction_documents")
    finding: Mapped[WhiteBoxFinding] = relationship(back_populates="reproduction_documents")
    evidence: Mapped[WhiteBoxEvidence] = relationship(back_populates="reproduction_documents")

    __table_args__ = (
        Index("ix_white_box_repro_assessment", "assessment_id", "finding_id"),
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
VALID_VULN_CANDIDATE_STATUSES = frozenset({"candidate", "verified", "dismissed"})
VALID_PUBLIC_ASSET_SEARCH_SOURCES = frozenset({"FOFA", "Quake", "Shodan"})
VALID_PUBLIC_ASSET_CANDIDATE_STATUSES = frozenset({"unreviewed", "promoted", "dismissed"})
VALID_PUBLIC_DISCOVERY_CADENCES_HOURS = frozenset({4, 8, 12})
VALID_WHITE_BOX_ASSESSMENT_STATUSES = frozenset(
    {"queued", "unpacking", "analyzing", "generating_docs", "completed", "failed", "cancelled"}
)
VALID_WHITE_BOX_FINDING_STATUSES = frozenset(
    {"open", "needs_review", "confirmed", "dismissed", "promoted"}
)
VALID_WHITE_BOX_CONFIDENCES = frozenset({"low", "medium", "high"})
VALID_SOURCE_PACKAGE_FORMATS = frozenset({"zip", "tar.gz"})

WHITE_BOX_ASSESSMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"unpacking", "cancelled", "failed"}),
    "unpacking": frozenset({"analyzing", "cancelled", "failed"}),
    "analyzing": frozenset({"generating_docs", "cancelled", "failed"}),
    "generating_docs": frozenset({"completed", "cancelled", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

# Reserved vocabulary for the `asset.tags.type` JSON key (spec §2.1.1).
# Business-oriented asset classification (Chinese labels).
VALID_ASSET_TYPES = frozenset(
    {
        "智能体",   # AI agent / bot / crawler endpoint
        "内网",     # Internal network host (RFC-1918, non-web service)
        "OA",       # Office automation (mail, LDAP, SSO, collaboration)
        "支撑",     # Infrastructure / support (DNS, DHCP, NTP, monitoring)
        "中间件",   # Middleware (Tomcat, Nginx, Redis, RabbitMQ, Kafka)
        "业务",     # Business application (web app, API, e-commerce)
        "其他",     # Catch-all
    }
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
