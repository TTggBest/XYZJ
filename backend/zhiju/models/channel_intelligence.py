from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from zhiju.models.base import Base, IdMixin, TimestampMixin


class MediaAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint("asset_type IN ('image','video','audio','document','other')", name="valid_asset_type"),
        CheckConstraint(
            "asset_role IN ('channel_avatar','channel_banner','channel_watermark','thumbnail','community_image','source_material','package_artifact','other')",
            name="valid_asset_role",
        ),
        CheckConstraint("status IN ('pending','ready','failed','archived','deleted')", name="valid_status"),
        CheckConstraint("file_size_bytes >= 0", name="file_size_nonnegative"),
        UniqueConstraint("storage_provider", "storage_key", name="uq_media_assets_storage_location"),
        Index("ix_media_assets_channel_status", "channel_id", "status"),
        Index("ix_media_assets_sha256", "sha256"),
        {"comment": "图片、视频和文档等媒体资产元数据"},
    )

    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), comment="所属频道内部ID")
    operation_package_id: Mapped[str | None] = mapped_column(ForeignKey("operation_packages.id", ondelete="SET NULL"), comment="所属运营包ID")
    storage_provider: Mapped[str] = mapped_column(String(40), nullable=False, comment="存储提供方，如local或s3")
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False, comment="存储系统内稳定对象键")
    original_filename: Mapped[str | None] = mapped_column(String(500), comment="上传时原始文件名")
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="资产大类")
    asset_role: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="other", comment="资产业务用途"
    )
    mime_type: Mapped[str | None] = mapped_column(String(150), comment="MIME类型")
    public_url: Mapped[str | None] = mapped_column(
        String(1000), comment="可公开访问地址"
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件SHA-256摘要")
    width: Mapped[int | None] = mapped_column(Integer, comment="图片或视频宽度像素")
    height: Mapped[int | None] = mapped_column(Integer, comment="图片或视频高度像素")
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="文件大小字节数")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="资产状态")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="软删除时间")


class ChannelProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_profiles"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','archived')", name="valid_status"),
        UniqueConstraint("channel_id", name="uq_channel_profiles_channel_id"),
        {"comment": "频道当前展示与定位档案"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    avatar_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), comment="当前头像资产ID")
    banner_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), comment="当前Banner资产ID")
    description: Mapped[str | None] = mapped_column(Text, comment="频道说明")
    language: Mapped[str | None] = mapped_column(String(20), comment="频道展示语言")
    positioning: Mapped[str | None] = mapped_column(Text, comment="频道定位说明")
    popup_scheme: Mapped[str | None] = mapped_column(String(120), comment="标题弹框方案")
    title_template: Mapped[str | None] = mapped_column(Text, comment="频道标题模板")
    fixed_symbol: Mapped[str | None] = mapped_column(String(120), comment="标题固定符号")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft", comment="档案状态")


class ChannelPinnedCommentTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_pinned_comment_templates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','superseded','archived')",
            name="valid_status",
        ),
        CheckConstraint("version_number >= 1", name="version_positive"),
        UniqueConstraint(
            "channel_id",
            "language",
            "version_number",
            name="uq_channel_pinned_comment_templates_version",
        ),
        Index(
            "ix_channel_pinned_comment_templates_channel_language_status",
            "channel_id",
            "language",
            "status",
        ),
        {"comment": "频道默认置顶评论模板版本"},
    )

    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属频道内部ID",
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="模板语言")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="频道语言内版本号")
    body: Mapped[str] = mapped_column(Text, nullable=False, comment="置顶评论正文")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft", comment="模板状态")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="生效时间")
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="结束生效时间")


class ChannelBrandingAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_branding_assets"
    __table_args__ = (
        CheckConstraint("role IN ('avatar','banner','watermark','community_default')", name="valid_role"),
        CheckConstraint("status IN ('draft','active','superseded','archived')", name="valid_status"),
        Index("ix_channel_branding_assets_channel_role", "channel_id", "role", "status"),
        {"comment": "频道装潢资产使用历史"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False, comment="媒体资产ID")
    role: Mapped[str] = mapped_column(String(30), nullable=False, comment="装潢资产用途")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft", comment="使用状态")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="生效时间")
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="失效时间")


class ChannelKeyword(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_keywords"
    __table_args__ = (
        CheckConstraint("keyword_type IN ('keyword','tag')", name="valid_keyword_type"),
        CheckConstraint("status IN ('active','inactive','archived')", name="valid_status"),
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        UniqueConstraint("channel_id", "keyword", "keyword_type", "language", name="uq_channel_keywords_identity"),
        Index("ix_channel_keywords_channel_status", "channel_id", "status", "keyword_type"),
        {"comment": "频道关键词与标签明细"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, comment="关键词或标签正文")
    keyword_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="词条类型")
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="词条语言")
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0.5000", comment="词条权重，0到1")
    source: Mapped[str] = mapped_column(String(60), nullable=False, comment="词条来源")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="生效时间")
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="失效时间")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="词条状态")


class ChannelAnalysisReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_analysis_reports"
    __table_args__ = (
        CheckConstraint("report_type IN ('initial','periodic','manual','incident')", name="valid_report_type"),
        CheckConstraint("status IN ('pending','running','completed','failed','archived')", name="valid_status"),
        CheckConstraint("version_number >= 1", name="version_positive"),
        UniqueConstraint("channel_id", "version_number", name="uq_channel_analysis_reports_version"),
        Index("ix_channel_analysis_reports_channel_period", "channel_id", "period_end", "status"),
        {"comment": "频道分析报告及其历史版本"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="频道内分析报告版本号")
    report_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="报告类型")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="分析周期开始时间")
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="分析周期结束时间")
    summary: Mapped[str | None] = mapped_column(Text, comment="报告摘要")
    growth_reasons: Mapped[str | None] = mapped_column(Text, comment="增长原因")
    decline_reasons: Mapped[str | None] = mapped_column(Text, comment="下降原因")
    primary_content: Mapped[str | None] = mapped_column(Text, comment="主材分析")
    supporting_content: Mapped[str | None] = mapped_column(Text, comment="辅材分析")
    risks: Mapped[str | None] = mapped_column(Text, comment="风险分析")
    recommendations: Mapped[str | None] = mapped_column(Text, comment="下一步建议")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="报告状态")
    generated_by: Mapped[str] = mapped_column(String(40), nullable=False, server_default="system", comment="报告生成方式")


class ChannelAnalysisTopicScore(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_analysis_topic_scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint("trend IN ('rising','stable','falling','unknown')", name="valid_trend"),
        CheckConstraint("rank_number >= 1", name="rank_positive"),
        UniqueConstraint("report_id", "topic", name="uq_channel_analysis_topic_scores_topic"),
        Index("ix_channel_analysis_topic_scores_report_rank", "report_id", "rank_number"),
        {"comment": "频道分析报告中的题材评分"},
    )

    report_id: Mapped[str] = mapped_column(ForeignKey("channel_analysis_reports.id", ondelete="CASCADE"), nullable=False, comment="分析报告ID")
    topic: Mapped[str] = mapped_column(String(255), nullable=False, comment="题材或内容方向")
    score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False, comment="题材评分，0到1")
    trend: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown", comment="上升、稳定、下降或未知")
    rank_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="报告内题材排名")
    evidence_summary: Mapped[str | None] = mapped_column(Text, comment="题材评分证据摘要")


class ChannelAnalysisKeywordScore(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_analysis_keyword_scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint("performance_level IN ('high','medium','low','unknown')", name="valid_performance_level"),
        CheckConstraint("rank_number >= 1", name="rank_positive"),
        UniqueConstraint("report_id", "keyword", "language", name="uq_channel_analysis_keyword_scores_keyword"),
        Index("ix_channel_analysis_keyword_scores_report_rank", "report_id", "rank_number"),
        {"comment": "频道分析报告中的关键词评分"},
    )

    report_id: Mapped[str] = mapped_column(ForeignKey("channel_analysis_reports.id", ondelete="CASCADE"), nullable=False, comment="分析报告ID")
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, comment="关键词正文")
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="关键词语言")
    score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False, comment="关键词评分，0到1")
    performance_level: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown", comment="高、中、低或未知表现")
    rank_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="报告内关键词排名")
    evidence_summary: Mapped[str | None] = mapped_column(Text, comment="关键词评分证据摘要")


class ChannelAudienceProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_audience_profiles"
    __table_args__ = (
        CheckConstraint("profile_type IN ('country','device','traffic_source','active_time','age_group','gender','viewer_type','behavior','genre')", name="valid_profile_type"),
        CheckConstraint("share IS NULL OR (share >= 0 AND share <= 1)", name="share_range"),
        CheckConstraint("rank_number >= 1", name="rank_positive"),
        UniqueConstraint("report_id", "profile_type", "segment_value", name="uq_channel_audience_profiles_segment"),
        Index("ix_channel_audience_profiles_report_type", "report_id", "profile_type", "rank_number"),
        {"comment": "频道分析报告中的结构化用户画像"},
    )

    report_id: Mapped[str] = mapped_column(ForeignKey("channel_analysis_reports.id", ondelete="CASCADE"), nullable=False, comment="分析报告ID")
    profile_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="国家、设备、流量来源或行为等画像类型")
    segment_value: Mapped[str] = mapped_column(String(255), nullable=False, comment="画像分群值")
    share: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), comment="该分群占比，0到1")
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 5), comment="该分群补充指标值")
    rank_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="同类画像排名")
    summary: Mapped[str | None] = mapped_column(Text, comment="画像业务解释")


