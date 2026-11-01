"""Persist the operator's shared channel order independently of Feishu catalog numbers."""
from alembic import op
import sqlalchemy as sa

revision = "f18b20261101"
down_revision = "f17a20261031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("sort_order", sa.SmallInteger(), nullable=True))


def downgrade():
    op.drop_column("channels", "sort_order")
