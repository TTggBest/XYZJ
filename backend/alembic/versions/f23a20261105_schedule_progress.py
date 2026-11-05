"""Persist scheduling execution progress outside frozen story snapshots."""
from alembic import op
import sqlalchemy as sa
revision='f23a20261105'
down_revision='f22a20261104'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('channel_schedule_plans',sa.Column('progress',sa.JSON(),nullable=True))
    op.create_table('executor_claims',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),nullable=False),
        sa.Column('task_type',sa.String(40),nullable=False),sa.Column('run_id',sa.String(36),nullable=False),
        sa.Column('host_id',sa.String(36),nullable=False),sa.Column('claim_id',sa.String(36),nullable=False),
        sa.Column('released_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('tenant_id','claim_id'))
    op.create_index('ix_executor_claims_capacity','executor_claims',['tenant_id','released_at'])


def downgrade():
    op.drop_table('executor_claims')
    op.drop_column('channel_schedule_plans','progress')
