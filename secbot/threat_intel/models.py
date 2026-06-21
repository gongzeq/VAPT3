"""SQLAlchemy 2.x ORM models for the Threat Intel database.

Schema contract: ``docs/prd-threat-intelligence.md`` §3 (Data Model).

The Threat Intel DB is independent of the CMDB — separate file, separate
engine, separate migrations.  The star model centres on **Threat Group**
as the hub for infrastructure IPs, malware families, and (optionally)
exploited vulnerabilities.  Maritime events and feed run records are
independent dimensions.

Every business table carries ``actor_id`` (multi-tenant reservation).
The default ``'local'`` lets v1 run single-user; the column is NOT NULL
so future RBAC migrations stay non-breaking — mirroring the CMDB pattern.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DEFAULT_ACTOR = "local"

# ---------------------------------------------------------------------------
# Enumerations (stored as strings; validated at the repo layer)
# ---------------------------------------------------------------------------

IP_TYPES = ("c2", "scanner", "proxy", "drop")
IP_STATUSES = ("active", "inactive")
VULN_SEVERITIES = ("high", "critical")
RELATIONSHIP_TYPES = ("exploited", "targeted", "reported")
MALWARE_TYPES = ("rat", "backdoor", "ransomware", "stealer", "dropper", "botnet", "other")
MARITIME_EVENT_TYPES = ("piracy", "security_warning", "gnss_interference", "navigation_warning", "other")
MARITIME_SEVERITIES = ("critical", "high", "medium", "low")
MARITIME_SOURCES = ("imo", "ukmto", "recaap", "other")
VERIFICATION_STATUSES = ("unreviewed", "confirmed", "dismissed")
FEED_SOURCES = ("mitre", "cisa_kev", "threatfox", "feodo", "malwarebazaar", "otx", "nvd", "exploit_db", "manual")
FEED_TRIGGERS = ("manual", "schedule")
FEED_STATUSES = ("running", "ok", "partial", "failed")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all Threat Intel tables."""


# ---------------------------------------------------------------------------
# 1. Threat Group — the hub of the star model
# ---------------------------------------------------------------------------

