"""add Feishu channel schedule fields

Revision ID: e7b9c4a2d615
Revises: c3f8a1b7d902
Create Date: 2026-08-29 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "e7b9c4a2d615"
down_revision = "c3f8a1b7d902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_schedule_entries",
        sa.Column("source_type", sa.String(length=20), server_default="manual", nullable=False, comment="排期来源"),
    )
    op.add_column("channel_schedule_entries", sa.Column("source_sheet_id", sa.String(length=40), nullable=True, comment="来源飞书工作表ID"))
    op.add_column("channel_schedule_entries", sa.Column("source_row_number", sa.Integer(), nullable=True, comment="来源飞书原始行号"))
    op.add_column("channel_schedule_entries", sa.Column("source_synced_at", mysql.DATETIME(fsp=6), nullable=True, comment="最后一次飞书同步时间"))
    op.add_column("channel_schedule_entries", sa.Column("source_video_id", sa.String(length=32), nullable=True, comment="来源视频ID"))
    op.add_column("channel_schedule_entries", sa.Column("source_video_url", sa.String(length=1000), nullable=True, comment="来源视频地址"))
    op.add_column("channel_schedule_entries", sa.Column("is_uploaded", sa.Boolean(), server_default=sa.false(), nullable=False, comment="是否已上传"))
    op.add_column("channel_schedule_entries", sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False, comment="是否已上线"))
    op.add_column("channel_schedule_entries", sa.Column("is_task_written", sa.Boolean(), server_default=sa.false(), nullable=False, comment="是否已写入任务"))
    op.create_check_constraint(
        "ck_channel_schedule_entries_valid_source_type",
        "channel_schedule_entries",
        "source_type IN ('manual','feishu','system')",
    )
    op.create_index(
        "ix_schedule_entries_source_row",
        "channel_schedule_entries",
        ["source_sheet_id", "source_row_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_schedule_entries_source_row", table_name="channel_schedule_entries")
    op.drop_constraint("ck_channel_schedule_entries_valid_source_type", "channel_schedule_entries", type_="check")
    op.drop_column("channel_schedule_entries", "is_task_written")
    op.drop_column("channel_schedule_entries", "is_published")
    op.drop_column("channel_schedule_entries", "is_uploaded")
    op.drop_column("channel_schedule_entries", "source_video_url")
    op.drop_column("channel_schedule_entries", "source_video_id")
    op.drop_column("channel_schedule_entries", "source_synced_at")
    op.drop_column("channel_schedule_entries", "source_row_number")
    op.drop_column("channel_schedule_entries", "source_sheet_id")
    op.drop_column("channel_schedule_entries", "source_type")
