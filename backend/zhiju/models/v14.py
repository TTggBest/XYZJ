"""Fixed V14 execution state. Existing Feishu models are deliberately unchanged."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKeyConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, LargeBinary
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TenantOwnedMixin, TimestampMixin


class WorkflowSkillVersion(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = 'workflow_skill_versions'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'label', 'revision', name='uq_workflow_skill_revision'),
        CheckConstraint("status IN ('draft','published')", name='workflow_skill_status'),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='draft')
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default='')
    archive: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), 'mysql'), nullable=False)


class V14Setting(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "v14_settings"
    __table_args__ = (UniqueConstraint("tenant_id"),)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, comment="配置或阶段结构化内容")


class V14Run(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "v14_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "work_order_id", name="uq_v14_runs_tenant_work_order"),
        UniqueConstraint("tenant_id", "id", name="uq_v14_runs_tenant_id_id"),
        ForeignKeyConstraint(["tenant_id", "work_order_id"], ["work_orders.tenant_id", "work_orders.id"]),
        ForeignKeyConstraint(["tenant_id", "package_id"], ["operation_packages.tenant_id", "operation_packages.id"]),
        CheckConstraint("status IN ('queued','running','interrupted','needs_user_review','cancelled','text_ready')", name="valid_status"),
    )
    work_order_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="智矩工单ID")
    package_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="关联运营包ID")
    host_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="绑定执行主机ID")
    account_profile: Mapped[str] = mapped_column(String(120), nullable=False, comment="本机Codex账号配置引用")
    model: Mapped[str] = mapped_column(String(120), nullable=False, comment="本次固定模型")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", comment="运行状态")
    claim_id: Mapped[str | None] = mapped_column(String(36), comment="本次领取ID")
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, comment="冻结的业务输入")
    rules_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, comment="冻结的V14规则")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="执行器最近心跳")
    error: Mapped[str | None] = mapped_column(Text, comment="错误与修复反馈")


class V14Attempt(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "v14_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "run_id"], ["v14_runs.tenant_id", "v14_runs.id"]),
        UniqueConstraint("run_id", "node_type", "sequence"),
        CheckConstraint("outcome IN ('running','accepted','content_error','system_error','interrupted')", name="valid_outcome"),
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="所属V14运行ID")
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="本次领取ID")
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="生产阶段")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="该阶段调用序号")
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="running", comment="本次尝试结果类型")
    payload: Mapped[dict | None] = mapped_column(JSON, comment="配置或阶段结构化内容")
    raw_payload: Mapped[dict | None] = mapped_column(JSON, comment="模型原始完整响应")
    error: Mapped[str | None] = mapped_column(Text, comment="错误与修复反馈")
