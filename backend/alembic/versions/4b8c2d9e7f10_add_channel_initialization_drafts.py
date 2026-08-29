"""add channel initialization drafts

Revision ID: 4b8c2d9e7f10
Revises: 31b7d5e8a2c4
Create Date: 2026-08-29 18:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "4b8c2d9e7f10"
down_revision = "31b7d5e8a2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_initialization_drafts",
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("channel_id", sa.String(length=36), nullable=False, comment="频道内部ID"),
        sa.Column("input_snapshot", sa.JSON(), nullable=False, comment="初始化输入快照"),
        sa.Column("output_draft", sa.JSON(), nullable=False, comment="初始化模块输出草稿"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], name=op.f("fk_channel_initialization_drafts_channel_id_channels"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_initialization_drafts")),
        sa.UniqueConstraint("channel_id", name="uq_channel_initialization_drafts_channel_id"),
        comment="频道初始化工作台草稿",
    )


def downgrade() -> None:
    op.drop_table("channel_initialization_drafts")
