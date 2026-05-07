"""initial cmdb schema (asset / service / vulnerability / scan)

Revision ID: 20260507_initial
Revises:
Create Date: 2026-05-07 00:00:00

Spec: .trellis/spec/backend/cmdb-schema.md
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260507_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scan",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_scan_actor_status", "scan", ["actor_id", "status"])
    op.create_index("ix_scan_actor_created", "scan", ["actor_id", "created_at"])

    op.create_table(
        "asset",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scan_id",
            sa.String(),
            sa.ForeignKey("scan.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("os_guess", sa.String(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
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
    op.create_index("ix_asset_actor_ip", "asset", ["actor_id", "ip"])
    op.create_index("ix_asset_actor_hostname", "asset", ["actor_id", "hostname"])
    op.create_index("ix_asset_scan", "asset", ["scan_id"])

    op.create_table(
        "service",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("asset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("protocol", sa.String(), nullable=False),
        sa.Column("service", sa.String(), nullable=True),
        sa.Column("product", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="open"),
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
            "asset_id", "port", "protocol", name="uq_service_asset_port_proto"
        ),
    )

    op.create_table(
        "vulnerability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("asset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("service.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("cve_id", sa.String(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("raw_log_path", sa.String(), nullable=True),
        sa.Column("discovered_by", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_vuln_actor_severity_created",
        "vulnerability",
        ["actor_id", "severity", "created_at"],
    )
    op.create_index("ix_vuln_asset", "vulnerability", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_vuln_asset", table_name="vulnerability")
    op.drop_index("ix_vuln_actor_severity_created", table_name="vulnerability")
    op.drop_table("vulnerability")
    op.drop_table("service")
    op.drop_index("ix_asset_scan", table_name="asset")
    op.drop_index("ix_asset_actor_hostname", table_name="asset")
    op.drop_index("ix_asset_actor_ip", table_name="asset")
    op.drop_table("asset")
    op.drop_index("ix_scan_actor_created", table_name="scan")
    op.drop_index("ix_scan_actor_status", table_name="scan")
    op.drop_table("scan")
