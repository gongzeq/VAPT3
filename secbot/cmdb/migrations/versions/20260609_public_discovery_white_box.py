"""add public asset discovery and white-box assessment tables

Revision ID: 20260609_public_discovery_white_box
Revises: 20260607_vulnerability_candidate
Create Date: 2026-06-09 00:00:00

Spec: .trellis/tasks/06-09-public-asset-discovery-whitebox-assessment/prd.md
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_public_discovery_white_box"
down_revision: Union[str, None] = "20260607_vulnerability_candidate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("asset") as batch_op:
        batch_op.alter_column(
            "scan_id",
            existing_type=sa.String(),
            nullable=True,
        )

    op.create_table(
        "organization_scope",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("root_domains", sa.JSON(), nullable=True),
        sa.Column("icp_subjects", sa.JSON(), nullable=True),
        sa.Column("certificate_subjects", sa.JSON(), nullable=True),
        sa.Column("asns", sa.JSON(), nullable=True),
        sa.Column("ip_ranges", sa.JSON(), nullable=True),
        sa.Column("include_terms", sa.JSON(), nullable=True),
        sa.Column("exclude_terms", sa.JSON(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_org_scope_actor_name", "organization_scope", ["actor_id", "name"])

    op.create_table(
        "external_asset_search_credential",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("credential_ref", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "actor_id",
            "source",
            name="uq_external_asset_credential_source",
        ),
    )
    op.create_index(
        "ix_external_asset_credential_actor",
        "external_asset_search_credential",
        ["actor_id", "enabled"],
    )

    op.create_table(
        "asset_search_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scope_id",
            sa.Integer(),
            sa.ForeignKey("organization_scope.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_asset_search_rule_actor_scope",
        "asset_search_rule",
        ["actor_id", "scope_id"],
    )
    op.create_index(
        "ix_asset_search_rule_actor_source",
        "asset_search_rule",
        ["actor_id", "source", "enabled"],
    )

    op.create_table(
        "scheduled_public_asset_discovery",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scope_id",
            sa.Integer(),
            sa.ForeignKey("organization_scope.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cadence_hours", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_public_discovery_schedule_actor",
        "scheduled_public_asset_discovery",
        ["actor_id", "enabled", "next_run_at"],
    )

    op.create_table(
        "public_asset_candidate",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scope_id",
            sa.Integer(),
            sa.ForeignKey("organization_scope.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_host", sa.String(), nullable=False),
        sa.Column("display_host", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="unreviewed"),
        sa.Column(
            "managed_asset_id",
            sa.Integer(),
            sa.ForeignKey("asset.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("review_note", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "actor_id",
            "scope_id",
            "normalized_host",
            name="uq_public_asset_candidate_scope_host",
        ),
    )
    op.create_index(
        "ix_public_asset_candidate_actor_status",
        "public_asset_candidate",
        ["actor_id", "status"],
    )
    op.create_index(
        "ix_public_asset_candidate_scope_status",
        "public_asset_candidate",
        ["scope_id", "status"],
    )

    op.create_table(
        "public_asset_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("public_asset_candidate.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("asset_search_rule.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("observed_host", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("banner", sa.String(), nullable=True),
        sa.Column("certificate", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_public_asset_evidence_candidate",
        "public_asset_evidence",
        ["candidate_id", "source"],
    )
    op.create_index(
        "ix_public_asset_evidence_actor_source",
        "public_asset_evidence",
        ["actor_id", "source"],
    )

    op.create_table(
        "white_box_assessment",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("package_format", sa.String(), nullable=False),
        sa.Column("compressed_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("extracted_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("language_summary", sa.JSON(), nullable=True),
        sa.Column("archive_path", sa.String(), nullable=True),
        sa.Column("extracted_path", sa.String(), nullable=True),
        sa.Column("source_retained", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_white_box_assessment_actor_status",
        "white_box_assessment",
        ["actor_id", "status"],
    )
    op.create_index(
        "ix_white_box_assessment_actor_created",
        "white_box_assessment",
        ["actor_id", "created_at"],
    )

    op.create_table(
        "white_box_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assessment_id",
            sa.String(),
            sa.ForeignKey("white_box_assessment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analyzer", sa.String(), nullable=False),
        sa.Column("vulnerability_type", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("primary_file", sa.String(), nullable=False),
        sa.Column("primary_sink_line", sa.Integer(), nullable=True),
        sa.Column("entry_points", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("sinks", sa.JSON(), nullable=True),
        sa.Column("sanitizers", sa.JSON(), nullable=True),
        sa.Column("data_flow", sa.JSON(), nullable=True),
        sa.Column("prerequisites", sa.JSON(), nullable=True),
        sa.Column("request_samples", sa.JSON(), nullable=True),
        sa.Column("remediation", sa.String(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_white_box_evidence_assessment",
        "white_box_evidence",
        ["assessment_id", "analyzer"],
    )
    op.create_index(
        "ix_white_box_evidence_actor",
        "white_box_evidence",
        ["actor_id", "confidence"],
    )

    op.create_table(
        "white_box_finding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assessment_id",
            sa.String(),
            sa.ForeignKey("white_box_assessment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.Integer(),
            sa.ForeignKey("white_box_evidence.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("vulnerability_type", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="other"),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("primary_file", sa.String(), nullable=False),
        sa.Column("primary_sink_line", sa.Integer(), nullable=True),
        sa.Column(
            "promoted_vulnerability_id",
            sa.Integer(),
            sa.ForeignKey("vulnerability.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "assessment_id",
            "dedupe_key",
            name="uq_white_box_finding_dedupe",
        ),
    )
    op.create_index(
        "ix_white_box_finding_actor_status",
        "white_box_finding",
        ["actor_id", "status"],
    )
    op.create_index(
        "ix_white_box_finding_assessment",
        "white_box_finding",
        ["assessment_id", "severity"],
    )

    op.create_table(
        "white_box_reproduction_document",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assessment_id",
            sa.String(),
            sa.ForeignKey("white_box_assessment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            sa.Integer(),
            sa.ForeignKey("white_box_finding.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.Integer(),
            sa.ForeignKey("white_box_evidence.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("markdown", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_white_box_repro_assessment",
        "white_box_reproduction_document",
        ["assessment_id", "finding_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_white_box_repro_assessment", table_name="white_box_reproduction_document")
    op.drop_table("white_box_reproduction_document")
    op.drop_index("ix_white_box_finding_assessment", table_name="white_box_finding")
    op.drop_index("ix_white_box_finding_actor_status", table_name="white_box_finding")
    op.drop_table("white_box_finding")
    op.drop_index("ix_white_box_evidence_actor", table_name="white_box_evidence")
    op.drop_index("ix_white_box_evidence_assessment", table_name="white_box_evidence")
    op.drop_table("white_box_evidence")
    op.drop_index("ix_white_box_assessment_actor_created", table_name="white_box_assessment")
    op.drop_index("ix_white_box_assessment_actor_status", table_name="white_box_assessment")
    op.drop_table("white_box_assessment")
    op.drop_index("ix_public_asset_evidence_actor_source", table_name="public_asset_evidence")
    op.drop_index("ix_public_asset_evidence_candidate", table_name="public_asset_evidence")
    op.drop_table("public_asset_evidence")
    op.drop_index("ix_public_asset_candidate_scope_status", table_name="public_asset_candidate")
    op.drop_index("ix_public_asset_candidate_actor_status", table_name="public_asset_candidate")
    op.drop_table("public_asset_candidate")
    op.drop_index(
        "ix_public_discovery_schedule_actor",
        table_name="scheduled_public_asset_discovery",
    )
    op.drop_table("scheduled_public_asset_discovery")
    op.drop_index("ix_asset_search_rule_actor_source", table_name="asset_search_rule")
    op.drop_index("ix_asset_search_rule_actor_scope", table_name="asset_search_rule")
    op.drop_table("asset_search_rule")
    op.drop_index(
        "ix_external_asset_credential_actor",
        table_name="external_asset_search_credential",
    )
    op.drop_table("external_asset_search_credential")
    op.drop_index("ix_org_scope_actor_name", table_name="organization_scope")
    op.drop_table("organization_scope")
    with op.batch_alter_table("asset") as batch_op:
        batch_op.alter_column(
            "scan_id",
            existing_type=sa.String(),
            nullable=False,
        )
