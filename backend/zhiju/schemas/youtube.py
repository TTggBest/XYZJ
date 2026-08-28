from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VideoUpsert(BaseModel):
    youtube_video_id: str = Field(min_length=3, max_length=32)
    channel_id: str
    operation_package_id: str | None = None
    drama_id: str | None = None
    schedule_id: str | None = None
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    url: str = Field(min_length=1, max_length=1000)
    privacy_status: Literal["public", "private", "unlisted"]
    publish_status: Literal["draft", "scheduled", "published", "deleted", "error"]
    is_blocked: bool = False
    scheduled_publish_at: datetime | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    source: Literal["manual", "youtube_sync"] = "youtube_sync"
    etag: str | None = Field(default=None, max_length=255)
    last_synced_at: datetime | None = None

    @model_validator(mode="after")
    def validate_publish_timestamps(self):
        if self.publish_status == "scheduled" and self.scheduled_publish_at is None:
            raise ValueError("预约视频必须提供预约发布时间")
        if self.publish_status == "published" and self.published_at is None:
            raise ValueError("已发布视频必须提供实际发布时间")
        return self


class VideoRead(VideoUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VideoDramaBindingUpdate(BaseModel):
    drama_id: str


class PlaylistMembershipUpsert(BaseModel):
    video_id: str
    playlist_id: str
    youtube_playlist_item_id: str | None = Field(default=None, max_length=100)
    position_number: int | None = Field(default=None, ge=0)
    score: Decimal | None = Field(default=None, ge=0)
    status: Literal["active", "removed"] = "active"
    source: Literal["manual", "youtube_sync", "analytics_reorder"] = "youtube_sync"
    last_synced_at: datetime | None = None


class PlaylistMembershipRead(PlaylistMembershipUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class PlaylistOrderChange(BaseModel):
    position_number: int = Field(ge=0)
    score: Decimal | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)


class PlaylistOrderHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    membership_id: str
    playlist_id: str
    video_id: str
    old_position: int | None
    new_position: int | None
    old_score: Decimal | None
    new_score: Decimal | None
    old_status: str | None
    new_status: str
    reason: str
    actor_type: str
    actor_id: str | None
    changed_at: datetime


class CommentUpsert(BaseModel):
    youtube_comment_id: str = Field(min_length=1, max_length=120)
    video_id: str
    channel_id: str
    parent_comment_id: str | None = None
    author_channel_id: str | None = Field(default=None, max_length=100)
    author_display_name: str = Field(min_length=1, max_length=255)
    original_text: str = Field(min_length=1)
    translated_text: str | None = None
    published_at: datetime
    youtube_updated_at: datetime | None = None
    like_count: int = Field(default=0, ge=0)
    is_channel_owner: bool = False
    reply_status: Literal["unreplied", "suggested", "replied", "ignored", "failed"] = "unreplied"
    moderation_status: Literal["published", "held", "likely_spam", "rejected", "deleted"] = "published"
    sentiment: str | None = Field(default=None, max_length=40)
    analysis_label: str | None = Field(default=None, max_length=80)
    recommended_reply: str | None = None
    recommended_reply_translation: str | None = None
    last_synced_at: datetime


class CommentRead(CommentUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class CommentAnalysisUpdate(BaseModel):
    translated_text: str | None = None
    sentiment: str | None = Field(default=None, max_length=40)
    analysis_label: str | None = Field(default=None, max_length=80)
    recommended_reply: str | None = None
    recommended_reply_translation: str | None = None


class CommentReplyCreate(BaseModel):
    comment_id: str
    reply_text: str = Field(min_length=1)
    reply_translation: str | None = None
    generation_method: Literal["ai", "manual", "template"]
    approval_status: Literal["not_required", "pending", "approved", "rejected"] = "not_required"
    publish_status: Literal["draft", "queued"] = "draft"


class CommentReplyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    comment_id: str
    youtube_reply_id: str | None
    reply_text: str
    reply_translation: str | None
    generation_method: str
    approval_status: str
    publish_status: str
    published_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class CommentReplyReview(BaseModel):
    decision: Literal["approved", "rejected"]


class CommentReplyStatusUpdate(BaseModel):
    status: Literal["queued", "published", "failed", "cancelled"]
    youtube_reply_id: str | None = Field(default=None, max_length=120)
    published_at: datetime | None = None
    error_message: str | None = None


class ChannelDailyMetricUpsert(BaseModel):
    channel_id: str
    metric_date: date
    views: int = Field(default=0, ge=0)
    watch_time_minutes: Decimal = Field(default=Decimal("0"), ge=0)
    subscribers_gained: int = Field(default=0, ge=0)
    subscribers_lost: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    ctr: Decimal | None = Field(default=None, ge=0, le=1)
    synced_at: datetime


class ChannelDailyMetricRead(ChannelDailyMetricUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class VideoDailyMetricUpsert(BaseModel):
    video_id: str
    metric_date: date
    views: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    ctr: Decimal | None = Field(default=None, ge=0, le=1)
    watch_time_minutes: Decimal = Field(default=Decimal("0"), ge=0)
    average_view_duration_seconds: Decimal | None = Field(default=None, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    subscribers_gained: int = Field(default=0, ge=0)
    synced_at: datetime


class VideoDailyMetricRead(VideoDailyMetricUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class AnalyticsBreakdownUpsert(BaseModel):
    scope_type: Literal["channel", "video"]
    channel_id: str
    video_id: str | None = None
    metric_date: date
    dimension_type: Literal["country", "device", "traffic_source", "age_group", "gender", "viewer_type"]
    dimension_value: str = Field(min_length=1, max_length=255)
    views: int = Field(default=0, ge=0)
    watch_time_minutes: Decimal = Field(default=Decimal("0"), ge=0)
    impressions: int = Field(default=0, ge=0)
    ctr: Decimal | None = Field(default=None, ge=0, le=1)
    synced_at: datetime


class AnalyticsBreakdownRead(AnalyticsBreakdownUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope_entity_id: str
    created_at: datetime
    updated_at: datetime


class SyncStart(BaseModel):
    authorization_id: str
    worker_key: str = Field(min_length=1, max_length=120)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class SyncComplete(BaseModel):
    worker_key: str = Field(min_length=1, max_length=120)
    success: bool
    cursor_value: str | None = Field(default=None, max_length=1000)
    data_through_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = None


class SyncWatermarkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    data_type: str
    status: str
    cursor_value: str | None
    data_through_at: datetime | None
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_failed_at: datetime | None
    error_code: str | None
    error_message: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApiRequestRecordCreate(BaseModel):
    request_key: str = Field(min_length=8, max_length=180)
    channel_id: str | None = None
    authorization_id: str | None = None
    data_type: str = Field(min_length=1, max_length=60)
    endpoint: str = Field(min_length=1, max_length=255)
    http_method: str = Field(min_length=1, max_length=10)
    http_status: int | None = Field(default=None, ge=100, le=599)
    result: Literal["success", "failure", "cancelled"]
    quota_units: int = Field(default=0, ge=0)
    response_item_count: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = None
    requested_at: datetime
    finished_at: datetime | None = None
    quota_date: date

    @model_validator(mode="after")
    def validate_request_result(self) -> "ApiRequestRecordCreate":
        if self.finished_at is not None and self.finished_at < self.requested_at:
            raise ValueError("请求结束时间不能早于开始时间")
        if self.result == "success" and (
            self.http_status is None or not 200 <= self.http_status < 300
        ):
            raise ValueError("成功请求必须提供2xx HTTP状态码")
        return self


class ApiRequestRecordRead(BaseModel):
    id: str
    request_key: str
    channel_id: str | None
    authorization_id: str | None
    account_id: str | None
    data_type: str
    endpoint: str
    http_method: str
    http_status: int | None
    result: str
    quota_units: int
    response_item_count: int | None
    error_code: str | None
    error_message: str | None
    requested_at: datetime
    finished_at: datetime | None
    quota_log_id: str
    quota_date: date
    recorded_at: datetime


class QuotaUsageRead(BaseModel):
    id: str
    api_request_log_id: str
    request_key: str
    channel_id: str | None
    account_id: str | None
    quota_date: date
    endpoint: str
    units: int
    recorded_at: datetime


class QuotaUsageSummary(BaseModel):
    quota_date: date
    channel_id: str | None
    account_id: str | None
    endpoint: str
    request_count: int
    total_units: int
