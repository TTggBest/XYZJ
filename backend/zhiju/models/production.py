from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import DATETIME

from zhiju.models.base import Base, IdMixin, TimestampMixin


class ProductionBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "production_batches"
    __table_args__ = (
        CheckConstraint("source IN ('native','feishu')", name="valid_source"),
        Index("ix_production_batches_date_source", "production_date", "source"),
        {"comment": "生产任务的稳定批次"},
    )

    batch_number: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, comment="对外批次号")
    production_date: Mapped[date] = mapped_column(Date, nullable=False, comment="批次生产日期")
    source: Mapped[str] = mapped_column(String(20), nullable=False, comment="批次来源")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="批次状态")


class FeishuSyncRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "feishu_sync_runs"
    __table_args__ = (
        CheckConstraint("sync_type IN ('work_orders','operation_packages','channels','dramas')", name="valid_sync_type"),
        CheckConstraint("status IN ('running','completed','failed')", name="valid_status"),
        Index("ix_feishu_sync_runs_type_time", "sync_type", "started_at"),
        {"comment": "飞书工单与运营包同步执行记录"},
    )

    sync_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="同步数据类型")
    sheet_id: Mapped[str] = mapped_column(String(40), nullable=False, comment="飞书工作表ID")
    environment: Mapped[str] = mapped_column(String(30), nullable=False, comment="执行环境")
    device_key: Mapped[str | None] = mapped_column(String(160), comment="执行设备标识")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="同步状态")
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="读取行数")
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="新增行数")
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="更新行数")
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="跳过行数")
    error_message: Mapped[str | None] = mapped_column(Text, comment="同步失败原因")
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="开始时间")
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), comment="完成时间")


class OperationTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "operation_tasks"
    __table_args__ = (
        CheckConstraint("source IN ('manual','schedule','import')", name="valid_source"),
        CheckConstraint("status IN ('pending_dispatch','dispatched','processing','completed','failed','cancelled')", name="valid_status"),
        CheckConstraint("community_count >= 0", name="community_count_nonnegative"),
        UniqueConstraint("schedule_id", name="uq_operation_tasks_schedule_id"),
        Index("ix_operation_tasks_date_status", "task_date", "status"),
        Index("ix_operation_tasks_channel_status", "channel_id", "status"),
        {"comment": "今日任务及历史任务主记录"},
    )

    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="RESTRICT"), comment="来源排期ID")
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("production_batches.id", ondelete="RESTRICT"), comment="生产批次ID")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="频道内部ID")
    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="RESTRICT"), nullable=False, comment="剧目内部ID")
    publish_slot_id: Mapped[str | None] = mapped_column(ForeignKey("channel_publish_slots.id", ondelete="RESTRICT"), comment="发布时间档位ID")
    playlist_id: Mapped[str | None] = mapped_column(ForeignKey("channel_playlists.id", ondelete="SET NULL"), comment="计划播放列表ID")
    task_date: Mapped[date] = mapped_column(Date, nullable=False, comment="任务生产日期")
    target_publish_date: Mapped[date] = mapped_column(Date, nullable=False, comment="目标发布日期")
    community_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", comment="Community生产数量")
    source: Mapped[str] = mapped_column(String(20), nullable=False, comment="任务来源")
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending_dispatch", comment="任务状态")
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, comment="任务创建幂等键")
    source_video_id: Mapped[str | None] = mapped_column(String(32), comment="来源视频Video ID")
    source_video_url: Mapped[str | None] = mapped_column(String(1000), comment="来源剧目视频地址")
    source_row_number: Mapped[int | None] = mapped_column(Integer, comment="来源飞书表格原始行号")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务下发时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="任务完成时间")
    failure_reason: Mapped[str | None] = mapped_column(Text, comment="任务失败原因")


