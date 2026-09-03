"""记录排期视频信息的人工覆盖状态。

Revision ID: 6f3a2c9d1e40
Revises: 3a6c9e1f2b40
"""

from alembic import op
import sqlalchemy as sa


revision = "6f3a2c9d1e40"
down_revision = "3a6c9e1f2b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_schedule_entries",
        sa.Column(
            "source_video_overridden",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="视频信息是否已在智矩人工修改",
        ),
    )


def downgrade() -> None:
    op.drop_column("channel_schedule_entries", "source_video_overridden")
