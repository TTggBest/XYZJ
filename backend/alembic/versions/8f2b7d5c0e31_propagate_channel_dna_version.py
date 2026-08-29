"""propagate channel dna version

Revision ID: 8f2b7d5c0e31
Revises: 7e1a6c4b9d20
Create Date: 2026-08-29 21:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "8f2b7d5c0e31"
down_revision = "7e1a6c4b9d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_schedule_entries",
        sa.Column("channel_dna_version_id", sa.String(length=36), nullable=True, comment="创建排期时采用的频道运营参考版本ID"),
    )
    op.create_foreign_key(
        "fk_schedule_channel_dna_version",
        "channel_schedule_entries",
        "channel_dna_versions",
        ["channel_dna_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "work_orders",
        sa.Column("channel_dna_version_id", sa.String(length=36), nullable=True, comment="工单继承的频道运营参考版本ID"),
    )
    op.create_foreign_key(
        "fk_work_order_channel_dna_version",
        "work_orders",
        "channel_dna_versions",
        ["channel_dna_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_work_order_channel_dna_version", "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "channel_dna_version_id")
    op.drop_constraint("fk_schedule_channel_dna_version", "channel_schedule_entries", type_="foreignkey")
    op.drop_column("channel_schedule_entries", "channel_dna_version_id")
