from datetime import datetime

from pydantic import BaseModel


class ChannelLedgerRow(BaseModel):
    row_id: str
    group_id: str
    drama_id: str | None
    drama_title: str
    drama_code: str | None
    youtube_video_id: str | None
    visibility: str
    scheduled_publish_at: datetime | None
    uploaded_at: datetime | None
    schedule_id: str | None
    planned_at: datetime | None
    has_schedule: bool
    is_public: bool
    failed: bool
    failure_message: str | None
    upload_status: str | None
    needs_matching: bool


class ChannelLedgerPage(BaseModel):
    channel_id: str
    channel_name: str
    language: str | None
    items: list[ChannelLedgerRow]
    total: int
    drama_count: int
    page: int
    pages: int
    page_size: int
    last_synced_at: datetime | None
    sync_status: str | None
    sync_complete: bool
    inventory_basis: str
    completed_drama_count: int
    inventory_warning: str | None
