"""Add fixed V14 configuration, runs and attempts; leave existing imports untouched."""
from alembic import op
import sqlalchemy as sa

revision = "7b14a201d001"
down_revision = "6a81c4d290fe"
branch_labels = depends_on = None


def common():
    return [sa.Column("id", sa.String(36), primary_key=True, comment="记录内部ID"),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True, comment="所属公司ID"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="更新时间")]


def upgrade():
    op.create_table("v14_settings", *common(), sa.Column("payload", sa.JSON(), nullable=False, comment="配置或阶段结构化内容"), sa.UniqueConstraint("tenant_id"))
    op.create_table("v14_runs", *common(),
        sa.Column("work_order_id", sa.String(36), nullable=False, comment="智矩工单ID"), sa.Column("package_id", sa.String(36), nullable=False, comment="关联运营包ID"),
        sa.Column("host_id", sa.String(36), nullable=False, comment="绑定执行主机ID"), sa.Column("account_profile", sa.String(120), nullable=False, comment="本机Codex账号配置引用"),
        sa.Column("model", sa.String(120), nullable=False, comment="本次固定模型"), sa.Column("status", sa.String(30), nullable=False, comment="运行状态"),
        sa.Column("claim_id", sa.String(36), comment="本次领取ID"), sa.Column("input_snapshot", sa.JSON(), nullable=False, comment="冻结的业务输入"),
        sa.Column("rules_snapshot", sa.JSON(), nullable=False, comment="冻结的V14规则"), sa.Column("heartbeat_at", sa.DateTime(timezone=True), comment="执行器最近心跳"),
        sa.Column("error", sa.Text(), comment="错误与修复反馈"), sa.UniqueConstraint("tenant_id", "work_order_id"), sa.UniqueConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id", "work_order_id"], ["work_orders.tenant_id", "work_orders.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "package_id"], ["operation_packages.tenant_id", "operation_packages.id"]),
        sa.CheckConstraint("status IN ('queued','running','interrupted','needs_user_review','cancelled','text_ready')", name="valid_status"))
    op.create_table("v14_attempts", *common(),
        sa.Column("run_id", sa.String(36), nullable=False, comment="所属V14运行ID"), sa.Column("claim_id", sa.String(36), nullable=False, comment="本次领取ID"),
        sa.Column("node_type", sa.String(20), nullable=False, comment="生产阶段"), sa.Column("sequence", sa.Integer(), nullable=False, comment="该阶段调用序号"),
        sa.Column("outcome", sa.String(20), nullable=False, comment="本次尝试结果类型"), sa.Column("payload", sa.JSON(), comment="配置或阶段结构化内容"), sa.Column("raw_payload", sa.JSON(), comment="模型原始完整响应"), sa.Column("error", sa.Text(), comment="错误与修复反馈"),
        sa.UniqueConstraint("run_id", "node_type", "sequence"),
        sa.ForeignKeyConstraint(["tenant_id", "run_id"], ["v14_runs.tenant_id", "v14_runs.id"]),
        sa.CheckConstraint("outcome IN ('running','accepted','content_error','system_error','interrupted')", name="valid_outcome"))


def downgrade():
    for table in ("v14_attempts", "v14_runs", "v14_settings"):
        op.drop_table(table)
