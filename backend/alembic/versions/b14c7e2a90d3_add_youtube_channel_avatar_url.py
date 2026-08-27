"""add youtube channel avatar url

Revision ID: b14c7e2a90d3
Revises: 6d93f0a18c42
Create Date: 2026-08-27 15:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "b14c7e2a90d3"
down_revision = "6d93f0a18c42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("youtube_avatar_url", sa.String(1000), nullable=True, comment="YouTube频道当前头像地址"),
    )
    op.execute(
        sa.text(
            "REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) "
            "VALUES ('channels','youtube_avatar_url','YouTube频道当前头像地址',NOW())"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM schema_comments WHERE table_name='channels' AND column_name='youtube_avatar_url'"
        )
    )
    op.drop_column("channels", "youtube_avatar_url")