class TaskEvent(IdMixin, Base):
    __tablename__ = "task_events"
    __table_args__ = (
        Index("ix_task_events_task_time", "task_id", "occurred_at"),
        {"comment": "任务状态变化历史"},
    )

    task_id: Mapped[str] = mapped_column(ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False, comment="任务ID")
    old_status: Mapped[str | None] = mapped_column(String(30), comment="变化前状态")
    new_status: Mapped[str] = mapped_column(String(30), nullable=False, comment="变化后状态")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="状态变化原因")
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作者类型")
    actor_id: Mapped[str | None] = mapped_column(String(36), comment="操作者内部ID")
    occurred_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="事件时间")


class WorkOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="valid_status"),
        CheckConstraint("attempt_count >= 1", name="attempt_count_positive"),
        UniqueConstraint("task_id", name="uq_work_orders_task_id"),
        Index("ix_work_orders_production_date_status", "production_date", "status"),
        Index("ix_work_orders_channel_status", "channel_id", "status"),
        {"comment": "任务下发后生成的生产工单"},
    )

    task_id: Mapped[str] = mapped_column(ForeignKey("operation_tasks.id", ondelete="RESTRICT"), nullable=False, comment="来源任务ID")
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("production_batches.id", ondelete="RESTRICT"), comment="生产批次ID")
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="RESTRICT"), comment="来源排期ID")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="频道内部ID")
    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="RESTRICT"), nullable=False, comment="剧目内部ID")
    publish_slot_id: Mapped[str | None] = mapped_column(ForeignKey("channel_publish_slots.id", ondelete="RESTRICT"), comment="发布时间档位ID")
    playlist_id: Mapped[str | None] = mapped_column(ForeignKey("channel_playlists.id", ondelete="SET NULL"), comment="计划播放列表ID")
    production_date: Mapped[date] = mapped_column(Date, nullable=False, comment="生产日期")
    target_publish_date: Mapped[date] = mapped_column(Date, nullable=False, comment="目标发布日期")
    community_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", comment="Community生产数量")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued", comment="工单状态")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="工单运行轮次")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="首次开始时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="完成时间")
    failure_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因")


class OperationPackage(IdMixin, TimestampMixin, Base):
    __tablename__ = "operation_packages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('building','search_ready','title_ready','cover_ready','text_ready','community_ready','merge_ready','review_pending','changes_requested','approved','delivered','failed','archived')",
            name="valid_status",
        ),
        UniqueConstraint("work_order_id", "version_number", name="uq_operation_packages_version"),
        Index("ix_operation_packages_channel_status", "channel_id", "status"),
        Index("ix_operation_packages_work_order_status", "work_order_id", "status"),
        {"comment": "某剧目、频道和工单的一版运营包"},
    )

    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id", ondelete="RESTRICT"), nullable=False, comment="生产工单ID")
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("production_batches.id", ondelete="RESTRICT"), comment="生产批次ID")
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="RESTRICT"), comment="来源排期ID")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="频道内部ID")
    drama_id: Mapped[str] = mapped_column(ForeignKey("dramas.id", ondelete="RESTRICT"), nullable=False, comment="剧目内部ID")
    channel_dna_version_id: Mapped[str | None] = mapped_column(ForeignKey("channel_dna_versions.id", ondelete="SET NULL"), comment="生产时采用的频道DNA版本ID")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="工单内运营包版本号")
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="building", comment="运营包状态")
    source_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", comment="飞书源数据是否完整")
    source_incomplete_reason: Mapped[str | None] = mapped_column(Text, comment="飞书源数据不完整原因")
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="合并完成时间")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最终审核通过时间")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="交付时间")
    review_note: Mapped[str | None] = mapped_column(Text, comment="最终审核意见")


class PackageOutputCopyState(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_output_copy_states"
    __table_args__ = (
        CheckConstraint(
            "output_type IN ('title','cover','description','community_text','community_image')",
            name="valid_output_type",
        ),
        UniqueConstraint("package_id", "output_type", "output_id", name="uq_package_output_copy_states_target"),
        Index("ix_package_output_copy_states_package_time", "package_id", "copied_at"),
        {"comment": "运营包当前产物的人工复制进度"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    output_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="被复制的产物类型")
    output_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="被复制的当前产物ID")
    copied_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="最近复制成功时间")


class ProductionNodeRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "production_node_runs"
    __table_args__ = (
        CheckConstraint("node_type IN ('search','title','cover','description','community','merge')", name="valid_node_type"),
        CheckConstraint("status IN ('pending','queued','running','completed','failed','skipped','cancelled')", name="valid_status"),
        CheckConstraint("attempt_number >= 1", name="attempt_positive"),
        UniqueConstraint("work_order_id", "node_type", "attempt_number", name="uq_production_node_runs_attempt"),
        UniqueConstraint("idempotency_key", name="uq_production_node_runs_idempotency_key"),
        Index("ix_production_node_runs_work_order_status", "work_order_id", "status", "node_type"),
        {"comment": "生产工单各节点的每次运行尝试"},
    )

    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, comment="生产工单ID")
    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="生产节点类型")
    sequence_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="节点顺序")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="该节点尝试次数")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="节点运行状态")
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False, comment="节点运行幂等键")
    worker_key: Mapped[str | None] = mapped_column(String(120), comment="领取该节点的工作器标识")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="开始时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="完成时间")
    error_code: Mapped[str | None] = mapped_column(String(120), comment="错误代码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="脱敏错误信息")


class PackageTitle(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_titles"
    __table_args__ = (
        CheckConstraint("status IN ('generated','selected','rejected','superseded')", name="valid_status"),
        CheckConstraint("variant_number >= 1 AND generation_number >= 1", name="version_positive"),
        UniqueConstraint("package_id", "variant_number", "generation_number", name="uq_package_titles_version"),
        Index("ix_package_titles_package_status", "package_id", "status", "variant_number"),
        {"comment": "运营包标题候选及重生版本"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    variant_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="A/B候选编号")
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="该候选生成版本")
    localized_title: Mapped[str] = mapped_column(String(500), nullable=False, comment="频道语言标题")
    chinese_translation: Mapped[str | None] = mapped_column(String(1000), comment="标题中文翻译")
    core_phrase: Mapped[str | None] = mapped_column(String(255), comment="标题核心词")
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), comment="标题评分")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", comment="是否最终采用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="generated", comment="标题状态")


class PackageDescription(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_descriptions"
    __table_args__ = (
        CheckConstraint("status IN ('generated','selected','rejected','superseded')", name="valid_status"),
        CheckConstraint("version_number >= 1", name="version_positive"),
        UniqueConstraint("package_id", "version_number", name="uq_package_descriptions_version"),
        {"comment": "运营包说明及其重生版本"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="说明版本号")
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="说明语言")
    localized_text: Mapped[str] = mapped_column(Text, nullable=False, comment="频道语言说明正文")
    chinese_translation: Mapped[str | None] = mapped_column(Text, comment="说明中文翻译")
    pinned_comment: Mapped[str | None] = mapped_column(Text, comment="本版本置顶评论")
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), comment="说明评分")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", comment="是否最终采用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="generated", comment="说明状态")


class PackageCoverVariant(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_cover_variants"
    __table_args__ = (
        CheckConstraint("aspect_ratio IN ('4:5','16:9')", name="valid_aspect_ratio"),
        CheckConstraint("status IN ('prompt_ready','rendered','selected','rejected','superseded')", name="valid_status"),
        CheckConstraint("generation_number >= 1", name="generation_positive"),
        UniqueConstraint("package_id", "title_id", "aspect_ratio", "generation_number", name="uq_package_cover_variants_version"),
        Index("ix_package_cover_variants_package_status", "package_id", "status", "aspect_ratio"),
        {"comment": "与标题候选一一对应的4:5和16:9封面版本"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    title_id: Mapped[str] = mapped_column(ForeignKey("package_titles.id", ondelete="CASCADE"), nullable=False, comment="对应标题候选ID")
    aspect_ratio: Mapped[str] = mapped_column(String(10), nullable=False, comment="封面比例")
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="该比例生成版本")
    creative_prompt: Mapped[str] = mapped_column(Text, nullable=False, comment="封面生成提示词")
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id", ondelete="SET NULL"), comment="生成后的图片资产ID")
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), comment="封面评分")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", comment="是否最终采用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="prompt_ready", comment="封面状态")


