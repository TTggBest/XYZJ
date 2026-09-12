from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TenantOwnedMixin, TimestampMixin, configure_tenant_relations


class Integration(IdMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled','deprecated')", name="valid_status"),
        {"comment": "第三方服务类型定义"},
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, comment="系统内稳定集成代码")
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="集成显示名称")
    provider_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="服务提供方类型")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="集成状态")


class IntegrationAccount(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','expired','revoked','error','disabled')", name="valid_status"),
        UniqueConstraint("tenant_id", "integration_id", "account_key", name="uq_integration_accounts_tenant_key"),
        Index("ix_integration_accounts_integration_status", "integration_id", "status"),
        {"comment": "第三方服务中的具体账号"},
    )

    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id", ondelete="RESTRICT"), nullable=False, comment="第三方集成ID")
    account_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="系统内账号稳定标识")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="账号显示名称")
    external_account_id: Mapped[str | None] = mapped_column(String(255), comment="第三方平台账号ID")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="账号连接状态")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后验证时间")


class IntegrationCredential(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        CheckConstraint("status IN ('active','expired','revoked','error')", name="valid_status"),
        UniqueConstraint(
            "tenant_id", "integration_account_id", "credential_type",
            name="uq_integration_credentials_tenant_type",
        ),
        Index("ix_integration_credentials_account_status", "integration_account_id", "status"),
        {"comment": "第三方账号凭证引用，禁止保存密钥明文"},
    )

    integration_account_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="第三方账号ID")
    credential_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="凭证类型")
    secret_reference: Mapped[str] = mapped_column(String(500), nullable=False, comment="外部Secret存储引用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="凭证状态")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="凭证失效时间")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后验证时间")


class OAuthAuthorizationState(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "oauth_authorization_states"
    __table_args__ = (
        UniqueConstraint("opaque_state", name="uq_oauth_authorization_states_opaque"),
        Index("ix_oauth_authorization_states_expiry", "expires_at", "consumed_at"),
        {"comment": "一次性OAuth授权上下文"},
    )

    opaque_state: Mapped[str] = mapped_column(String(128), nullable=False, comment="不透明state")
    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, comment="发起授权的用户ID",
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, comment="发起授权的会话ID",
    )
    channel_id: Mapped[str] = mapped_column(
        nullable=False, comment="待授权频道ID",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="授权状态过期时间",
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="授权状态消费时间",
    )


configure_tenant_relations(
    (
        ("integration_credentials", "integration_account_id", "integration_accounts", "CASCADE"),
        ("oauth_authorization_states", "channel_id", "channels", "CASCADE"),
    ),
    parent_tables=("integration_accounts",),
)
