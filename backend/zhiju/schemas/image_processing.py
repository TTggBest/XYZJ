from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ImageWorkspaceWrite(BaseModel):
    root_path: str = Field(min_length=1, max_length=1000)


class ImageWorkspaceRead(BaseModel):
    id: str
    root_path: str
    resolved_root: str
    persistent_root: str
    output_root: str
    updated_at: datetime


class ChannelLogoProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    channel_name: str
    status: str
    left_logo_path: str
    right_logo_path: str
    template_path: str
    config_path: str
    canvas_width: int
    canvas_height: int
    calibrated_at: datetime
    updated_at: datetime


class ImageProcessingBatchRead(BaseModel):
    id: str
    batch_number: str
    production_date: date
    status: str
    package_count: int


class ImageProcessingItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    stored_path: str
    match_status: str
    match_method: str | None
    image_role: str | None
    package_id: str | None
    channel_id: str | None
    drama_id: str | None
    schedule_id: str | None
    output_path: str | None
    error_message: str | None


class ImageProcessingRunRead(BaseModel):
    id: str
    batch_id: str
    batch_number: str
    status: str
    total_files: int
    matched_files: int
    unmatched_files: int
    generated_files: int
    manifest_path: str | None
    error_message: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[ImageProcessingItemRead]


class ImageProcessingRunPageRead(BaseModel):
    total: int
    items: list[ImageProcessingRunRead]


class ImageAssetReconcileRead(BaseModel):
    scanned_items: int
    registered_assets: int
    bound_assets: int
    missing_files: int
    unbound_assets: int


class MediaAssetContextRead(BaseModel):
    package_id: str
    channel_id: str
    channel_name: str
    language_code: str
    chinese_title: str
    drama_id: str
    drama_code: str
    video_id: str | None
    source_row_number: int | None
    batch_number: str | None
    target_publish_date: date
    planned_local_time: datetime | None


class MediaAssetCoverageRead(MediaAssetContextRead):
    community_count: int
    expected_roles: list[str]
    present_roles: list[str]
    missing_roles: list[str]
    expected_count: int
    present_count: int
    complete: bool
