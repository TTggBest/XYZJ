"""Independent channel analysis jobs, sharing the existing bound Codex host."""
from alembic import op
import sqlalchemy as sa

revision = 'e94a1c729b30'
down_revision = 'd83f1e604af2'
branch_labels = depends_on = None


def upgrade():
    op.create_table('channel_analysis_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('channel_id', sa.String(36), nullable=False),
        sa.Column('host_id', sa.String(36), nullable=False),
        sa.Column('mode', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('phase', sa.String(40), nullable=False),
        sa.Column('claim_id', sa.String(36)),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True)),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('materials', sa.JSON(), nullable=False),
        sa.Column('attempts', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON()), sa.Column('error', sa.Text()),
        sa.Column('report_id', sa.String(36)), sa.Column('dna_id', sa.String(36)),
        sa.Column('mirror_status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_channel_analysis_runs_tenant_id_id'),
        sa.ForeignKeyConstraint(['tenant_id','channel_id'], ['channels.tenant_id','channels.id']))
    op.create_index('ix_channel_analysis_runs_queue', 'channel_analysis_runs', ['tenant_id','status','host_id'])
    op.create_index('ix_channel_analysis_runs_tenant_id', 'channel_analysis_runs', ['tenant_id'])


def downgrade():
    op.drop_table('channel_analysis_runs')
