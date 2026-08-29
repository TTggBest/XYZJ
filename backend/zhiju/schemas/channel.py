from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zhiju.schemas.identity import ChannelRead
from zhiju.schemas.operations import PlaylistRead
from zhiju.schemas.settings import ChannelDramaTypeRead, ChannelInitializationRuleRead


class ChannelProfileUpsert(BaseModel):
    avatar_asset_id: str | None = None
    banner_asset_id: str | None = None
    description: str | None = None
    language: str | None = Field(default=None, max_length=20)
    positioning: str | None = None
    avatar_prompt: str | None = None
    banner_prompt: str | None = None
    popup_scheme: str | None = Field(default=None, max_length=120)
    title_template: str | None = None
    fixed_symbol: str | None = Field(default=None, max_length=120)
    status: Literal["draft", "active", "archived"] = "draft"


class ChannelProfileRead(ChannelProfileUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    created_at: datetime
    updated_at: datetime


class ChannelHubUpdate(BaseModel):
    chinese_meaning: str | None = Field(default=None, max_length=255)
    default_genre: str | None = Field(default=None, max_length=120)
    drama_type: str | None = Field(default=None, max_length=80)
    description: str | None = None
    positioning: str | None = None
    avatar_prompt: str | None = None
    banner_prompt: str | None = None
    popup_scheme: str | None = Field(default=None, max_length=120)
    title_template: str | None = None
    fixed_symbol: str | None = Field(default=None, max_length=120)


class ChannelBrandingAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    asset_id: str
    role: str
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelRelevantSkillRead(BaseModel):
    skill_id: str
    code: str
    name: str
    category: str
    version_id: str | None
    version_number: int | None
    version_status: str | None


class ChannelInitializationReadinessRead(BaseModel):
    channel_id: str
    can_initialize: bool
    missing_inputs: list[str]
    missing_rule_modules: list[str]
    rules: list[ChannelInitializationRuleRead]


class ChannelInitializationDraftUpsert(BaseModel):
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    avatar_prompt: str | None = None
    banner_prompt: str | None = None
    pinned_comment: str | None = None
    title_template: str | None = None
    popup_scheme: str | None = None
    playlists: list[str] = Field(default_factory=list)
    initial_audience: str | None = None
    initial_analysis: str | None = None
    operating_reference: str | None = None


class ChannelInitializationDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    input_snapshot: dict[str, object]
    output_draft: dict[str, object]
    applied_report_id: str | None
    applied_dna_version_id: str | None
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelInitializationApplyRead(BaseModel):
    channel_id: str
    applied_modules: list[str]
    retained_draft_modules: list[str]
    created_keywords: int
    created_pinned_comments: int
    created_playlists: int
    analysis_report_id: str | None
    dna_version_id: str | None


class ChannelKeywordCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)
    keyword_type: Literal["keyword", "tag"]
    language: str = Field(min_length=2, max_length=20)
    weight: Decimal = Field(default=Decimal("0.5000"), ge=0, le=1)
    source: str = Field(default="manual", min_length=1, max_length=60)


class ChannelKeywordRead(ChannelKeywordCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelPinnedCommentTemplateCreate(BaseModel):
    language: str = Field(min_length=2, max_length=20)
    body: str = Field(min_length=1)
    activate: bool = False

    @field_validator("language", "body")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


class ChannelPinnedCommentTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    language: str
    version_number: int
    body: str
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelAnalysisTopicScoreCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=255)
    score: Decimal = Field(ge=0, le=1)
    trend: Literal["rising", "stable", "falling", "unknown"] = "unknown"
    rank_number: int = Field(ge=1)
    evidence_summary: str | None = None


class ChannelAnalysisTopicScoreRead(ChannelAnalysisTopicScoreCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    created_at: datetime
    updated_at: datetime


class ChannelAnalysisKeywordScoreCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)
    language: str = Field(min_length=2, max_length=20)
    score: Decimal = Field(ge=0, le=1)
    performance_level: Literal["high", "medium", "low", "unknown"] = "unknown"
    rank_number: int = Field(ge=1)
    evidence_summary: str | None = None