class ChannelStrategyRecommendation(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_strategy_recommendations"
    __table_args__ = (
        CheckConstraint("category IN ('content','schedule','title','cover','description','community','playlist','risk')", name="valid_category"),
        CheckConstraint("status IN ('proposed','adopted','rejected','completed')", name="valid_status"),
        CheckConstraint("priority >= 1", name="priority_positive"),
        UniqueConstraint("report_id", "category", "priority", name="uq_channel_strategy_recommendations_priority"),
        Index("ix_channel_strategy_recommendations_report_status", "report_id", "status", "priority"),
        {"comment": "频道分析报告中的结构化策略建议"},
    )

    report_id: Mapped[str] = mapped_column(ForeignKey("channel_analysis_reports.id", ondelete="CASCADE"), nullable=False, comment="分析报告ID")
    category: Mapped[str] = mapped_column(String(30), nullable=False, comment="内容、排期、标题、封面等建议类别")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, comment="建议优先级")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, comment="可执行建议正文")
    rationale: Mapped[str | None] = mapped_column(Text, comment="建议理由")
    expected_impact: Mapped[str | None] = mapped_column(Text, comment="预期影响")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="proposed", comment="建议采用状态")


class ChannelAnalysisEvidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_analysis_evidence"
    __table_args__ = (
        CheckConstraint("source_type IN ('channel_metric','video_metric','analytics_breakdown','youtube_video','comment','operation_package','schedule','channel_dna','manual')", name="valid_source_type"),
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        UniqueConstraint("report_id", "source_type", "source_entity_id", name="uq_channel_analysis_evidence_source"),
        Index("ix_channel_analysis_evidence_report_type", "report_id", "source_type"),
        {"comment": "频道分析报告使用的数据库证据关联"},
    )

    report_id: Mapped[str] = mapped_column(ForeignKey("channel_analysis_reports.id", ondelete="CASCADE"), nullable=False, comment="分析报告ID")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="证据业务实体类型")
    source_entity_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="证据业务实体稳定ID")
    evidence_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="证据对应业务时间")
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0.5000", comment="证据权重，0到1")
    summary: Mapped[str | None] = mapped_column(Text, comment="证据摘要")


class ChannelDnaVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_dna_versions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','superseded','archived')", name="valid_status"),
        UniqueConstraint("channel_id", "version_number", name="uq_channel_dna_versions_number"),
        Index("ix_channel_dna_versions_channel_status", "channel_id", "status"),
        {"comment": "可追溯的频道DNA版本"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    analysis_report_id: Mapped[str | None] = mapped_column(ForeignKey("channel_analysis_reports.id", ondelete="SET NULL"), comment="形成该版本的分析报告ID")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="频道内递增版本号")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft", comment="DNA版本状态")
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="频道语言")
    primary_genre: Mapped[str] = mapped_column(String(120), nullable=False, comment="主题材")
    secondary_genre: Mapped[str | None] = mapped_column(String(255), comment="子题材")
    audience_summary: Mapped[str | None] = mapped_column(Text, comment="核心受众描述")
    age_tendency: Mapped[str | None] = mapped_column(String(120), comment="年龄倾向")
    gender_tendency: Mapped[str | None] = mapped_column(String(120), comment="性别倾向")
    emotion_preference: Mapped[str | None] = mapped_column(Text, comment="情绪偏好")
    plot_preference: Mapped[str | None] = mapped_column(Text, comment="剧情偏好")
    character_preference: Mapped[str | None] = mapped_column(Text, comment="人物偏好")
    conflict_preference: Mapped[str | None] = mapped_column(Text, comment="冲突偏好")
    title_style: Mapped[str | None] = mapped_column(Text, comment="标题风格")
    cover_style: Mapped[str | None] = mapped_column(Text, comment="封面风格")
    community_style: Mapped[str | None] = mapped_column(Text, comment="Community风格")
    content_pace: Mapped[str | None] = mapped_column(Text, comment="内容节奏")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="生效时间")
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="失效时间")


class ChannelDnaSignal(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_dna_signals"
    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('high_keyword','low_keyword','high_plot_pattern','low_plot_pattern')",
            name="valid_signal_type",
        ),
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        CheckConstraint("rank_number >= 1", name="rank_positive"),
        UniqueConstraint("dna_version_id", "signal_type", "value", name="uq_channel_dna_signals_identity"),
        Index("ix_channel_dna_signals_version_type", "dna_version_id", "signal_type", "rank_number"),
        {"comment": "频道DNA中的高低表现关键词和剧情模式"},
    )

    dna_version_id: Mapped[str] = mapped_column(ForeignKey("channel_dna_versions.id", ondelete="CASCADE"), nullable=False, comment="频道DNA版本ID")
    signal_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="信号类型")
    value: Mapped[str] = mapped_column(String(500), nullable=False, comment="关键词或剧情模式正文")
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0.5000", comment="信号权重，0到1")
    rank_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="同类信号排序")
    evidence_summary: Mapped[str | None] = mapped_column(Text, comment="形成该判断的证据摘要")
