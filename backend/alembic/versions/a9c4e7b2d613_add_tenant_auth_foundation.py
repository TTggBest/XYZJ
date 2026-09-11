"""add tenant auth foundation

Revision ID: a9c4e7b2d613
Revises: 6f3a2c9d1e40
Create Date: 2026-09-11 13:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c4e7b2d613"
down_revision: Union[str, None] = "6f3a2c9d1e40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "trust_level",
            sa.String(length=30),
            server_default="normal",
            nullable=False,
            comment="设备信任等级",
        ),
    )
    op.create_check_constraint(
        op.f("ck_devices_valid_trust_level"),
        "devices",
        "trust_level IN ('super_code_machine','code_machine','production_device','normal')",
    )

    op.create_table(
        "app_users",
        sa.Column("display_name", sa.String(length=120), nullable=False, comment="用户显示姓名"),
        sa.Column("login_name", sa.String(length=120), nullable=False, comment="唯一登录名"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="Argon2id密码摘要"),
        sa.Column("platform_role", sa.String(length=20), nullable=True, comment="平台角色，当前仅超级管理员"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="用户状态"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True, comment="用户独立租约到期时间，为空时继承主账号"),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, comment="密码最后修改时间"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True, comment="最后登录时间"),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False, comment="连续登录失败次数"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True, comment="临时锁定截止时间"),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True, comment="创建人用户ID"),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True, comment="停用时间"),
        sa.Column("suspended_reason", sa.String(length=500), nullable=True, comment="停用原因"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("failed_login_count >= 0", name=op.f("ck_app_users_failed_login_count_nonnegative")),
        sa.CheckConstraint("platform_role IS NULL OR platform_role IN ('super_admin')", name=op.f("ck_app_users_valid_platform_role")),
        sa.CheckConstraint("status IN ('active','suspended')", name=op.f("ck_app_users_valid_status")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], name=op.f("fk_app_users_created_by_user_id_app_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_users")),
        sa.UniqueConstraint("login_name", name=op.f("uq_app_users_login_name")),
        comment="智矩管理系统登录用户",
    )
    op.create_index("ix_app_users_login_status", "app_users", ["login_name", "status"], unique=False)

    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=120), nullable=False, comment="稳定权限码"),
        sa.Column("name_zh", sa.String(length=120), nullable=False, comment="权限中文名称"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("code", name=op.f("uq_permissions_code")),
        comment="稳定权限码目录",
    )

    op.create_table(
        "tenants",
        sa.Column("company_name", sa.String(length=255), nullable=False, comment="公司全称"),
        sa.Column("short_name", sa.String(length=120), nullable=False, comment="主账号切换和列表简称"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="主账号状态"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False, comment="主账号租约到期时间"),
        sa.Column("plan_code", sa.String(length=60), nullable=True, comment="未来收费套餐代码"),
        sa.Column("contact_name", sa.String(length=120), nullable=True, comment="联系人姓名"),
        sa.Column("contact_phone", sa.String(length=40), nullable=True, comment="联系人电话"),
        sa.Column("remark", sa.Text(), nullable=True, comment="主账号备注"),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True, comment="创建人用户ID"),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True, comment="停用时间"),
        sa.Column("suspended_reason", sa.String(length=500), nullable=True, comment="停用原因"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("status IN ('active','suspended')", name=op.f("ck_tenants_valid_status")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], name=op.f("fk_tenants_created_by_user_id_app_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("short_name", name=op.f("uq_tenants_short_name")),
        comment="公司、客户和未来计费归属的主账号",
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_code", sa.String(length=20), nullable=False, comment="基础角色代码"),
        sa.Column("permission_id", sa.String(length=36), nullable=False, comment="权限ID"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("role_code IN ('super_admin','owner','admin','operator','viewer')", name=op.f("ck_role_permissions_valid_role_code")),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], name=op.f("fk_role_permissions_permission_id_permissions"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_permissions")),
        sa.UniqueConstraint("role_code", "permission_id", name="uq_role_permissions_pair"),
        comment="基础角色与稳定权限码关系",
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="主账号ID"),
        sa.Column("user_id", sa.String(length=36), nullable=False, comment="用户ID"),
        sa.Column("role_code", sa.String(length=20), nullable=False, comment="租户角色代码"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="成员关系状态"),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True, comment="创建人用户ID"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="最后更新时间"),
        sa.CheckConstraint("role_code IN ('owner','admin','operator','viewer')", name=op.f("ck_tenant_memberships_valid_role_code")),
        sa.CheckConstraint("status IN ('active','suspended')", name=op.f("ck_tenant_memberships_valid_status")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_users.id"], name=op.f("fk_tenant_memberships_created_by_user_id_app_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_tenant_memberships_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name=op.f("fk_tenant_memberships_user_id_app_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_memberships")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_pair"),
        comment="用户在主账号中的角色成员关系",
    )
    op.create_index("ix_tenant_memberships_user_status", "tenant_memberships", ["user_id", "status"], unique=False)

    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.String(length=36), nullable=False, comment="用户ID"),
        sa.Column("tenant_id", sa.String(length=36), nullable=True, comment="当前主账号ID"),
        sa.Column("device_id", sa.String(length=36), nullable=True, comment="当前设备ID"),
        sa.Column("token_digest", sa.String(length=64), nullable=False, comment="高熵会话令牌SHA-256摘要"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="会话状态"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="会话到期时间"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, comment="最后使用时间"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True, comment="撤销时间"),
        sa.Column("revoke_reason", sa.String(length=500), nullable=True, comment="撤销原因"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.CheckConstraint("status IN ('active','revoked','expired')", name=op.f("ck_auth_sessions_valid_status")),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name=op.f("fk_auth_sessions_device_id_devices"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_auth_sessions_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name=op.f("fk_auth_sessions_user_id_app_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_auth_sessions_token_digest")),
        comment="服务端认证会话",
    )
    op.create_index("ix_auth_sessions_token_status", "auth_sessions", ["token_digest", "status"], unique=False)

    op.create_table(
        "device_user_bindings",
        sa.Column("device_id", sa.String(length=36), nullable=False, comment="设备ID"),
        sa.Column("user_id", sa.String(length=36), nullable=False, comment="用户ID"),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="主账号ID"),
        sa.Column("is_default", sa.Boolean(), server_default="0", nullable=False, comment="是否为设备默认账号"),
        sa.Column("auto_login_enabled", sa.Boolean(), server_default="1", nullable=False, comment="是否允许免登录"),
        sa.Column("credential_digest", sa.String(length=64), nullable=False, comment="设备秘密SHA-256摘要"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="绑定到期时间"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True, comment="最后使用时间"),
        sa.Column("bound_by_user_id", sa.String(length=36), nullable=False, comment="执行绑定的用户ID"),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False, comment="绑定时间"),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False, comment="绑定状态"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True, comment="撤销时间"),
        sa.Column("revoke_reason", sa.String(length=500), nullable=True, comment="撤销原因"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.CheckConstraint("status IN ('active','suspended','revoked')", name=op.f("ck_device_user_bindings_valid_status")),
        sa.ForeignKeyConstraint(["bound_by_user_id"], ["app_users.id"], name=op.f("fk_device_user_bindings_bound_by_user_id_app_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name=op.f("fk_device_user_bindings_device_id_devices"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_device_user_bindings_tenant_id_tenants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name=op.f("fk_device_user_bindings_user_id_app_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_user_bindings")),
        sa.UniqueConstraint("credential_digest", name=op.f("uq_device_user_bindings_credential_digest")),
        sa.UniqueConstraint("device_id", "user_id", "tenant_id", name="uq_device_user_bindings_scope"),
        comment="指定设备、用户与主账号的免登录绑定",
    )
    op.create_index("ix_device_user_bindings_credential_status", "device_user_bindings", ["credential_digest", "status"], unique=False)
    op.create_index(
        "ix_device_user_bindings_device_active",
        "device_user_bindings",
        ["device_id", "status", "auto_login_enabled"],
        unique=False,
    )

    op.create_table(
        "auth_events",
        sa.Column("tenant_id", sa.String(length=36), nullable=True, comment="事件作用主账号ID"),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True, comment="真实操作者用户ID"),
        sa.Column("actor_device_id", sa.String(length=36), nullable=True, comment="操作者设备ID"),
        sa.Column("session_id", sa.String(length=36), nullable=True, comment="关联会话ID"),
        sa.Column("request_id", sa.String(length=64), nullable=True, comment="请求追踪ID"),
        sa.Column("event_type", sa.String(length=60), nullable=False, comment="认证事件类型"),
        sa.Column("result", sa.String(length=20), nullable=False, comment="认证事件结果"),
        sa.Column("target_type", sa.String(length=80), nullable=True, comment="操作目标类型"),
        sa.Column("target_id", sa.String(length=36), nullable=True, comment="操作目标ID"),
        sa.Column("login_name", sa.String(length=120), nullable=True, comment="登录尝试使用的登录名"),
        sa.Column("detail", sa.Text(), nullable=True, comment="不含秘密的事件详情"),
        sa.Column("reason", sa.String(length=500), nullable=True, comment="失败或管理操作原因"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, comment="事件发生时间"),
        sa.Column("id", sa.String(length=36), nullable=False, comment="系统内部稳定主键"),
        sa.CheckConstraint("result IN ('success','failure')", name=op.f("ck_auth_events_valid_result")),
        sa.ForeignKeyConstraint(["actor_device_id"], ["devices.id"], name=op.f("fk_auth_events_actor_device_id_devices"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_users.id"], name=op.f("fk_auth_events_actor_user_id_app_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], name=op.f("fk_auth_events_session_id_auth_sessions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_auth_events_tenant_id_tenants"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_events")),
        comment="登录、会话、租户切换和设备绑定认证事件",
    )
    op.create_index("ix_auth_events_actor_time", "auth_events", ["actor_user_id", "occurred_at"], unique=False)
    op.create_index("ix_auth_events_tenant_time", "auth_events", ["tenant_id", "occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_table("auth_events")
    op.drop_table("device_user_bindings")
    op.drop_table("auth_sessions")
    op.drop_table("tenant_memberships")
    op.drop_table("role_permissions")
    op.drop_table("tenants")
    op.drop_table("permissions")
    op.drop_table("app_users")
    op.drop_constraint(op.f("ck_devices_valid_trust_level"), "devices", type_="check")
    op.drop_column("devices", "trust_level")
