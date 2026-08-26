from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    schedule_id: str
    task_date: date
    idempotency_key: str = Field(min_length=8, max_length=160)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schedule_id: str | None
    channel_id: str
    drama_id: str
    publish_slot_id: str | None
    playlist_id: str | None
    task_date: date
    target_publish_date: date
    community_count: int
    source: str
    status: str
    idempotency_key: str
    source_row_number: int | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class TaskOverview(BaseModel):
    task_id: str
    schedule_id: str | None
    task_date: date
    target_publish_date: date
    channel_id: str
    youtube_channel_id: str
    channel_name: str
    channel_original_name: str
    drama_id: str
    drama_number: int
    business_drama_id: str
    source_row_number: int | None
    drama_code: str
    chinese_title: str
    drama_resource_url: str | None
    publish_slot_id: str | None
    slot_type: str | None
    slot_number: int | None
    slot_local_time: time | None
    slot_timezone: str | None
    schedule_status: str | None
    planned_local_time: datetime | None
    planned_beijing_time: datetime | None
    planned_utc_time: datetime | None
    playlist_id: str | None
    playlist_name: str | None
    playlist_url: str | None
    community_count: int
    source: str
    batch_number: str | None
    source_video_id: str | None
    source_video_url: str | None
    task_status: str
    dispatched_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    work_order_id: str | None
    work_order_status: str | None
    package_id: str | None
    package_status: str | None
    current_node: str | None
    completed_nodes: int
    total_nodes: int
    progress_percent: int
    nodes: dict[str, "WorkOrderNodeProgress"]
    created_at: datetime
    updated_at: datetime


class WorkOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    schedule_id: str | None
    channel_id: str
    drama_id: str
    publish_slot_id: str | None
    playlist_id: str | None
    production_date: date
    target_publish_date: date
    community_count: int
    status: str
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class PackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    schedule_id: str | None
    channel_id: str
    drama_id: str
    channel_dna_version_id: str | None
    version_number: int
    status: str
    ready_at: datetime | None
    approved_at: datetime | None
    delivered_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class NodeRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    package_id: str
    node_type: str
    sequence_number: int
    attempt_number: int
    status: str
    idempotency_key: str
    worker_key: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class WorkOrderDetail(BaseModel):
    task: TaskRead
    work_order: WorkOrderRead
    package: PackageRead
    nodes: list[NodeRunRead]


class WorkOrderNodeProgress(BaseModel):
    node_type: str
    status: str
    attempt_number: int
    worker_key: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None


class WorkOrderOverview(BaseModel):
    work_order_id: str
    task_id: str
    package_id: str
    production_date: date
    target_publish_date: date
    channel_id: str
    youtube_channel_id: str
    channel_name: str
    channel_original_name: str
    drama_id: str
    drama_number: int
    business_drama_id: str
    source_row_number: int | None
    drama_code: str
    chinese_title: str
    drama_resource_url: str | None
    community_count: int
    batch_number: str | None
    source_video_id: str | None
    source_video_url: str | None
    work_order_status: str
    package_status: str
    current_node: str | None
    completed_nodes: int
    total_nodes: int
    progress_percent: int
    nodes: dict[str, WorkOrderNodeProgress]
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class NodeStart(BaseModel):
    worker_key: str = Field(min_length=1, max_length=120)


class NodeFinish(BaseModel):
    success: bool
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = None


class NodeRetry(BaseModel):
    reason: str = Field(min_length=1)


class PackageReview(BaseModel):
    decision: Literal["approved", "changes_requested"]
    note: str | None = None


class CreativeSlotWrite(BaseModel):
    character_focus: str | None = None
    plot_focus: str | None = None
    emotion: str | None = None
    title_hook: str | None = None
    thumbnail_scene: str | None = None
    thumbnail_action: str | None = None
    thumbnail_layout: str | None = None
    description_angle: str | None = None
    community_angle: str | None = None


