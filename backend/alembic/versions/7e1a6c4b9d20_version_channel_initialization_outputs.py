"""version channel initialization outputs

Revision ID: 7e1a6c4b9d20
Revises: 4b8c2d9e7f10
Create Date: 2026-08-29 20:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "7e1a6c4b9d20"
down_revision = "4b8c2d9e7f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_dna_versions",
        sa.Column("reference_summary", sa.Text(), nullable=True, comment="频道运营包参考"),
    )
    op.add_column(
        "channel_initialization_drafts",
        sa.Column("applied_report_id", sa.String(length=36), nullable=True, comment="已应用的初始分析报告ID"),
    )
    op.add_column(
        "channel_initialization_drafts",
        sa.Column("applied_dna_version_id", sa.String(length=36), nullable=True, comment="已应用的频道运营参考版本ID"),
    )
    op.add_column(
        "channel_initialization_drafts",
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True, comment="最近应用时间"),
    )
    op.create_foreign_key(
        "fk_channel_init_draft_report",
        "channel_initialization_drafts",
        "channel_analysis_reports",
        ["applied_report_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_channel_init_draft_dna",
        "channel_initialization_drafts",
        "channel_dna_versions",
        ["applied_dna_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_channel_init_draft_dna",
        "channel_initialization_drafts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_channel_init_draft_report",
        "channel_initialization_drafts",
        type_="foreignkey",
    )
    op.drop_column("channel_initialization_drafts", "applied_at")
    op.drop_column("channel_initialization_drafts", "applied_dna_version_id")
    op.drop_column("channel_initialization_drafts", "applied_report_id")
    op.drop_column("channel_dna_versions", "reference_summary")
