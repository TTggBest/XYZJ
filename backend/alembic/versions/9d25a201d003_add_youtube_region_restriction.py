"""Keep the latest YouTube region restriction independently of manual bans."""
from alembic import op
import sqlalchemy as sa

revision = "9d25a201d003"
down_revision = "8c14a201d002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("youtube_videos", sa.Column("region_restriction", sa.JSON(), nullable=True,
                                            comment="YouTube当前地区屏蔽或允许范围"))


def downgrade():
    op.drop_column("youtube_videos", "region_restriction")
