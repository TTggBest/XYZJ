"""AI schedule previews, frozen inputs and atomic application."""
from alembic import op
import sqlalchemy as sa
revision = 'f21e20261102'
down_revision = 'f20d20261102'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('channel_schedule_plans',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),nullable=True),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('channel_id',sa.String(36),nullable=False),
        sa.Column('host_id',sa.String(36),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('dna_id',sa.String(36)),
        sa.Column('claim_id',sa.String(36)),sa.Column('heartbeat_at',sa.DateTime(timezone=True)),
        sa.Column('input_snapshot',sa.JSON(),nullable=False),sa.Column('result',sa.JSON()),sa.Column('error',sa.Text()),
        sa.ForeignKeyConstraint(['tenant_id','channel_id'],['channels.tenant_id','channels.id']))
    op.create_index('ix_channel_schedule_plans_tenant_id','channel_schedule_plans',['tenant_id'])
    op.create_index('ix_channel_schedule_plans_queue','channel_schedule_plans',['tenant_id','host_id','status'])


def downgrade():
    op.drop_table('channel_schedule_plans')
