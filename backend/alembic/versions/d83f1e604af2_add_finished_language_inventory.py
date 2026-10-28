"""Store authoritative per-language final-compose inventory from Zhihe."""
from alembic import op
import sqlalchemy as sa

revision = "d83f1e604af2"
down_revision = "c72a10b01500"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("drama_production_states", sa.Column("finished_languages", sa.JSON(none_as_null=True),
        nullable=True, comment="智核正式逐语言最终合成完成清单；NULL表示尚未同步，空数组表示无完成语言"))


def downgrade():
    op.drop_column("drama_production_states", "finished_languages")