class CreativeSlotRead(CreativeSlotWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    created_at: datetime
    updated_at: datetime


class TitleCandidateWrite(BaseModel):
    variant_number: int = Field(ge=1, le=3)
    localized_title: str = Field(min_length=1, max_length=500)
    chinese_translation: str | None = Field(default=None, max_length=1000)
    core_phrase: str | None = Field(default=None, max_length=255)
    score: Decimal | None = Field(default=None, ge=0)


class TitleBatchWrite(BaseModel):
    titles: list[TitleCandidateWrite] = Field(min_length=3, max_length=3)
    creative_slot: CreativeSlotWrite | None = None


class TitleRead(TitleCandidateWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    generation_number: int
    selected: bool
    status: str
    created_at: datetime
    updated_at: datetime


class CoverVariantWrite(BaseModel):
    title_id: str
    aspect_ratio: Literal["4:5", "16:9"]
    creative_prompt: str = Field(min_length=1)
    asset_id: str | None = None
    score: Decimal | None = Field(default=None, ge=0)
    selected: bool = True
    status: Literal["prompt_ready", "rendered", "selected"] = "prompt_ready"


class CoverBatchWrite(BaseModel):
    covers: list[CoverVariantWrite] = Field(min_length=1, max_length=24)


class CoverRead(CoverVariantWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    generation_number: int
    status: str
    created_at: datetime
    updated_at: datetime


class DescriptionWrite(BaseModel):
    language: str = Field(min_length=2, max_length=20)
    localized_text: str = Field(min_length=1)
    chinese_translation: str | None = None
    pinned_comment: str | None = None
    score: Decimal | None = Field(default=None, ge=0)
    playlist_id: str | None = None
    playlist_rationale: str | None = None


class DescriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    version_number: int
    language: str
    localized_text: str
    chinese_translation: str | None
    pinned_comment: str | None
    score: Decimal | None
    selected: bool
    status: str
    created_at: datetime
    updated_at: datetime


class CommunityPostWrite(BaseModel):
    sequence_number: int = Field(ge=1, le=20)
    language: str = Field(min_length=2, max_length=20)
    localized_text: str = Field(min_length=1)
    chinese_translation: str | None = None
    planned_time: datetime | None = None
    image_prompt: str | None = None
    asset_ids: list[str] = Field(default_factory=list, max_length=10)


class CommunityBatchWrite(BaseModel):
    posts: list[CommunityPostWrite] = Field(max_length=20)


class CommunityPostRead(CommunityPostWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    version_number: int
    selected: bool
    status: str
    created_at: datetime
    updated_at: datetime


class PlaylistAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    playlist_id: str
    rank_number: int
    rationale: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ValidationWrite(BaseModel):
    validator_code: str = Field(min_length=1, max_length=100)
    node_type: Literal["search", "title", "cover", "description", "community", "merge"] | None = None
    field_reference: str | None = Field(default=None, max_length=255)
    result: Literal["pass", "warning", "fail"]
    message: str = Field(min_length=1)


class ValidationRead(ValidationWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    is_current: bool
    checked_at: datetime
    created_at: datetime
    updated_at: datetime


class SimilarityCheckWrite(BaseModel):
    title_similarity: Decimal | None = Field(default=None, ge=0, le=1)
    cover_similarity: Decimal | None = Field(default=None, ge=0, le=1)
    description_similarity: Decimal | None = Field(default=None, ge=0, le=1)
    creative_similarity: Decimal | None = Field(default=None, ge=0, le=1)
    result: Literal["pass", "warning", "fail"]


class SimilarityCheckRead(SimilarityCheckWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    compared_package_id: str
    checked_at: datetime
    created_at: datetime
    updated_at: datetime


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    artifact_format: str
    generation_number: int
    storage_provider: str
    storage_key: str
    sha256: str | None
    status: str
    ready_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class PackageOutputsRead(BaseModel):
    package: PackageRead
    creative_slot: CreativeSlotRead | None
    titles: list[TitleRead]
    covers: list[CoverRead]
    descriptions: list[DescriptionRead]
    community_posts: list[CommunityPostRead]
    playlist_assignments: list[PlaylistAssignmentRead]
    validations: list[ValidationRead]
    similarity_checks: list[SimilarityCheckRead]
    artifacts: list[ArtifactRead]


class PackageCommunityCell(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence_number: int
    localized_text: str
    chinese_translation: str | None
    image_prompt: str | None
    planned_time: datetime | None
    selected: bool
    status: str


class PackageCopyMark(BaseModel):
    output_type: Literal["title", "cover", "description", "community_text", "community_image"]
    output_id: str = Field(min_length=36, max_length=36)


class PackageCopyProgress(BaseModel):
    package_id: str
    copy_status: Literal["not_started", "in_progress", "completed"]
    copied_keys: list[str]
    copied_count: int
    copy_total: int


class PackageOperationOverview(BaseModel):
    package_id: str
    work_order_id: str
    package_version: int
    package_status: str
    source_complete: bool
    source_incomplete_reason: str | None
    work_order_status: str
    production_date: date
    target_publish_date: date
    planned_local_time: datetime | None
    channel_id: str
    channel_name: str
    channel_original_name: str
    drama_id: str
    drama_number: int
    business_drama_id: str
    source_row_number: int | None
    drama_code: str
    chinese_title: str
    drama_resource_url: str | None
    youtube_video_id: str | None
    video_url: str | None
    batch_number: str | None
    community_count: int
    playlist_id: str | None
    playlist_name: str | None
    playlist_url: str | None
    titles: list[TitleRead]
    covers: list[CoverRead]
    description: DescriptionRead | None
    community_posts: list[PackageCommunityCell]
    copy_status: Literal["not_started", "in_progress", "completed"]
    copied_keys: list[str]
    copied_count: int
    copy_total: int


class PackageMergeResult(BaseModel):
    detail: WorkOrderDetail
    artifacts: list[ArtifactRead]