class PackageCommunityPost(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_community_posts"
    __table_args__ = (
        CheckConstraint("status IN ('generated','selected','rejected','superseded','published')", name="valid_status"),
        CheckConstraint("sequence_number >= 1 AND version_number >= 1", name="version_positive"),
        UniqueConstraint("package_id", "sequence_number", "version_number", name="uq_package_community_posts_version"),
        Index("ix_package_community_posts_package_status", "package_id", "status", "sequence_number"),
        {"comment": "运营包Community文案版本"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    sequence_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="Community序号")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="文案版本号")
    language: Mapped[str] = mapped_column(String(20), nullable=False, comment="文案语言")
    localized_text: Mapped[str] = mapped_column(Text, nullable=False, comment="频道语言Community文案")
    chinese_translation: Mapped[str | None] = mapped_column(Text, comment="Community文案中文翻译")
    planned_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="计划发布时间")
    image_prompt: Mapped[str | None] = mapped_column(Text, comment="Community配图提示词")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", comment="是否最终采用")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="generated", comment="Community文案状态")


class CommunityPostAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "community_post_assets"
    __table_args__ = (
        CheckConstraint("position_number >= 1", name="position_positive"),
        UniqueConstraint("community_post_id", "position_number", name="uq_community_post_assets_position"),
        UniqueConstraint("community_post_id", "asset_id", name="uq_community_post_assets_asset"),
        {"comment": "Community帖子与一张或多张图片的关联"},
    )

    community_post_id: Mapped[str] = mapped_column(ForeignKey("package_community_posts.id", ondelete="CASCADE"), nullable=False, comment="Community帖子ID")
    asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False, comment="媒体资产ID")
    position_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="图片顺序")


