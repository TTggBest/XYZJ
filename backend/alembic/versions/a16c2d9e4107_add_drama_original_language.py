"""Map the independent original language field, preserving existing backfill."""
from alembic import op
import sqlalchemy as sa

revision = "a16c2d9e4107"
down_revision = "9d25a201d003"
branch_labels = None
depends_on = None


def upgrade():
    # Production already received this column and 157 user-confirmed values.
    # Other installations still need the same nullable, non-defaulted field.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("dramas")}
    if "source_language" not in columns:
        op.add_column("dramas", sa.Column("source_language", sa.String(10), nullable=True,
                                        comment="原始语言：zh中文原片，en英语原片；未确认留空"))


def downgrade():
    op.drop_column("dramas", "source_language")
