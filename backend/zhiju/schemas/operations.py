from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DramaCoreTermInput(BaseModel):
    term_type: Literal["keyword", "topic", "trope", "persona", "conflict"]
    term: str = Field(min_length=1, max_length=255)
    weight: Decimal = Field(default=Decimal("0.5000"), ge=0, le=1)
    source: str = Field(default="manual", min_length=1, max_length=60)


class DramaAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alias: str
    source: str


class DramaCoreTermRead(DramaCoreTermInput):
    model_config = ConfigDict(from_attributes=True)

    id: str


class DramaCreate(BaseModel):
    chinese_title: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    baidu_cloud_url: str | None = Field(default=None, max_length=1000)
    content_summary: str | None = None
    plot_archive: str | None = None
    plot_pattern: str | None = None
    core_personas: str | None = None
    expires_at: datetime | None = None
    batch_name: str | None = Field(default=None, max_length=120)
    status: Literal["active", "expired", "blocked", "archived"] = "active"
    core_terms: list[DramaCoreTermInput] = Field(default_factory=list)

    @field_validator("chinese_title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("中文剧名不能为空")
        return normalized


class DramaRead(BaseModel):
    id: str
    drama_number: int
    drama_code: str
    chinese_title: str
    baidu_cloud_url: str | None
    content_summary: str | None
    plot_archive: str | None
    plot_pattern: str | None
    core_personas: str | None
    expires_at: datetime | None
    batch_name: str | None = None
    source_type: str = "manual"
    source_row_number: int | None = None
    source_synced_at: datetime | None = None
    status: str
    aliases: list[DramaAliasRead]
    core_terms: list[DramaCoreTermRead]
    created_at: datetime
    updated_at: datetime


class LanguageCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name_zh: str = Field(min_length=1, max_length=120)
    native_name: str | None = Field(default=None, max_length=120)


class LanguageRead(LanguageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime
    updated_at: datetime


class DramaTranslationUpsert(BaseModel):
    translated_title: str | None = Field(default=None, max_length=500)
    translation_status: Literal["missing", "pending", "in_progress", "ready", "failed"]
    asset_status: Literal["missing", "partial", "ready", "expired"]
    resource_uri: str | None = Field(default=None, max_length=1000)
    reason: str = Field(min_length=1)

    @field_validator("translated_title", "resource_uri")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_ready_fields(self) -> "DramaTranslationUpsert":
        if self.translation_status == "ready" and not self.translated_title:
            raise ValueError("翻译就绪时必须提供目标语言剧名")
        if self.asset_status == "ready" and not self.resource_uri:
            raise ValueError("素材就绪时必须提供资源定位地址")
        return self


class DramaTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    drama_id: str
    drama_code: str
    chinese_title: str
    language_id: str
    language_code: str
    language_name_zh: str
    translated_title: str | None
    translation_status: str
    asset_status: str
    resource_uri: str | None
    created_at: datetime
    updated_at: datetime


class DramaTranslationMatrixCell(BaseModel):
    language_id: str
    language_code: str
    language_name_zh: str
    language_native_name: str | None
    language_status: str
    translation_id: str | None
    translated_title: str | None
    translation_status: str
    asset_status: str
    resource_uri: str | None
    created_at: datetime | None
    updated_at: datetime | None


class DramaTranslationMatrixRow(BaseModel):
    drama_id: str
    drama_code: str
    chinese_title: str
    drama_status: str
    drama_resource_url: str | None
    language_count: int
    translation_ready_count: int
    asset_ready_count: int
    cells: list[DramaTranslationMatrixCell]
    created_at: datetime
    updated_at: datetime


class PlaylistCreate(BaseModel):
    youtube_playlist_id: str | None = Field(default=None, max_length=80)
    local_name: str = Field(min_length=1, max_length=255)
    chinese_name: str | None = Field(default=None, max_length=255)
    local_description: str | None = None
    chinese_description: str | None = None
    url: str | None = Field(default=None, max_length=1000)
    sort_order: int = Field(default=0, ge=0)
    status: Literal["draft", "active", "paused", "archived"] = "draft"


class PlaylistUpdate(BaseModel):
    youtube_playlist_id: str | None = Field(default=None, max_length=80)
    local_name: str | None = Field(default=None, min_length=1, max_length=255)
    chinese_name: str | None = Field(default=None, max_length=255)
    local_description: str | None = None
    chinese_description: str | None = None
    url: str | None = Field(default=None, max_length=1000)
    sort_order: int | None = Field(default=None, ge=0)
    status: Literal["draft", "active", "paused", "archived"] | None = None


class PlaylistRead(PlaylistCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    created_at: datetime
    updated_at: datetime


class PublishSlotCreate(BaseModel):
    slot_type: Literal["main", "aux"]
    slot_number: int = Field(ge=0, le=24)
    local_time: time
    timezone: str = Field(min_length=1, max_length=64)
    status: Literal["active", "inactive", "archived"] = "active"


class PublishSlotRead(PublishSlotCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    created_at: datetime
    updated_at: datetime


class PublishSlotChannelOverview(BaseModel):
    channel_id: str
    youtube_channel_id: str
    original_name: str
    operational_name: str | None
    display_name: str
    timezone: str
    daily_publish_count: int
    channel_status: str
    slots: list[PublishSlotRead]


class CadenceTemplateSlotInput(BaseModel):
    slot_number: int = Field(ge=1, le=5)
    slot_type: Literal["main", "aux"]
    local_video_time: time
    engagement_offset_minutes: int = Field(default=120, ge=0, le=1440)


class CadenceTemplateSlotRead(CadenceTemplateSlotInput):
    model_config = ConfigDict(from_attributes=True)

    id: str
    daily_publish_count: int
    created_at: datetime
    updated_at: datetime


class CadenceTemplateRead(BaseModel):
    daily_publish_count: int
    slots: list[CadenceTemplateSlotRead]


class CadenceTemplateUpdate(BaseModel):
    slots: list[CadenceTemplateSlotInput]


class ChannelCadenceUpdate(BaseModel):
    daily_publish_count: int = Field(ge=1, le=5)


class CadenceProjectionRead(BaseModel):
    template_slot_id: str
    slot_number: int
    slot_type: Literal["main", "aux"]
    engagement_offset_minutes: int
    local_video_date: date
    local_video_time: str
    beijing_video_date: date
    beijing_video_time: str
    local_engagement_date: date
    local_engagement_time: str
    beijing_engagement_date: date
    beijing_engagement_time: str


class ChannelCadenceOverview(BaseModel):
    channel_id: str
    youtube_channel_id: str
    original_name: str
    operational_name: str | None
    display_name: str
    country_code: str | None
    country_name_zh: str | None
    default_language: str | None
    timezone: str
    daily_publish_count: int
    channel_status: str
    slots: list[CadenceProjectionRead]


class CommunitySlotCreate(BaseModel):
    publish_slot_id: str | None = None
    schedule_mode: Literal["relative", "fixed"]
    local_time: time | None = None
    timezone: str = Field(min_length=1, max_length=64)
    offset_minutes: int = Field(default=0, ge=0, le=1440)
    status: Literal["active", "inactive"] = "active"

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "CommunitySlotCreate":
        if self.schedule_mode == "relative":
            if self.publish_slot_id is None or self.local_time is not None:
                raise ValueError("相对模式必须选择视频档位且不能填写固定时间")
        elif self.publish_slot_id is not None or self.local_time is None or self.offset_minutes != 0:
            raise ValueError("固定模式必须填写当地时间、不能选择视频档位且延迟必须为0")
        return self


class CommunitySlotRead(CommunitySlotCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    status: Literal["active", "inactive", "archived"]
    created_at: datetime
    updated_at: datetime


class CommunitySlotStatusChange(BaseModel):
    status: Literal["active", "inactive", "archived"]
    reason: str = Field(min_length=1)


class ScheduleCreate(BaseModel):
    drama_id: str
    playlist_id: str | None = None
    publish_slot_id: str
    publish_date: date
    community_count: int = Field(default=0, ge=0, le=20)
    priority: int = Field(default=100, ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    drama_id: str
    channel_dna_version_id: str | None
    playlist_id: str | None
    publish_slot_id: str
    publish_date: date
    planned_local_time: datetime
    planned_beijing_time: datetime
    planned_utc_time: datetime
    community_count: int
    status: str
    priority: int
    idempotency_key: str
    replaced_by_schedule_id: str | None
    source_type: str
    source_sheet_id: str | None
    source_row_number: int | None
    source_synced_at: datetime | None
    source_video_id: str | None
    source_video_url: str | None
    is_uploaded: bool
    is_published: bool
    is_task_written: bool
    created_at: datetime
    updated_at: datetime


class ScheduleOverview(BaseModel):
    schedule_id: str
    publish_date: date
    channel_id: str
    youtube_channel_id: str
    channel_name: str
    channel_original_name: str
    channel_timezone: str
    drama_id: str
    drama_code: str
    chinese_title: str
    drama_resource_url: str | None
    publish_slot_id: str
    slot_type: str
    slot_number: int
    slot_local_time: time
    planned_local_time: datetime
    planned_beijing_time: datetime
    planned_utc_time: datetime
    playlist_id: str | None
    playlist_name: str | None
    playlist_url: str | None
    community_count: int
    priority: int
    schedule_status: str
    candidate_count: int
    available_candidate_count: int
    selected_candidate_id: str | None
    task_id: str | None
    task_status: str | None
    work_order_id: str | None
    work_order_status: str | None
    replaced_by_schedule_id: str | None
    created_at: datetime
    updated_at: datetime


class ChannelScheduleRow(BaseModel):
    schedule_id: str
    channel_id: str
    channel_name: str
    channel_timezone: str
    drama_id: str
    drama_code: str
    chinese_title: str
    publish_date: date
    planned_local_time: datetime
    planned_beijing_time: datetime
    slot_type: str
    slot_number: int
    schedule_status: str
    source_type: str
    source_sheet_id: str | None
    source_row_number: int | None
    source_synced_at: datetime | None
    source_video_id: str | None
    source_video_url: str | None
    is_uploaded: bool
    is_published: bool
    is_task_written: bool
    task_id: str | None
    task_status: str | None


class ChannelSchedulePage(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[ChannelScheduleRow]


class ScheduleStatusChange(BaseModel):
    status: Literal["reserved", "confirmed", "cancelled", "published"]
    reason: str = Field(min_length=1)


class ScheduleCandidateCreate(BaseModel):
    drama_id: str
    rank_number: int = Field(ge=2)
    score: Decimal | None = Field(default=None, ge=0)
    reason: str | None = None


class ScheduleCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schedule_id: str
    drama_id: str
    drama_code: str
    chinese_title: str
    candidate_type: str
    rank_number: int
    score: Decimal | None
    reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ScheduleCandidateSelect(BaseModel):
    reason: str = Field(min_length=1)
