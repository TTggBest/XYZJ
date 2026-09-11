from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TimestampMixin


PLATFORM_ROLES = {"super_admin"}
MEMBERSHIP_ROLES = {"owner", "admin", "operator", "viewer"}
ACCOUNT_STATUSES = {"active", "suspended"}
SESSION_STATUSES = {"active", "revoked", "expired"}
BINDING_STATUSES = {"active", "suspended", "revoked"}


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended')", name="valid_status"),
        {"comment": "公司、客户和未来计费归属的主账号"},
    )

    company_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="公司全称")
    short_name: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, comment="主账号切换和列表简称"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="主账号状态"
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="主账号租约到期时间"
    )
    plan_code: Mapped[str | None] = mapped_column(String(60), comment="未来收费套餐代码")
    contact_name: Mapped[str | None] = mapped_column(String(120), comment="联系人姓名")
    contact_phone: Mapped[str | None] = mapped_column(String(40), comment="联系人电话")
    remark: Mapped[str | None] = mapped_column(Text, comment="主账号备注")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), comment="创建人用户ID"
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="停用时间")
    suspended_reason: Mapped[str | None] = mapped_column(String(500), comment="停用原因")


class AppUser(IdMixin, TimestampMixin, Base):
    __tablename__ = "app_users"
    __table_args__ = (
        CheckConstraint(
            "platform_role IS NULL OR platform_role IN ('super_admin')",
            name="valid_platform_role",
        ),
        CheckConstraint("status IN ('active','suspended')", name="valid_status"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonnegative"),
        Index("ix_app_users_login_status", "login_name", "status"),
        {"comment": "智矩管理系统登录用户"},
    )

    display_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="用户显示姓名")
    login_name: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, comment="唯一登录名"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Argon2id密码摘要"
    )
    platform_role: Mapped[str | None] = mapped_column(String(20), comment="平台角色，当前仅超级管理员")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="用户状态"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="用户独立租约到期时间，为空时继承主账号"
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="密码最后修改时间"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后登录时间")
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="连续登录失败次数"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="临时锁定截止时间")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), comment="创建人用户ID"
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="停用时间")
    suspended_reason: Mapped[str | None] = mapped_column(String(500), comment="停用原因")


class TenantMembership(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        CheckConstraint("role_code IN ('owner','admin','operator','viewer')", name="valid_role_code"),
        CheckConstraint("status IN ('active','suspended')", name="valid_status"),
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_pair"),
        Index("ix_tenant_memberships_user_status", "user_id", "status"),
        {"comment": "用户在主账号中的角色成员关系"},
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, comment="主账号ID"
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    role_code: Mapped[str] = mapped_column(String(20), nullable=False, comment="租户角色代码")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="成员关系状态"
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), comment="创建人用户ID"
    )


class Permission(IdMixin, TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = ({"comment": "稳定权限码目录"},)

    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, comment="稳定权限码")
    name_zh: Mapped[str] = mapped_column(String(120), nullable=False, comment="权限中文名称")


class RolePermission(IdMixin, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        CheckConstraint(
            "role_code IN ('super_admin','owner','admin','operator','viewer')",
            name="valid_role_code",
        ),
        UniqueConstraint("role_code", "permission_id", name="uq_role_permissions_pair"),
        {"comment": "基础角色与稳定权限码关系"},
    )

    role_code: Mapped[str] = mapped_column(String(20), nullable=False, comment="基础角色代码")
    permission_id: Mapped[str] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, comment="权限ID"
    )


class AuthSession(IdMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','revoked','expired')", name="valid_status"),
        Index("ix_auth_sessions_token_status", "token_digest", "status"),
        {"comment": "服务端认证会话"},
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), comment="当前主账号ID"
    )
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), comment="当前设备ID"
    )
    token_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="高熵会话令牌SHA-256摘要"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="会话状态"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="会话到期时间")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="最后使用时间")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="撤销时间")
    revoke_reason: Mapped[str | None] = mapped_column(String(500), comment="撤销原因")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")


class DeviceUserBinding(IdMixin, Base):
    __tablename__ = "device_user_bindings"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','revoked')", name="valid_status"),
        UniqueConstraint("device_id", "user_id", "tenant_id", name="uq_device_user_bindings_scope"),
        Index("ix_device_user_bindings_credential_status", "credential_digest", "status"),
        Index(
            "ix_device_user_bindings_device_active",
            "device_id",
            "status",
            "auto_login_enabled",
        ),
        {"comment": "指定设备、用户与主账号的免登录绑定"},
    )

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, comment="设备ID"
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, comment="主账号ID"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", comment="是否为设备默认账号"
    )
    auto_login_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="1", comment="是否允许免登录"
    )
    credential_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="设备秘密SHA-256摘要"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="绑定到期时间")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后使用时间")
    bound_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False, comment="执行绑定的用户ID"
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="绑定时间")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", comment="绑定状态"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="撤销时间")
    revoke_reason: Mapped[str | None] = mapped_column(String(500), comment="撤销原因")


class AuthEvent(IdMixin, Base):
    __tablename__ = "auth_events"
    __table_args__ = (
        CheckConstraint("result IN ('success','failure')", name="valid_result"),
        Index("ix_auth_events_actor_time", "actor_user_id", "occurred_at"),
        Index("ix_auth_events_tenant_time", "tenant_id", "occurred_at"),
        {"comment": "登录、会话、租户切换和设备绑定认证事件"},
    )

    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), comment="事件作用主账号ID"
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), comment="真实操作者用户ID"
    )
    actor_device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), comment="操作者设备ID"
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), comment="关联会话ID"
    )
    request_id: Mapped[str | None] = mapped_column(String(64), comment="请求追踪ID")
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="认证事件类型")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="认证事件结果")
    target_type: Mapped[str | None] = mapped_column(String(80), comment="操作目标类型")
    target_id: Mapped[str | None] = mapped_column(String(36), comment="操作目标ID")
    login_name: Mapped[str | None] = mapped_column(String(120), comment="登录尝试使用的登录名")
    detail: Mapped[str | None] = mapped_column(Text, comment="不含秘密的事件详情")
    reason: Mapped[str | None] = mapped_column(String(500), comment="失败或管理操作原因")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="事件发生时间")
