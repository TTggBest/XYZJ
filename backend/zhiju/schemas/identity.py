from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccountCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=120)
    google_email: EmailStr


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nickname: str
    google_email: str
    status: str
    authorization_status: str
    authorized_at: datetime | None
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelCreate(BaseModel):
    youtube_channel_id: str = Field(min_length=3, max_length=64)
    original_name: str = Field(min_length=1, max_length=255)
    operational_name: str | None = Field(default=None, max_length=255)
    youtube_channel_url: str | None = Field(default=None, max_length=1000)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    country_name_zh: str | None = Field(default=None, max_length=120)
    default_language: str | None = Field(default=None, max_length=20)
    default_genre: str | None = Field(default=None, max_length=120)
    channel_type: str | None = Field(default=None, max_length=120)
    drama_type: str | None = Field(default=None, max_length=60)
    application_success_date: date | None = None
    display_order: int | None = Field(default=None, ge=1)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    daily_publish_count: int = Field(default=0, ge=0, le=24)


class ChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    youtube_channel_id: str
    original_name: str
    operational_name: str | None
    youtube_channel_url: str | None
    youtube_avatar_url: str | None
    country_code: str | None
    country_name_zh: str | None
    default_language: str | None
    default_genre: str | None
    channel_type: str | None
    drama_type: str | None
    application_success_date: date | None
    display_order: int | None
    timezone: str
    daily_publish_count: int
    status: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelAuthorizedAccountOverview(BaseModel):
    authorization_id: str
    account_id: str
    nickname: str
    google_email: str
    account_status: str
    authorization_status: str
    verified_at: datetime


class ChannelOverview(BaseModel):
    channel_id: str
    youtube_channel_id: str
    original_name: str
    operational_name: str | None
    display_name: str
    youtube_avatar_url: str | None
    country_code: str | None
    country_name_zh: str | None
    default_language: str | None
    default_genre: str | None
    timezone: str
    daily_publish_count: int
    status: str
    deleted_at: datetime | None
    authorized_account_count: int
    authorized_accounts: list[ChannelAuthorizedAccountOverview]
    profile_id: str | None
    profile_status: str | None
    positioning: str | None
    avatar_asset_id: str | None
    avatar_storage_provider: str | None
    avatar_storage_key: str | None
    avatar_status: str | None
    dna_version_count: int
    latest_dna_version_id: str | None
    latest_dna_version_number: int | None
    latest_dna_status: str | None
    latest_dna_primary_genre: str | None
    latest_dna_secondary_genre: str | None
    latest_dna_updated_at: datetime | None
    analysis_report_count: int
    latest_analysis_report_id: str | None
    latest_analysis_version_number: int | None
    latest_analysis_status: str | None
    latest_analysis_at: datetime | None
    last_sync_at: datetime | None
    running_sync_count: int
    created_at: datetime
    updated_at: datetime


class ChannelStatusChange(BaseModel):
    status: Literal[
        "authorized",
        "analyzed",
        "branded",
        "configured",
        "scheduled",
        "active",
        "paused",
        "archived",
    ]
    reason: str = Field(min_length=1)


class DeviceRegister(BaseModel):
    device_key: str = Field(min_length=3, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    alias: str | None = Field(default=None, max_length=120)
    hostname: str = Field(min_length=1, max_length=255)
    device_role: Literal["builder", "studio", "worker"] = "worker"
    login_user: str | None = Field(default=None, max_length=120)
    thunderbolt_address: str | None = Field(default=None, max_length=45)
    lan_address: str | None = Field(default=None, max_length=45)
    ssh_key_path: str | None = Field(default=None, max_length=500)
    ip_address: str | None = Field(default=None, max_length=45)
    ssh_address: str | None = Field(default=None, max_length=255)
    os_type: str = Field(min_length=1, max_length=40)
    purpose: str | None = Field(default=None, max_length=255)
    status: Literal["active", "inactive", "retired"] = "active"


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_key: str
    name: str
    alias: str | None
    hostname: str
    device_role: str
    login_user: str | None
    thunderbolt_address: str | None
    lan_address: str | None
    ssh_key_path: str | None
    ip_address: str | None
    ssh_address: str | None
    os_type: str
    purpose: str | None
    status: str
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OAuthGrantCreate(BaseModel):
    account_id: str
    provider_subject: str = Field(min_length=1, max_length=255)
    credential_ref: str = Field(min_length=1, max_length=500)
    scopes: list[str] = Field(min_length=1)
    status: Literal["pending", "active", "expired", "revoked", "error"] = "active"
    token_expires_at: datetime | None = None
    device_id: str | None = None


class OAuthGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    provider_subject: str
    credential_ref: str
    status: str
    token_expires_at: datetime | None
    last_refreshed_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str]


class ChannelAuthorizationVerify(BaseModel):
    account_id: str
    channel_id: str
    oauth_grant_id: str
    verified_youtube_channel_id: str = Field(min_length=3, max_length=64)
    device_id: str | None = None


class ChannelAuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    channel_id: str
    oauth_grant_id: str
    status: str
    verified_youtube_channel_id: str
    verified_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuthorizationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str | None
    channel_id: str | None
    device_id: str | None
    oauth_grant_id: str | None
    event_type: str
    result: str
    error_code: str | None
    error_message: str | None
    occurred_at: datetime
