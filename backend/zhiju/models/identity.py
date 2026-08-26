from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import DATETIME

from zhiju.models.base import Base, IdMixin, TimestampMixin


class Device(IdMixin, TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive','retired')", name="valid_status"),
        CheckConstraint("device_role IN ('builder','studio','worker')", name="valid_device_role"),
        Index("ix_devices_status_last_seen", "status", "last_seen_at"),
        {"comment": "运行、登录或执行授权操作的设备"},
    )

    device_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, comment="设备稳定标识")
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="设备名称")
    alias: Mapped[str | None] = mapped_column(String(120), comment="设备运营别名")
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, comment="设备主机名，运行包自动识别使用")
    device_role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="worker", comment="设备角色：builder、studio或worker")
    login_user: Mapped[str | None] = mapped_column(String(120), comment="设备登录用户")
    thunderbolt_address: Mapped[str | None] = mapped_column(String(45), comment="雷电网络地址")
    lan_address: Mapped[str | None] = mapped_column(String(45), comment="普通局域网地址")
    ssh_key_path: Mapped[str | None] = mapped_column(String(500), comment="SSH密钥路径")
    ip_address: Mapped[str | None] = mapped_column(String(45), comment="最近一次IP地址")
    ssh_address: Mapped[str | None] = mapped_column(String(255), comment="SSH连接地址")
    os_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作系统类型")
    purpose: Mapped[str | None] = mapped_column(String(255), comment="设备用途")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="设备状态")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后在线时间")


class GoogleAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "google_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled','revoked')", name="valid_status"),
        CheckConstraint(
            "authorization_status IN ('pending','authorized','expired','revoked','error')",
            name="valid_authorization_status",
        ),
        Index("ix_google_accounts_status_auth", "status", "authorization_status"),
        {"comment": "YouTube授权所使用的Google主账号"},
    )

    nickname: Mapped[str] = mapped_column(String(120), nullable=False, comment="账号运营昵称")
    google_email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, comment="Google账号邮箱")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="账号状态")
    authorization_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="授权状态")
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="首次授权成功时间")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后验证授权时间")

    oauth_grants: Mapped[list[OAuthGrant]] = relationship(back_populates="account")


class OAuthGrant(IdMixin, TimestampMixin, Base):
    __tablename__ = "google_oauth_grants"
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','expired','revoked','error')", name="valid_status"),
        UniqueConstraint("account_id", "provider_subject", name="uq_oauth_grants_account_subject"),
        Index("ix_oauth_grants_account_status", "account_id", "status"),
        {"comment": "Google OAuth授权记录，仅保存Secret引用"},
    )

    account_id: Mapped[str] = mapped_column(ForeignKey("google_accounts.id", ondelete="RESTRICT"), nullable=False, comment="Google账号内部ID")
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False, comment="Google OAuth subject标识")
    credential_ref: Mapped[str] = mapped_column(String(500), nullable=False, comment="外部Secret存储引用，禁止存Token明文")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="授权记录状态")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="访问令牌预计失效时间")
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后刷新时间")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="撤销时间")

    account: Mapped[GoogleAccount] = relationship(back_populates="oauth_grants")
    scopes: Mapped[list[OAuthGrantScope]] = relationship(back_populates="grant", cascade="all, delete-orphan")


class OAuthGrantScope(Base):
    __tablename__ = "google_oauth_grant_scopes"
    __table_args__ = ({"comment": "OAuth授权范围明细"},)

    grant_id: Mapped[str] = mapped_column(ForeignKey("google_oauth_grants.id", ondelete="CASCADE"), primary_key=True, comment="OAuth授权记录ID")
    scope: Mapped[str] = mapped_column(String(500), primary_key=True, comment="OAuth scope")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")

    grant: Mapped[OAuthGrant] = relationship(back_populates="scopes")


class Channel(IdMixin, TimestampMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new','authorized','analyzed','branded','configured','scheduled','active','paused','archived','deleted')",
            name="valid_status",
        ),
        CheckConstraint("daily_publish_count >= 0", name="daily_publish_count_nonnegative"),
        Index("ix_channels_status_language", "status", "default_language"),
        {"comment": "YouTube频道稳定身份信息"},
    )

    youtube_channel_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="YouTube频道外部ID")
    original_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="YouTube频道原名")
    operational_name: Mapped[str | None] = mapped_column(String(255), comment="运营昵称")
    youtube_channel_url: Mapped[str | None] = mapped_column(String(1000), comment="YouTube频道主页地址")
    country_code: Mapped[str | None] = mapped_column(String(2), comment="频道目标国家或地区代码")
    country_name_zh: Mapped[str | None] = mapped_column(String(120), comment="频道目标国家或地区中文名称")
    default_language: Mapped[str | None] = mapped_column(String(20), comment="默认语言代码")
    default_genre: Mapped[str | None] = mapped_column(String(120), comment="默认题材")
    channel_type: Mapped[str | None] = mapped_column(String(120), comment="频道内容类型")
    drama_type: Mapped[str | None] = mapped_column(String(60), comment="短剧受众类型")
    application_success_date: Mapped[date | None] = mapped_column(Date, comment="频道申请成功日期")
    display_order: Mapped[int | None] = mapped_column(SmallInteger, comment="频道总表展示序号")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Shanghai", comment="IANA时区")
    daily_publish_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", comment="每日更新次数")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="new", comment="频道生命周期状态")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="软删除时间")


class AccountChannelAuthorization(IdMixin, TimestampMixin, Base):
    __tablename__ = "account_channel_authorizations"
    __table_args__ = (
        CheckConstraint("status IN ('active','revoked','mismatch','error')", name="valid_status"),
        UniqueConstraint("account_id", "channel_id", name="uq_account_channel_authorizations_pair"),
        Index("ix_account_channel_auth_channel_status", "channel_id", "status"),
        {"comment": "Google账号与YouTube频道的授权关系"},
    )

    account_id: Mapped[str] = mapped_column(ForeignKey("google_accounts.id", ondelete="RESTRICT"), nullable=False, comment="Google账号内部ID")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="频道内部ID")
    oauth_grant_id: Mapped[str] = mapped_column(ForeignKey("google_oauth_grants.id", ondelete="RESTRICT"), nullable=False, comment="实际使用的OAuth授权ID")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="绑定状态")
    verified_youtube_channel_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="Token调用YouTube后返回的频道ID")
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="频道绑定校验时间")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="解除绑定时间")


class AuthorizationEvent(IdMixin, Base):
    __tablename__ = "authorization_events"
    __table_args__ = (
        CheckConstraint("result IN ('success','failure','cancelled')", name="valid_result"),
        Index("ix_authorization_events_account_time", "account_id", "occurred_at"),
        Index("ix_authorization_events_channel_time", "channel_id", "occurred_at"),
        {"comment": "OAuth授权与频道校验事件流水"},
    )

    account_id: Mapped[str | None] = mapped_column(ForeignKey("google_accounts.id", ondelete="SET NULL"), comment="Google账号内部ID")
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), comment="频道内部ID")
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), comment="操作设备ID")
    oauth_grant_id: Mapped[str | None] = mapped_column(ForeignKey("google_oauth_grants.id", ondelete="SET NULL"), comment="OAuth授权记录ID")
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="授权事件类型")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="执行结果")
    error_code: Mapped[str | None] = mapped_column(String(120), comment="错误代码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="脱敏错误信息")
    occurred_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="事件发生时间")
