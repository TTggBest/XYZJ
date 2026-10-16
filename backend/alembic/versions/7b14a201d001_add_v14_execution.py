"""Add fixed V14 configuration, runs and attempts; leave existing imports untouched."""
from alembic import op
import sqlalchemy as sa

revision = "7b14a201d001"
down_revision = "6a81c4d290fe"
branch_labels = depends_on = None


def common():
    return [sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("v14_settings", *common(), sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("tenant_id"))
    op.create_table("v14_runs", *common(),
        sa.Column("work_order_id", sa.String(36), nullable=False), sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("host_id", sa.String(36), nullable=False), sa.Column("account_profile", sa.String(120), nullable=False),
        sa.Column("model", sa.String(120), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("claim_id", sa.String(36)), sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("rules_snapshot", sa.JSON(), nullable=False), sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()), sa.UniqueConstraint("tenant_id", "work_order_id"), sa.UniqueConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id", "work_order_id"], ["work_orders.tenant_id", "work_orders.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "package_id"], ["operation_packages.tenant_id", "operation_packages.id"]),
        sa.CheckConstraint("status IN ('queued','running','interrupted','needs_user_review','cancelled','text_ready')", name="valid_status"))
    op.create_table("v14_attempts", *common(),
        sa.Column("run_id", sa.String(36), nullable=False), sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("node_type", sa.String(20), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False), sa.Column("payload", sa.JSON()), sa.Column("error", sa.Text()),
        sa.UniqueConstraint("run_id", "node_type", "sequence"),
        sa.ForeignKeyConstraint(["tenant_id", "run_id"], ["v14_runs.tenant_id", "v14_runs.id"]),
        sa.CheckConstraint("outcome IN ('running','accepted','content_error','system_error','interrupted')", name="valid_outcome"))


def downgrade():
    for table in ("v14_attempts", "v14_runs", "v14_settings"):
        op.drop_table(table)
