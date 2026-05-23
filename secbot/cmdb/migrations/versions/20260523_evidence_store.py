"""add evidence store tables

Revision ID: 20260523_evidence_store
Revises: 20260510_report_meta
Create Date: 2026-05-23 00:00:00

Spec: .trellis/spec/backend/structured-blackboard.md §5
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260523_evidence_store"
down_revision: Union[str, None] = "20260510_report_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("source_tool", sa.String(), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("raw_ref", sa.String(), nullable=True),
        sa.Column("sanitised", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sensitive_keys", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_evidence_chat",
        "evidence_records",
        ["chat_id", "created_at"],
    )
    op.create_table(
        "evidence_finding_link",
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("finding_id", sa.String(), primary_key=True),
        sa.Column("link_role", sa.String(), nullable=False, server_default="primary"),
    )


def downgrade() -> None:
    op.drop_table("evidence_finding_link")
    op.drop_index("ix_evidence_chat", table_name="evidence_records")
    op.drop_table("evidence_records")
