"""Store complete tenant workflow Skills versions; preserve existing runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGBLOB

revision = 'c72a10b01500'
down_revision = 'a16c2d9e4107'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workflow_skill_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('change_summary', sa.Text(), nullable=False),
        sa.Column('archive', sa.LargeBinary().with_variant(LONGBLOB(), 'mysql'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'label', 'revision', name='uq_workflow_skill_revision'),
        sa.CheckConstraint("status IN ('draft','published')", name='workflow_skill_status'),
    )
    op.create_index('ix_workflow_skill_versions_tenant_id', 'workflow_skill_versions', ['tenant_id'])


def downgrade():
    op.drop_table('workflow_skill_versions')
