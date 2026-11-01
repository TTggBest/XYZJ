"""Remember successful original-image downloads independently of copy progress."""
from alembic import op
import sqlalchemy as sa
revision = "f19c20261101"
down_revision = "f18b20261101"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_assets", sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("media_assets", "downloaded_at")
