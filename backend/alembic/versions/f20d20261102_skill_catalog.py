"""Categorized complete Skill bundles; production archives stay in place."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGBLOB
revision='f20d20261102'
down_revision='f19c20261101'
branch_labels=None
depends_on=None

def common():
    return [sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),nullable=True,index=True),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False)]

def upgrade():
    op.create_table('skill_categories',*common(),sa.Column('name',sa.String(80),nullable=False),sa.Column('description',sa.Text(),nullable=False),sa.Column('default_version_id',sa.String(36)),sa.UniqueConstraint('tenant_id','name'))
    op.create_table('skill_bundle_versions',*common(),sa.Column('category_id',sa.String(36),nullable=False,index=True),sa.Column('label',sa.String(80),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('change_summary',sa.Text(),nullable=False),sa.Column('archive',sa.LargeBinary().with_variant(LONGBLOB(),'mysql'),nullable=False),sa.UniqueConstraint('tenant_id','category_id','label','revision'))

def downgrade():
    op.drop_table('skill_bundle_versions')
    op.drop_table('skill_categories')
