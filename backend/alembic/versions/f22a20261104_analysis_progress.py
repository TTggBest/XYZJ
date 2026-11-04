"""Persist small execution progress independently of frozen source data."""
from alembic import op
import sqlalchemy as sa
revision = 'f22a20261104'
down_revision = 'f21e20261102'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('channel_analysis_runs', sa.Column('progress', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('channel_analysis_runs', 'progress')