class PackagePlaylistAssignment(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_playlist_assignments"
    __table_args__ = (
        CheckConstraint("status IN ('candidate','selected','rejected')", name="valid_status"),
        UniqueConstraint("package_id", "playlist_id", name="uq_package_playlist_assignments_pair"),
        {"comment": "运营包播放列表候选与最终选择"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    playlist_id: Mapped[str] = mapped_column(ForeignKey("channel_playlists.id", ondelete="RESTRICT"), nullable=False, comment="播放列表ID")
    rank_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="候选排序")
    rationale: Mapped[str | None] = mapped_column(Text, comment="推荐理由")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="candidate", comment="选择状态")


class PackageCreativeSlot(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_creative_slots"
    __table_args__ = (
        UniqueConstraint("package_id", name="uq_package_creative_slots_package_id"),
        {"comment": "运营包各创意维度的统一定位"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    character_focus: Mapped[str | None] = mapped_column(Text, comment="人物焦点")
    plot_focus: Mapped[str | None] = mapped_column(Text, comment="剧情焦点")
    emotion: Mapped[str | None] = mapped_column(Text, comment="情绪方向")
    title_hook: Mapped[str | None] = mapped_column(Text, comment="标题钩子")
    thumbnail_scene: Mapped[str | None] = mapped_column(Text, comment="封面场景")
    thumbnail_action: Mapped[str | None] = mapped_column(Text, comment="封面动作")
    thumbnail_layout: Mapped[str | None] = mapped_column(Text, comment="封面构图")
    description_angle: Mapped[str | None] = mapped_column(Text, comment="说明角度")
    community_angle: Mapped[str | None] = mapped_column(Text, comment="Community角度")


class PackageArtifact(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_artifacts"
    __table_args__ = (
        CheckConstraint("artifact_format IN ('md','json')", name="valid_artifact_format"),
        CheckConstraint("status IN ('pending','ready','failed','superseded')", name="valid_status"),
        CheckConstraint("generation_number >= 1", name="generation_positive"),
        UniqueConstraint("package_id", "artifact_format", "generation_number", name="uq_package_artifacts_version"),
        {"comment": "由数据库内容派生的MD或JSON运营包文件"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    artifact_format: Mapped[str] = mapped_column(String(10), nullable=False, comment="导出文件格式")
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="导出版本号")
    storage_provider: Mapped[str] = mapped_column(String(40), nullable=False, comment="存储提供方")
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False, comment="存储对象键")
    sha256: Mapped[str | None] = mapped_column(String(64), comment="导出文件SHA-256摘要")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending", comment="导出状态")
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="导出完成时间")
    error_message: Mapped[str | None] = mapped_column(Text, comment="脱敏错误信息")


class PackageValidationResult(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_validation_results"
    __table_args__ = (
        CheckConstraint("result IN ('pass','warning','fail')", name="valid_result"),
        Index("ix_package_validation_results_package_result", "package_id", "result", "validator_code"),
        Index("ix_package_validation_results_current", "package_id", "is_current", "validator_code"),
        {"comment": "运营包各项自动检测结果"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="运营包ID")
    validator_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="检测器代码")
    node_type: Mapped[str | None] = mapped_column(String(20), comment="关联生产节点")
    field_reference: Mapped[str | None] = mapped_column(String(255), comment="关联字段定位")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="检测结果")
    message: Mapped[str] = mapped_column(Text, nullable=False, comment="检测说明")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", comment="是否为同一检测项的当前结果")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="检测时间")


class PackageSimilarityCheck(IdMixin, TimestampMixin, Base):
    __tablename__ = "package_similarity_checks"
    __table_args__ = (
        CheckConstraint("result IN ('pass','warning','fail')", name="valid_result"),
        CheckConstraint("title_similarity IS NULL OR title_similarity BETWEEN 0 AND 1", name="valid_title_similarity"),
        CheckConstraint("cover_similarity IS NULL OR cover_similarity BETWEEN 0 AND 1", name="valid_cover_similarity"),
        CheckConstraint("description_similarity IS NULL OR description_similarity BETWEEN 0 AND 1", name="valid_description_similarity"),
        CheckConstraint("creative_similarity IS NULL OR creative_similarity BETWEEN 0 AND 1", name="valid_creative_similarity"),
        UniqueConstraint("package_id", "compared_package_id", name="uq_package_similarity_checks_pair"),
        Index("ix_package_similarity_checks_package_result", "package_id", "result"),
        {"comment": "运营包与历史运营包的相似度检测"},
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="当前运营包ID")
    compared_package_id: Mapped[str] = mapped_column(ForeignKey("operation_packages.id", ondelete="CASCADE"), nullable=False, comment="对比运营包ID")
    title_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), comment="标题相似度，0到1")
    cover_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), comment="封面相似度，0到1")
    description_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), comment="说明相似度，0到1")
    creative_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), comment="整体创意相似度，0到1")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="检测结果")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="检测时间")


class SystemEvent(IdMixin, Base):
    __tablename__ = "system_events"
    __table_args__ = (
        Index("ix_system_events_entity_time", "entity_type", "entity_id", "occurred_at"),
        {"comment": "跨业务实体的统一状态事件账本"},
    )

    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, comment="业务对象类型")
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="业务对象ID")
    old_status: Mapped[str | None] = mapped_column(String(40), comment="变化前状态")
    new_status: Mapped[str] = mapped_column(String(40), nullable=False, comment="变化后状态")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="状态变化原因")
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作者类型")
    actor_id: Mapped[str | None] = mapped_column(String(36), comment="操作者ID")
    occurred_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="事件发生时间")
