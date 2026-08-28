from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    BigInteger,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import DATETIME

from zhiju.models.base import Base, IdMixin, TimestampMixin


class Language(IdMixin, TimestampMixin, Base):
    __tablename__ = "languages"
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="valid_status"),
        CheckConstraint("priority_tier IS NULL OR priority_tier IN ('S','A','B','C')", name="valid_priority_tier"),
        {"comment": "系统支持的语言定义"},
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, comment="BCP 47语言代码")
    name_zh: Mapped[str] = mapped_column(String(120), nullable=False, comment="中文语言名称")
    native_name: Mapped[str | None] = mapped_column(String(120), comment="语言本地名称")
    priority_tier: Mapped[str | None] = mapped_column(String(1), comment="语言制作优先级")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="语言状态")


class Drama(IdMixin, TimestampMixin, Base):
    __tablename__ = "dramas"
    __table_args__ = (
        CheckConstraint("status IN ('active','expired','blocked','archived')", name="valid_status"),
        CheckConstraint("source_type IN ('manual','feishu')", name="valid_source_type"),
        Index("ix_dramas_status_expiry", "status", "expires_at"),
        {"comment": "本地剧库中的剧目主档"},
    )

    drama_number: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, autoincrement=True, comment="剧库自增编号")
    drama_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, comment="系统自动生成的可读剧库ID")
    chinese_title: Mapped[str] = mapped_column(String(255), nullable=False, comment="中文主剧名")
    normalized_title: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, comment="用于完全匹配的规范化主剧名")
    baidu_cloud_url: Mapped[str | None] = mapped_column(String(1000), comment="百度网盘资源地址")
    content_summary: Mapped[str | None] = mapped_column(Text, comment="内容概要")
    plot_archive: Mapped[str | None] = mapped_column(Text, comment="剧情档案")
    plot_pattern: Mapped[str | None] = mapped_column(Text, comment="剧情套路")
    core_personas: Mapped[str | None] = mapped_column(Text, comment="核心人设")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="剧目资源到期时间")
    batch_name: Mapped[str | None] = mapped_column(String(120), comment="来源批次")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual", comment="剧目来源")
    source_sheet_id: Mapped[str | None] = mapped_column(String(40), comment="来源飞书工作表ID")
    source_row_number: Mapped[int | None] = mapped_column(Integer, comment="来源飞书原始行号")
    source_synced_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), comment="最后一次飞书同步时间")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="剧目状态")


class DramaAlias(IdMixin, TimestampMixin, Base):
    __tablename__ = "drama_aliases"
    __table_args__ = (
        UniqueConstraint("normalized_alias", name="uq_drama_aliases_normalized_alias"),
        Index("ix_drama_aliases_normalized_alias", "normalized_alias"),
        {"comment": "剧目别名，一条记录保存一个别名"},
    )

    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, comment="剧目内部ID")
    alias: Mapped[str] = mapped_column(String(255), nullable=False, comment="剧目别名")
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, comment="用于完全匹配的规范化别名")
    source: Mapped[str] = mapped_column(String(60), nullable=False, server_default="manual", comment="别名来源")


class DramaCoreTerm(IdMixin, TimestampMixin, Base):
    __tablename__ = "drama_core_terms"
    __table_args__ = (
        CheckConstraint("term_type IN ('keyword','topic','trope','persona','conflict')", name="valid_term_type"),
        UniqueConstraint("drama_id", "term_type", "term", name="uq_drama_core_terms_identity"),
        Index("ix_drama_core_terms_drama_type", "drama_id", "term_type"),
        {"comment": "剧目核心词、题材、套路、人设和冲突词"},
    )

    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, comment="剧目内部ID")
    term_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="核心词类型")
    term: Mapped[str] = mapped_column(String(255), nullable=False, comment="核心词正文")
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0.5000", comment="核心词权重，0到1")
    source: Mapped[str] = mapped_column(String(60), nullable=False, server_default="manual", comment="核心词来源")