class ChannelAnalysisKeywordScoreRead(ChannelAnalysisKeywordScoreCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    created_at: datetime
    updated_at: datetime


class ChannelAudienceProfileCreate(BaseModel):
    profile_type: Literal[
        "country",
        "device",
        "traffic_source",
        "active_time",
        "age_group",
        "gender",
        "viewer_type",
        "behavior",
        "genre",
    ]
    segment_value: str = Field(min_length=1, max_length=255)
    share: Decimal | None = Field(default=None, ge=0, le=1)
    metric_value: Decimal | None = None
    rank_number: int = Field(ge=1)
    summary: str | None = None


class ChannelAudienceProfileRead(ChannelAudienceProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    created_at: datetime
    updated_at: datetime


class ChannelStrategyRecommendationCreate(BaseModel):
    category: Literal[
        "content", "schedule", "title", "cover", "description", "community", "playlist", "risk"
    ]
    priority: int = Field(ge=1)
    recommendation: str = Field(min_length=1)
    rationale: str | None = None
    expected_impact: str | None = None
    status: Literal["proposed", "adopted", "rejected", "completed"] = "proposed"


class ChannelStrategyRecommendationRead(ChannelStrategyRecommendationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    created_at: datetime
    updated_at: datetime


class ChannelAnalysisEvidenceCreate(BaseModel):
    source_type: Literal[
        "channel_metric",
        "video_metric",
        "analytics_breakdown",
        "youtube_video",
        "comment",
        "operation_package",
        "schedule",
        "channel_dna",
        "manual",
    ]
    source_entity_id: str = Field(min_length=1, max_length=36)
    evidence_time: datetime | None = None
    weight: Decimal = Field(default=Decimal("0.5000"), ge=0, le=1)
    summary: str | None = None


class ChannelAnalysisEvidenceRead(ChannelAnalysisEvidenceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    created_at: datetime
    updated_at: datetime


class ChannelAnalysisReportBase(BaseModel):
    report_type: Literal["initial", "periodic", "manual", "incident"]
    period_start: datetime | None = None
    period_end: datetime | None = None
    summary: str | None = None
    growth_reasons: str | None = None
    decline_reasons: str | None = None
    primary_content: str | None = None
    supporting_content: str | None = None
    risks: str | None = None
    recommendations: str | None = None
    status: Literal["pending", "running", "completed", "failed", "archived"] = "completed"
    generated_by: str = Field(default="manual", min_length=1, max_length=40)


class ChannelAnalysisReportCreate(ChannelAnalysisReportBase):
    topic_scores: list[ChannelAnalysisTopicScoreCreate] = Field(default_factory=list)
    keyword_scores: list[ChannelAnalysisKeywordScoreCreate] = Field(default_factory=list)
    audience_profiles: list[ChannelAudienceProfileCreate] = Field(default_factory=list)
    strategy_recommendations: list[ChannelStrategyRecommendationCreate] = Field(default_factory=list)
    evidence: list[ChannelAnalysisEvidenceCreate] = Field(default_factory=list)


class ChannelAnalysisReportRead(ChannelAnalysisReportBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    version_number: int
    created_at: datetime
    updated_at: datetime


class ChannelAnalysisReportDetailRead(ChannelAnalysisReportRead):
    topic_scores: list[ChannelAnalysisTopicScoreRead]
    keyword_scores: list[ChannelAnalysisKeywordScoreRead]
    audience_profiles: list[ChannelAudienceProfileRead]
    strategy_recommendations: list[ChannelStrategyRecommendationRead]
    evidence: list[ChannelAnalysisEvidenceRead]


class DnaSignalCreate(BaseModel):
    signal_type: Literal["high_keyword", "low_keyword", "high_plot_pattern", "low_plot_pattern"]
    value: str = Field(min_length=1, max_length=500)
    weight: Decimal = Field(default=Decimal("0.5000"), ge=0, le=1)
    rank_number: int = Field(ge=1)
    evidence_summary: str | None = None


class DnaSignalRead(DnaSignalCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dna_version_id: str
    created_at: datetime
    updated_at: datetime


class ChannelDnaVersionCreate(BaseModel):
    analysis_report_id: str | None = None
    activate: bool = False
    language: str = Field(min_length=2, max_length=20)
    primary_genre: str = Field(min_length=1, max_length=120)
    secondary_genre: str | None = Field(default=None, max_length=255)
    audience_summary: str | None = None
    reference_summary: str | None = None
    age_tendency: str | None = Field(default=None, max_length=120)
    gender_tendency: str | None = Field(default=None, max_length=120)
    emotion_preference: str | None = None
    plot_preference: str | None = None
    character_preference: str | None = None
    conflict_preference: str | None = None
    title_style: str | None = None
    cover_style: str | None = None
    community_style: str | None = None
    content_pace: str | None = None
    signals: list[DnaSignalCreate] = Field(default_factory=list)


class ChannelDnaVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    analysis_report_id: str | None
    version_number: int
    status: str
    language: str
    primary_genre: str
    secondary_genre: str | None
    audience_summary: str | None
    reference_summary: str | None
    age_tendency: str | None
    gender_tendency: str | None
    emotion_preference: str | None
    plot_preference: str | None
    character_preference: str | None
    conflict_preference: str | None
    title_style: str | None
    cover_style: str | None
    community_style: str | None
    content_pace: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    updated_at: datetime
    signals: list[DnaSignalRead]


class MediaAssetCreate(BaseModel):
    channel_id: str | None = None
    operation_package_id: str | None = None
    storage_provider: str = Field(default="local", min_length=1, max_length=40)
    storage_key: str = Field(min_length=1, max_length=600)
    original_filename: str | None = Field(default=None, max_length=500)
    asset_type: Literal["image", "video", "audio", "document", "other"]
    asset_role: Literal[
        "channel_avatar",
        "channel_banner",
        "channel_watermark",
        "thumbnail",
        "community_image",
        "source_material",
        "package_artifact",
        "other",
    ] = "other"
    mime_type: str | None = Field(default=None, max_length=150)
    public_url: str | None = Field(default=None, max_length=1000)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    file_size_bytes: int = Field(ge=0)
    status: Literal["pending", "ready", "failed", "archived"] = "ready"

    @model_validator(mode="after")
    def validate_asset_metadata(self):
        channel_roles = {"channel_avatar", "channel_banner", "channel_watermark"}
        package_roles = {"thumbnail", "community_image", "package_artifact"}
        if self.asset_role in channel_roles and not self.channel_id:
            raise ValueError("频道装潢素材必须关联频道")
        if self.asset_role in package_roles and not self.operation_package_id:
            raise ValueError("运营包素材必须关联运营包")
        if self.status != "ready":
            return self
        if self.asset_type == "image":
            if not self.mime_type or not self.mime_type.lower().startswith("image/"):
                raise ValueError("可用图片必须提供图片MIME类型")
            if self.width is None or self.height is None:
                raise ValueError("可用图片必须提供宽度和高度")
        elif self.asset_type == "video":
            if not self.mime_type or not self.mime_type.lower().startswith("video/"):
                raise ValueError("可用视频必须提供视频MIME类型")
            if self.width is None or self.height is None:
                raise ValueError("可用视频必须提供宽度和高度")
        elif self.asset_type == "audio":
            if not self.mime_type or not self.mime_type.lower().startswith("audio/"):
                raise ValueError("可用音频必须提供音频MIME类型")
        return self


class MediaAssetRead(MediaAssetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: Literal["pending", "ready", "failed", "archived", "deleted"]
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MediaAssetStatusChange(BaseModel):
    status: Literal["pending", "ready", "failed", "archived"]
    reason: str | None = Field(default=None, max_length=500)


class MediaAssetMetadataUpdate(BaseModel):
    original_filename: str | None = Field(default=None, max_length=500)
    mime_type: str | None = Field(default=None, max_length=150)
    public_url: str | None = Field(default=None, max_length=1000)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    file_size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("至少提交一个需要修改的素材元数据字段")
        return self


class ChannelDetailRead(BaseModel):
    channel: ChannelRead
    profile: ChannelProfileRead | None
    keywords: list[ChannelKeywordRead]
    active_dna: ChannelDnaVersionRead | None
    recent_reports: list[ChannelAnalysisReportRead]
    pinned_comment_templates: list[ChannelPinnedCommentTemplateRead]
    playlists: list[PlaylistRead]
    branding_assets: list[ChannelBrandingAssetRead]
    drama_types: list[ChannelDramaTypeRead]
    relevant_skills: list[ChannelRelevantSkillRead]
