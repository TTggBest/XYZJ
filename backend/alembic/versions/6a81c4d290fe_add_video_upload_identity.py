"""Store owner-visible upload identity for schedule matching."""
from alembic import op
import sqlalchemy as sa

revision = "6a81c4d290fe"
down_revision = "0d7a4c9e12f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("youtube_videos", sa.Column("original_file_name", sa.String(1000), nullable=True))
    op.add_column("youtube_videos", sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("youtube_videos", sa.Column("upload_status", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("youtube_videos", "upload_status")
    op.drop_column("youtube_videos", "uploaded_at")
    op.drop_column("youtube_videos", "original_file_name")
