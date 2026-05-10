"""add report_meta table

Revision ID: 20260510_report_meta
Revises: 20260507_initial
Create Date: 2026-05-10 00:00:00

Spec: .trellis/spec/backend/cmdb-schema.md §2.5 +
      .trellis/spec/backend/report-meta.md
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260510_report_meta"
down_revision: Union[str, None] = "20260507_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_meta",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(),
            sa.ForeignKey("scan.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="published",
        ),
        sa.Column(
            "critical_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("download_path", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False, server_default="local"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_report_meta_actor_status_created",
        "report_meta",
        ["actor_id", "status", "created_at"],
    )
    op.create_index("ix_report_meta_scan", "report_meta", ["scan_id"])


def downgrade() -> None:
    op.drop_index("ix_report_meta_scan", table_name="report_meta")
    op.drop_index(
        "ix_report_meta_actor_status_created", table_name="report_meta"
    )
    op.drop_table("report_meta")
