from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from zhiju.schemas.operations import DramaAliasRead, DramaCoreTermInput, DramaCoreTermRead
from zhiju.schemas.drama_progress import DramaProductionStateRead


DramaStatus = Literal["active", "expired", "blocked", "archived"]


class DramaLibraryWrite(BaseModel):
    chinese_title: str = Field(min_length=1, max_length=255)
    baidu_cloud_url: str | None = Field(default=None, max_length=1000)
    content_summary: str | None = None
    plot_archive: str | None = None
    plot_pattern: str | None = None
    core_personas: str | None = None
    expires_at: datetime | None = None
    batch_name: str | None = Field(default=None, max_length=120)
    status: DramaStatus = "active"

    @field_validator("chinese_title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("中文剧名不能为空")
        return normalized

    @field_validator(
        "baidu_cloud_url",
        "content_summary",
        "plot_archive",
        "plot_pattern",
        "core_personas",
        "batch_name",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DramaLibraryUpdate(DramaLibraryWrite):
    aliases: list[str] | None = None
    core_terms: list[DramaCoreTermInput] | None = None


class DramaLibraryBulkRequest(BaseModel):
    rows: list[DramaLibraryWrite] = Field(min_length=1, max_length=2000)


class DramaLibraryCsvRequest(BaseModel):
    content: str = Field(min_length=1)


class DramaLibraryBulkRowResult(BaseModel):
    row_number: int
    chinese_title: str
    action: Literal["inserted", "updated", "skipped", "conflict"]
    drama_id: str | None = None
    message: str | None = None


class DramaLibraryBulkResult(BaseModel):
    rows_read: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    rows_conflicted: int
    results: list[DramaLibraryBulkRowResult]


class DramaLibrarySummary(BaseModel):
    total: int
    active: int
    expiring: int
    archived: int


class DramaLibraryRow(BaseModel):
    id: str
    drama_number: int
    drama_code: str
    chinese_title: str
    batch_name: str | None
    expires_at: datetime | None
    content_summary: str | None
    status: str
    source_type: str
    source_row_number: int | None
    source_synced_at: datetime | None
    language_count: int
    published_channel_count: int
    episode_count: int | None
    total_duration_seconds: int | None


class DramaLibraryPage(BaseModel):
    items: list[DramaLibraryRow]
    page: int
    page_size: int
    total: int
    pages: int
    summary: DramaLibrarySummary


class DramaLanguageCoverage(BaseModel):
    language_id: str
    language_code: str
    language_name_zh: str
    priority_tier: str | None
    translated_title: str | None
    translation_status: str
    asset_status: str
    source_type: str | None
    source_synced_at: datetime | None


class DramaLanguageCoverageUpdate(BaseModel):
    translated_title: str | None = Field(default=None, max_length=500)
    translation_status: Literal["missing", "pending", "in_progress", "ready", "failed"] = "ready"
    asset_status: Literal["missing", "partial", "ready", "expired"] = "ready"
    resource_uri: str | None = Field(default=None, max_length=1000)


class DramaChannelPublication(BaseModel):
    channel_id: str
    channel_name: str
    youtube_video_id: str
    video_title: str
    url: str
    publish_status: str
    published_at: datetime | None


class DramaLibraryDetail(DramaLibraryRow):
    baidu_cloud_url: str | None
    plot_archive: str | None
    plot_pattern: str | None
    core_personas: str | None
    source_sheet_id: str | None
    aliases: list[DramaAliasRead]
    core_terms: list[DramaCoreTermRead]
    languages: list[DramaLanguageCoverage]
    channels: list[DramaChannelPublication]
    production_state: DramaProductionStateRead
    created_at: datetime
    updated_at: datetime