class DramaTranslation(IdMixin, TimestampMixin, Base):
    __tablename__ = "drama_translations"
    __table_args__ = (
        CheckConstraint("translation_status IN ('missing','pending','in_progress','ready','failed')", name="valid_translation_status"),
        CheckConstraint("asset_status IN ('missing','partial','ready','expired')", name="valid_asset_status"),
        CheckConstraint("source_type IN ('manual','feishu')", name="valid_source_type"),
        UniqueConstraint("drama_id", "language_id", name="uq_drama_translations_language"),
        Index("ix_drama_translations_language_status", "language_id", "translation_status", "asset_status"),
        {"comment": "剧目各语言翻译与素材可用状态"},
    )

    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, comment="剧目内部ID")
    language_id: Mapped[str] = mapped_column(ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False, comment="语言内部ID")
    translated_title: Mapped[str | None] = mapped_column(String(500), comment="该语言剧名")
    translation_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="missing", comment="翻译状态")
    asset_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="missing", comment="该语言素材状态")
    resource_uri: Mapped[str | None] = mapped_column(String(1000), comment="外部资源定位地址")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual", comment="语言覆盖来源")
    source_synced_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), comment="最后一次飞书同步时间")


class DramaProductionState(IdMixin, TimestampMixin, Base):
    __tablename__ = "drama_production_states"
    __table_args__ = (
        CheckConstraint(
            "cloud_download_status IN ('not_started','in_progress','completed','failed') AND "
            "parameter_normalization_status IN ('not_started','in_progress','completed','failed') AND "
            "subtitle_extraction_status IN ('not_started','in_progress','completed','failed') AND "
            "guishou_upload_status IN ('not_started','in_progress','completed','failed') AND "
            "role_extraction_status IN ('not_started','in_progress','completed','failed') AND "
            "production_completion_status IN ('not_started','in_progress','completed','failed')",
            name="valid_node_statuses",
        ),
        CheckConstraint("source_type IN ('manual','zhihe')", name="valid_source_type"),
        CheckConstraint("episode_count IS NULL OR episode_count >= 0", name="episode_count_nonnegative"),
        CheckConstraint("total_duration_seconds IS NULL OR total_duration_seconds >= 0", name="duration_nonnegative"),
        UniqueConstraint("drama_id", name="uq_drama_production_states_drama"),
        Index("ix_drama_production_states_source", "source_type", "source_updated_at"),
        {"comment": "每部剧唯一一套制剧进度"},
    )

    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="CASCADE"), nullable=False, comment="剧目内部ID")
    cloud_download_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started", comment="网盘下载状态")
    parameter_normalization_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started", comment="统一参数状态")
    subtitle_extraction_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started", comment="字幕提取状态")
    guishou_upload_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started", comment="鬼手上传状态")
    role_extraction_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started", comment="角色提取状态")
    production_completion_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started", comment="制作完成状态")
    episode_count: Mapped[int | None] = mapped_column(Integer, comment="剧集数")
    total_duration_seconds: Mapped[int | None] = mapped_column(Integer, comment="剧集合集时长秒数")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual", comment="进度来源")
    source_external_id: Mapped[str | None] = mapped_column(String(120), comment="智核剧目ID")
    source_updated_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), comment="智核数据更新时间")
    source_synced_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), comment="最近同步时间")
    last_error: Mapped[str | None] = mapped_column(Text, comment="最近失败原因")


class ChannelPlaylist(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_playlists"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','paused','archived','deleted')", name="valid_status"),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        UniqueConstraint("channel_id", "local_name", name="uq_channel_playlists_local_name"),
        Index("ix_channel_playlists_channel_status", "channel_id", "status", "sort_order"),
        {"comment": "频道播放列表定义"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    youtube_playlist_id: Mapped[str | None] = mapped_column(String(80), unique=True, comment="YouTube播放列表外部ID")
    local_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="目标语言播放列表名称")
    chinese_name: Mapped[str | None] = mapped_column(String(255), comment="播放列表中文名称")
    local_description: Mapped[str | None] = mapped_column(Text, comment="目标语言播放列表说明")
    chinese_description: Mapped[str | None] = mapped_column(Text, comment="播放列表中文说明")
    url: Mapped[str | None] = mapped_column(String(1000), comment="YouTube播放列表地址")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="频道内显示排序")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft", comment="播放列表状态")


