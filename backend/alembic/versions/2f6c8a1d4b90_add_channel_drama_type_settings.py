"""add channel drama type settings

Revision ID: 2f6c8a1d4b90
Revises: d4a7f9c2e610
Create Date: 2026-08-29 15:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2f6c8a1d4b90"
down_revision = "d4a7f9c2e610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_drama_types",
        sa.Column("code", sa.String(length=80), nullable=False, comment="稳定编码"),
        sa.Column("name", sa.String(length=120), nullable=False, comment="显示名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="业务说明"),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False, comment="显示顺序"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="配置状态"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_channel_drama_types_sort_order_nonnegative")),
        sa.CheckConstraint("status IN ('active','disabled')", name=op.f("ck_channel_drama_types_valid_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_drama_types")),
        sa.UniqueConstraint("code", name=op.f("uq_channel_drama_types_code")),
        sa.UniqueConstraint("name", name=op.f("uq_channel_drama_types_name")),
        comment="频道短剧类型可编辑配置",
    )
    op.create_index(
        "ix_channel_drama_types_status_sort",
        "channel_drama_types",
        ["status", "sort_order"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO channel_drama_types
                (id, code, name, description, sort_order, status, created_at, updated_at)
            SELECT UUID(), drama_type, drama_type, NULL,
                   ROW_NUMBER() OVER (ORDER BY drama_type), 'active', NOW(), NOW()
            FROM (SELECT DISTINCT TRIM(drama_type) AS drama_type
                  FROM channels
                  WHERE drama_type IS NOT NULL AND TRIM(drama_type) <> '') AS existing_types
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_channel_drama_types_status_sort", table_name="channel_drama_types")
    op.drop_table("channel_drama_types")
