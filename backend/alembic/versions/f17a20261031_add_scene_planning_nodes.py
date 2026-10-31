"""Allow V17 scene planning nodes in the existing production-node table."""
from alembic import op

revision = 'f17a20261031'
down_revision = 'e94a1c729b30'
branch_labels = None
depends_on = None


def _replace(expression):
    name = op.f('ck_production_node_runs_valid_node_type')
    with op.batch_alter_table('production_node_runs') as batch:
        batch.drop_constraint(name, type_='check')
        batch.create_check_constraint(name, expression)


def upgrade():
    _replace("node_type IN ('search','title','cover_scene','cover','description','community_scene','community','merge')")


def downgrade():
    _replace("node_type IN ('search','title','cover','description','community','merge')")
