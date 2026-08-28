from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


NodeStatus = Literal["not_started", "in_progress", "completed", "failed"]


class DramaProductionStateWrite(BaseModel):
    cloud_download_status: NodeStatus = "not_started"
    parameter_normalization_status: NodeStatus = "not_started"
    subtitle_extraction_status: NodeStatus = "not_started"
    guishou_upload_status: NodeStatus = "not_started"
    role_extraction_status: NodeStatus = "not_started"
    production_completion_status: NodeStatus = "not_started"
    episode_count: int | None = Field(default=None, ge=0)
    total_duration_seconds: int | None = Field(default=None, ge=0)
    last_error: str | None = None


class DramaProductionStateRead(DramaProductionStateWrite):
    id: str | None
    drama_id: str
    source_type: str
    source_external_id: str | None
    source_updated_at: datetime | None
    source_synced_at: datetime | None
    progress_percent: int
    overall_status: str
    current_node: str | None
    updated_at: datetime | None


class DramaProgressRow(DramaProductionStateRead):
    sequence_number: int
    drama_number: int
    drama_code: str
    chinese_title: str
    batch_name: str | None


class DramaProgressPage(BaseModel):
    items: list[DramaProgressRow]
    page: int
    page_size: int
    total: int
    pages: int