class ThreatGroup(Base):
    """Threat Group (APT / crime group / nation-state actor)."""

    __tablename__ = "threat_group"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    origin_country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_sectors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    mitre_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    techniques: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    first_seen: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_seen: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="mitre")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    last_ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    # Relationships
    infra_ips: Mapped[list["ThreatInfraIP"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    malware_families: Mapped[list["ThreatMalwareFamily"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    vuln_associations: Mapped[list["ThreatGroupVulnAssoc"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    watchlist_entries: Mapped[list["Watchlist"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    apt_aliases: Mapped[list["AptAlias"]] = relationship(back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("mitre_id", name="uq_threat_group_mitre_id"),
        Index("ix_threat_group_name", "name"),
        Index("ix_threat_group_origin", "origin_country"),
    )


# ---------------------------------------------------------------------------
# 2. Threat Infrastructure IP (C2 / scanner / proxy / drop)
# ---------------------------------------------------------------------------

class ThreatInfraIP(Base):
    """Threat infrastructure IP — C2, scanner, proxy, or drop server."""

    __tablename__ = "threat_infra_ip"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("threat_group.id", ondelete="CASCADE"), nullable=False
    )
    ip_address: Mapped[str] = mapped_column(String, nullable=False)
    ip_type: Mapped[str] = mapped_column(String, nullable=False, default="c2")
    malware_family: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    geo_country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    asn: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    source: Mapped[str] = mapped_column(String, nullable=False, default="threatfox")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    source_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    last_ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    group: Mapped[ThreatGroup] = relationship(back_populates="infra_ips")

    __table_args__ = (
        UniqueConstraint("group_id", "ip_address", "ip_type", name="uq_threat_ip_group_ip_type"),
        Index("ix_threat_ip_address", "ip_address"),
        Index("ix_threat_ip_group", "group_id"),
        Index("ix_threat_ip_status", "status"),
    )


# ---------------------------------------------------------------------------
# 3. Threat Vulnerability (independent — not always APT-attributed)
# ---------------------------------------------------------------------------

class ThreatVuln(Base):
    """Threat vulnerability — CISA KEV / NVD CVE with CVSS >= 7.0."""

    __tablename__ = "threat_vuln"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    cve_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cvss_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="high")
    affected_products: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_supply_chain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_poc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exploit_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cisa_kev: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cisa_kev_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    published_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    primary_source: Mapped[str] = mapped_column(String, nullable=False, default="cisa_kev")
    sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    last_ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    group_associations: Mapped[list["ThreatGroupVulnAssoc"]] = relationship(
        back_populates="vulnerability", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("cve_id", name="uq_threat_vuln_cve_id"),
        Index("ix_threat_vuln_severity", "severity"),
        Index("ix_threat_vuln_cisa_kev", "is_cisa_kev"),
        Index("ix_threat_vuln_supply_chain", "is_supply_chain"),
    )


# ---------------------------------------------------------------------------
# 4. Threat Group Vulnerability Association
# ---------------------------------------------------------------------------

class ThreatGroupVulnAssoc(Base):
    """Association between a Threat Group and a Threat Vulnerability.

    Only ``exploited`` relationships appear in the group detail page's
    "Known Exploited Vulns" default list; ``targeted`` / ``reported``
    are weak-evidence and folded by default.
    """

    __tablename__ = "threat_group_vuln_assoc"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("threat_group.id", ondelete="CASCADE"), nullable=False
    )
    vulnerability_id: Mapped[str] = mapped_column(
        String, ForeignKey("threat_vuln.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String, nullable=False, default="exploited")
    first_seen: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_seen: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    source_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    group: Mapped[ThreatGroup] = relationship(back_populates="vuln_associations")
    vulnerability: Mapped[ThreatVuln] = relationship(back_populates="group_associations")

    __table_args__ = (
        UniqueConstraint(
            "group_id", "vulnerability_id", "relationship_type",
            name="uq_group_vuln_assoc",
        ),
    )


# ---------------------------------------------------------------------------
# 5. Threat Malware Family
# ---------------------------------------------------------------------------

class ThreatMalwareFamily(Base):
    """Malware family associated with a threat group."""

    __tablename__ = "threat_malware_family"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("threat_group.id", ondelete="CASCADE"), nullable=False
    )
    family_name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False, default="other")
    platform: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sample_hashes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    yara_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    first_seen: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_active: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    source_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    last_ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    group: Mapped[ThreatGroup] = relationship(back_populates="malware_families")

    __table_args__ = (
        UniqueConstraint("group_id", "family_name", name="uq_malware_group_family"),
        Index("ix_malware_family_name", "family_name"),
        Index("ix_malware_type", "type"),
    )


# ---------------------------------------------------------------------------
# 6. Maritime Intelligence Event (independent — no APT attribution)
# ---------------------------------------------------------------------------

class MaritimeEvent(Base):
    """Maritime intelligence event — piracy, security warning, GNSS interference.

    Stored independently; no APT attribution.  P2 sources use LLM extraction.
    """

    __tablename__ = "maritime_event"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    event_type: Mapped[str] = mapped_column(String, nullable=False, default="other")
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="other")
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    verification_status: Mapped[str] = mapped_column(String, nullable=False, default="unreviewed")
    source_refs: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_url", "event_date", name="uq_maritime_source_url_date"),
        Index("ix_maritime_event_type", "event_type"),
        Index("ix_maritime_severity", "severity"),
        Index("ix_maritime_event_date", "event_date"),
    )


# ---------------------------------------------------------------------------
# 7. Watchlist (user-scoped)
# ---------------------------------------------------------------------------

class Watchlist(Base):
    """User's watched threat groups.  Scoped by ``actor_id``."""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False, default=DEFAULT_ACTOR, server_default=DEFAULT_ACTOR)
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("threat_group.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    group: Mapped[ThreatGroup] = relationship(back_populates="watchlist_entries")

    __table_args__ = (
        UniqueConstraint("actor_id", "group_id", name="uq_watchlist_actor_group"),
        Index("ix_watchlist_actor", "actor_id"),
    )


# ---------------------------------------------------------------------------
# 8. Industry CPE List (configuration)
# ---------------------------------------------------------------------------

class IndustryCPE(Base):
    """Industry CPE entry — maritime / port / SCADA / transport products."""

    __tablename__ = "industry_cpe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cpe_string: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    vendor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    industry_tag: Mapped[str] = mapped_column(String, nullable=False, default="maritime")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("cpe_string", name="uq_industry_cpe_string"),
        Index("ix_industry_cpe_tag", "industry_tag"),
    )


# ---------------------------------------------------------------------------
# 9. APT Alias (Chinese / vendor naming mapping)
# ---------------------------------------------------------------------------

class AptAlias(Base):
    """APT alias mapping — Chinese names (海莲花, 蔓灵花, etc.) to MITRE groups."""

    __tablename__ = "apt_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("threat_group.id", ondelete="SET NULL"), nullable=True
    )
    alias_name: Mapped[str] = mapped_column(String, nullable=False)
    naming_org: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    group: Mapped[Optional[ThreatGroup]] = relationship(back_populates="apt_aliases")

    __table_args__ = (
        UniqueConstraint("alias_name", "naming_org", name="uq_apt_alias_name_org"),
        Index("ix_apt_alias_name", "alias_name"),
    )


# ---------------------------------------------------------------------------
# 10. Feed Pull Run (operational dimension)
# ---------------------------------------------------------------------------

class FeedPullRun(Base):
    """Record of a single feed pull execution — status, counts, errors."""

    __tablename__ = "feed_pull_run"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ULID
    source: Mapped[str] = mapped_column(String, nullable=False)
    trigger: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmapped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_feed_run_source", "source"),
        Index("ix_feed_run_status", "status"),
        Index("ix_feed_run_started", "started_at"),
    )
