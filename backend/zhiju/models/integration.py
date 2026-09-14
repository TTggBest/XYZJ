from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
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


class YouTubeChannelImportSession(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_channel_import_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_oauth','ready','committed','cancelled','expired')",
            name="valid_status",
        ),
        UniqueConstraint("opaque_state", name="uq_youtube_channel_import_sessions_state"),
        Index("ix_youtube_channel_import_sessions_expiry", "status", "expires_at"),
        {"comment": "云端YouTube频道授权导入会话"},
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), index=True, nullable=False, comment="所属主账号ID",
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, comment="发起用户ID",
    )
    auth_session_id: Mapped[str] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, comment="发起登录会话ID",
    )
    oauth_grant_id: Mapped[str | None] = mapped_column(
        String(36), comment="回调完成后的Google OAuth授权ID",
    )
    opaque_state: Mapped[str] = mapped_column(String(128), nullable=False, comment="一次性OAuth state")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending_oauth")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class YouTubeChannelImportCandidate(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_channel_import_candidates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "import_session_id", "youtube_channel_id",
            name="uq_youtube_import_candidates_session_channel",
        ),
        {"comment": "YouTube授权后发现的待导入频道快照"},
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), index=True, nullable=False, comment="所属主账号ID",
    )
    import_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    custom_url: Mapped[str | None] = mapped_column(String(500))
    youtube_country_code: Mapped[str | None] = mapped_column(String(2))
    youtube_default_language: Mapped[str | None] = mapped_column(String(20))
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(64))


class OAuthTokenSecret(TenantOwnedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "oauth_token_secrets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "oauth_grant_id", name="uq_oauth_token_secrets_tenant_grant",
        ),
        {"comment": "云端Google OAuth令牌密文"},
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), index=True, nullable=False, comment="所属主账号ID",
    )
    oauth_grant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


configure_tenant_relations(
    (
        ("integration_credentials", "integration_account_id", "integration_accounts", "CASCADE"),
        ("oauth_authorization_states", "channel_id", "channels", "CASCADE"),
        ("youtube_channel_import_sessions", "oauth_grant_id", "google_oauth_grants", "CASCADE"),
        (
            "youtube_channel_import_candidates", "import_session_id",
            "youtube_channel_import_sessions", "CASCADE",
        ),
        ("oauth_token_secrets", "oauth_grant_id", "google_oauth_grants", "CASCADE"),
    ),
    parent_tables=("integration_accounts", "youtube_channel_import_sessions"),
)