class PublishCadenceTemplateSlot(IdMixin, TimestampMixin, Base):
    __tablename__ = "publish_cadence_template_slots"
    __table_args__ = (
        CheckConstraint("daily_publish_count BETWEEN 1 AND 5", name="valid_daily_publish_count"),
        CheckConstraint("slot_number >= 1", name="slot_number_positive"),
        CheckConstraint("slot_type IN ('main','aux')", name="valid_slot_type"),
        CheckConstraint("engagement_offset_minutes >= 0", name="engagement_offset_nonnegative"),
        UniqueConstraint("daily_publish_count", "slot_number", name="uq_cadence_template_slots_count_number"),
        Index("ix_cadence_template_slots_count_type", "daily_publish_count", "slot_type", "slot_number"),
        {"comment": "每日1至5更的全局视频与二次触达时间模板"},
    )

    daily_publish_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="模板每日更新次数")
    slot_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="模板内按时间排序的档位序号")
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="主档或辅档")
    local_video_time: Mapped[time] = mapped_column(Time, nullable=False, comment="目标国家当地视频发布时间")
    engagement_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="120", comment="社区或Shorts相对视频延迟分钟数")


class ChannelPublishSlot(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_publish_slots"
    __table_args__ = (
        CheckConstraint("slot_type IN ('main','aux')", name="valid_slot_type"),
        CheckConstraint("slot_number >= 0", name="slot_number_nonnegative"),
        CheckConstraint("status IN ('active','inactive','archived')", name="valid_status"),
        UniqueConstraint("channel_id", "slot_type", "slot_number", name="uq_channel_publish_slots_identity"),
        Index("ix_channel_publish_slots_channel_status", "channel_id", "status", "slot_type", "slot_number"),
        {"comment": "频道长期视频发布时间档位规则"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="主档或辅档")
    slot_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="同类档位编号")
    local_time: Mapped[time] = mapped_column(Time, nullable=False, comment="频道当地发布时间")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, comment="IANA时区")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="档位状态")


class ChannelCommunitySlot(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_community_slots"
    __table_args__ = (
        CheckConstraint("schedule_mode IN ('relative','fixed')", name="valid_schedule_mode"),
        CheckConstraint("status IN ('active','inactive','archived')", name="valid_status"),
        CheckConstraint("offset_minutes >= 0", name="offset_nonnegative"),
        CheckConstraint(
            "(schedule_mode = 'relative' AND publish_slot_id IS NOT NULL AND local_time IS NULL) OR "
            "(schedule_mode = 'fixed' AND publish_slot_id IS NULL AND local_time IS NOT NULL AND offset_minutes = 0)",
            name="mode_fields_present",
        ),
        UniqueConstraint(
            "channel_id",
            "publish_slot_id",
            "offset_minutes",
            name="uq_channel_community_slots_relative_rule",
        ),
        UniqueConstraint(
            "channel_id",
            "local_time",
            "timezone",
            name="uq_channel_community_slots_fixed_rule",
        ),
        Index("ix_channel_community_slots_channel_status", "channel_id", "status"),
        {"comment": "频道Community发布时间规则"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    publish_slot_id: Mapped[str | None] = mapped_column(ForeignKey("channel_publish_slots.id", ondelete="CASCADE"), comment="相对模式关联的视频档位ID")
    schedule_mode: Mapped[str] = mapped_column(String(20), nullable=False, comment="相对档位或固定时间模式")
    local_time: Mapped[time | None] = mapped_column(Time, comment="固定模式的当地发布时间")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, comment="IANA时区")
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="相对视频档位延迟分钟数")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="Community档位状态")


class ChannelScheduleEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_schedule_entries"
    __table_args__ = (
        CheckConstraint("status IN ('planned','reserved','confirmed','replaced','cancelled','published')", name="valid_status"),
        CheckConstraint("community_count >= 0", name="community_count_nonnegative"),
        UniqueConstraint("channel_id", "publish_date", "publish_slot_id", name="uq_schedule_entries_channel_slot_date"),
        Index("ix_schedule_entries_channel_date_status", "channel_id", "publish_date", "status"),
        Index("ix_schedule_entries_drama_status", "drama_id", "status"),
        {"comment": "频道某日某档位的剧目排期实例"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="频道内部ID")
    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="RESTRICT"), nullable=False, comment="剧目内部ID")
    playlist_id: Mapped[str | None] = mapped_column(ForeignKey("channel_playlists.id", ondelete="SET NULL"), comment="计划加入的播放列表ID")
    publish_slot_id: Mapped[str] = mapped_column(ForeignKey("channel_publish_slots.id", ondelete="RESTRICT"), nullable=False, comment="发布时间档位ID")
    publish_date: Mapped[date] = mapped_column(Date, nullable=False, comment="频道当地发布日期")
    planned_local_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="固化的当地计划时间")
    planned_beijing_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="固化的北京时间")
    planned_utc_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="固化的UTC时间")
    community_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", comment="计划Community数量")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="planned", comment="排期状态")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100", comment="排期优先级，数值越小越优先")
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, comment="创建排期的幂等键")
    replaced_by_schedule_id: Mapped[str | None] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="SET NULL"), comment="替换后的排期ID")


class ScheduleChangeHistory(IdMixin, Base):
    __tablename__ = "schedule_change_history"
    __table_args__ = (
        Index("ix_schedule_change_history_schedule_time", "schedule_id", "changed_at"),
        {"comment": "排期每次调整的不可变历史"},
    )

    schedule_id: Mapped[str] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="CASCADE"), nullable=False, comment="排期实例ID")
    old_drama_id: Mapped[str | None] = mapped_column(ForeignKey("dramas.id", ondelete="SET NULL"), comment="调整前剧目ID")
    new_drama_id: Mapped[str | None] = mapped_column(ForeignKey("dramas.id", ondelete="SET NULL"), comment="调整后剧目ID")
    old_planned_utc_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="调整前UTC计划时间")
    new_planned_utc_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="调整后UTC计划时间")
    old_status: Mapped[str | None] = mapped_column(String(20), comment="调整前状态")
    new_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="调整后状态")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="调整原因")
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作者类型")
    actor_id: Mapped[str | None] = mapped_column(String(36), comment="操作者内部ID")
    changed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="调整时间")


class ScheduleCandidate(IdMixin, TimestampMixin, Base):
    __tablename__ = "schedule_candidates"
    __table_args__ = (
        CheckConstraint("candidate_type IN ('primary','backup')", name="valid_candidate_type"),
        CheckConstraint("status IN ('available','selected','rejected','unavailable')", name="valid_status"),
        CheckConstraint("rank_number >= 1", name="rank_positive"),
        UniqueConstraint("schedule_id", "rank_number", name="uq_schedule_candidates_rank"),
        UniqueConstraint("schedule_id", "drama_id", name="uq_schedule_candidates_drama"),
        Index("ix_schedule_candidates_schedule_status", "schedule_id", "status", "rank_number"),
        {"comment": "排期的主选与备选剧目"},
    )

    schedule_id: Mapped[str] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="CASCADE"), nullable=False, comment="排期实例ID")
    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="RESTRICT"), nullable=False, comment="候选剧目ID")
    candidate_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="主选或备选")
    rank_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="候选排序")
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), comment="选剧评分")
    reason: Mapped[str | None] = mapped_column(Text, comment="入选原因")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="available", comment="候选状态")
