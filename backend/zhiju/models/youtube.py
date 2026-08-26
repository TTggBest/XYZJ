from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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
from sqlalchemy.dialects.mysql import DATETIME

from zhiju.models.base import Base, IdMixin, TimestampMixin


class YoutubeVideo(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_videos"
    __table_args__ = (
        CheckConstraint("privacy_status IN ('public','private','unlisted')", name="valid_privacy_status"),
        CheckConstraint("publish_status IN ('draft','scheduled','published','deleted','error')", name="valid_publish_status"),
        CheckConstraint("source IN ('manual','youtube_sync')", name="valid_source"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_nonnegative"),
        UniqueConstraint("operation_package_id", name="uq_youtube_videos_operation_package"),
        Index("ix_youtube_videos_channel_status", "channel_id", "publish_status", "privacy_status"),
        Index("ix_youtube_videos_package", "operation_package_id"),
        {"comment": "YouTube视频登记及当前发布状态"},
    )

    youtube_video_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, comment="YouTube视频外部ID")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="所属频道内部ID")
    operation_package_id: Mapped[str | None] = mapped_column(ForeignKey("operation_packages.id", ondelete="SET NULL"), comment="来源运营包ID")
    drama_id: Mapped[str | None] = mapped_column(ForeignKey("dramas.id", ondelete="SET NULL"), comment="关联剧目内部ID")
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("channel_schedule_entries.id", ondelete="SET NULL"), comment="关联排期ID")
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="YouTube当前标题")
    description: Mapped[str | None] = mapped_column(Text, comment="YouTube当前说明")
    url: Mapped[str] = mapped_column(String(1000), nullable=False, comment="YouTube视频地址")
    privacy_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="公开视频、私享或不公开")
    publish_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="草稿、预约、已发布、删除或异常")
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", comment="是否被运营标记为禁播")
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="YouTube预约发布时间")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="实际发布时间")
    duration_seconds: Mapped[int | None] = mapped_column(Integer, comment="视频时长秒数")
    source: Mapped[str] = mapped_column(String(20), nullable=False, comment="人工登记或YouTube同步")
    etag: Mapped[str | None] = mapped_column(String(255), comment="YouTube资源ETag")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后同步时间")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="确认从YouTube删除的时间")


class YoutubeVideoPlaylistMembership(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_video_playlist_memberships"
    __table_args__ = (
        CheckConstraint("status IN ('active','removed')", name="valid_status"),
        CheckConstraint("source IN ('manual','youtube_sync','analytics_reorder')", name="valid_source"),
        CheckConstraint("position_number IS NULL OR position_number >= 0", name="position_nonnegative"),
        CheckConstraint("score IS NULL OR score >= 0", name="score_nonnegative"),
        UniqueConstraint("video_id", "playlist_id", name="uq_youtube_video_playlist_memberships_pair"),
        Index("ix_youtube_video_playlist_memberships_playlist", "playlist_id", "status"),
        {"comment": "YouTube视频实际播放列表归属"},
    )

    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.id", ondelete="CASCADE"), nullable=False, comment="视频内部ID")
    playlist_id: Mapped[str] = mapped_column(ForeignKey("channel_playlists.id", ondelete="RESTRICT"), nullable=False, comment="播放列表内部ID")
    youtube_playlist_item_id: Mapped[str | None] = mapped_column(String(100), comment="YouTube播放列表条目外部ID")
    position_number: Mapped[int | None] = mapped_column(Integer, comment="YouTube播放列表内位置")
    score: Mapped[Decimal | None] = mapped_column(Numeric(18, 5), comment="当前动态排序综合评分")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", comment="当前归属状态")
    source: Mapped[str] = mapped_column(String(30), nullable=False, server_default="youtube_sync", comment="人工、YouTube同步或分析重排来源")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后同步时间")


class YoutubePlaylistOrderHistory(IdMixin, Base):
    __tablename__ = "youtube_playlist_order_history"
    __table_args__ = (
        CheckConstraint("old_position IS NULL OR old_position >= 0", name="old_position_nonnegative"),
        CheckConstraint("new_position IS NULL OR new_position >= 0", name="new_position_nonnegative"),
        CheckConstraint("old_score IS NULL OR old_score >= 0", name="old_score_nonnegative"),
        CheckConstraint("new_score IS NULL OR new_score >= 0", name="new_score_nonnegative"),
        CheckConstraint("old_status IS NULL OR old_status IN ('active','removed')", name="valid_old_status"),
        CheckConstraint("new_status IN ('active','removed')", name="valid_new_status"),
        Index("ix_youtube_playlist_order_history_playlist_time", "playlist_id", "changed_at"),
        Index("ix_youtube_playlist_order_history_membership_time", "membership_id", "changed_at"),
        {"comment": "播放列表视频位置、评分和归属状态变更历史"},
    )

    membership_id: Mapped[str] = mapped_column(ForeignKey("youtube_video_playlist_memberships.id", ondelete="CASCADE"), nullable=False, comment="视频播放列表归属ID")
    playlist_id: Mapped[str] = mapped_column(ForeignKey("channel_playlists.id", ondelete="CASCADE"), nullable=False, comment="播放列表内部ID")
    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.id", ondelete="CASCADE"), nullable=False, comment="视频内部ID")
    old_position: Mapped[int | None] = mapped_column(Integer, comment="变更前位置")
    new_position: Mapped[int | None] = mapped_column(Integer, comment="变更后位置")
    old_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 5), comment="变更前排序评分")
    new_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 5), comment="变更后排序评分")
    old_status: Mapped[str | None] = mapped_column(String(20), comment="变更前归属状态")
    new_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="变更后归属状态")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="排序或归属变化原因")
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="操作者类型")
    actor_id: Mapped[str | None] = mapped_column(String(36), comment="操作者内部ID")
    changed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="变更时间")


class YoutubeVideoStatusHistory(IdMixin, Base):
    __tablename__ = "youtube_video_status_history"
    __table_args__ = (
        Index("ix_youtube_video_status_history_video_time", "video_id", "changed_at"),
        {"comment": "YouTube视频发布状态变化历史"},
    )

    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.id", ondelete="CASCADE"), nullable=False, comment="视频内部ID")
    old_publish_status: Mapped[str | None] = mapped_column(String(20), comment="变化前发布状态")
    new_publish_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="变化后发布状态")
    old_privacy_status: Mapped[str | None] = mapped_column(String(20), comment="变化前隐私状态")
    new_privacy_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="变化后隐私状态")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="状态变化原因")
    source: Mapped[str] = mapped_column(String(30), nullable=False, comment="状态变化来源")
    changed_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, comment="状态变化时间")


class YoutubeComment(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_comments"
    __table_args__ = (
        CheckConstraint("reply_status IN ('unreplied','suggested','replied','ignored','failed')", name="valid_reply_status"),
        CheckConstraint("moderation_status IN ('published','held','likely_spam','rejected','deleted')", name="valid_moderation_status"),
        CheckConstraint("like_count >= 0", name="like_count_nonnegative"),
        Index("ix_youtube_comments_channel_reply", "channel_id", "reply_status", "published_at"),
        Index("ix_youtube_comments_video_time", "video_id", "published_at"),
        {"comment": "YouTube评论及运营分析字段"},
    )

    youtube_comment_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, comment="YouTube评论外部ID")
    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.id", ondelete="CASCADE"), nullable=False, comment="所属视频内部ID")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False, comment="所属频道内部ID")
    parent_comment_id: Mapped[str | None] = mapped_column(ForeignKey("youtube_comments.id", ondelete="CASCADE"), comment="父评论内部ID")
    author_channel_id: Mapped[str | None] = mapped_column(String(100), comment="评论人YouTube频道ID")
    author_display_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="评论人显示昵称")
    original_text: Mapped[str] = mapped_column(Text, nullable=False, comment="原评论正文")
    translated_text: Mapped[str | None] = mapped_column(Text, comment="评论中文翻译")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="评论发布时间")
    youtube_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="YouTube评论更新时间")
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="评论点赞数")
    is_channel_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", comment="是否频道自身评论")
    reply_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unreplied", comment="回复处理状态")
    moderation_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="published", comment="YouTube审核状态")
    sentiment: Mapped[str | None] = mapped_column(String(40), comment="正向、负向、中性等情绪")
    analysis_label: Mapped[str | None] = mapped_column(String(80), comment="质疑、敏感、剧情讨论等分析标签")
    recommended_reply: Mapped[str | None] = mapped_column(Text, comment="频道语言推荐回复")
    recommended_reply_translation: Mapped[str | None] = mapped_column(Text, comment="推荐回复中文翻译")
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="最后同步时间")


class YoutubeCommentReply(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_comment_replies"
    __table_args__ = (
        CheckConstraint("generation_method IN ('ai','manual','template')", name="valid_generation_method"),
        CheckConstraint("approval_status IN ('not_required','pending','approved','rejected')", name="valid_approval_status"),
        CheckConstraint("publish_status IN ('draft','queued','published','failed','cancelled')", name="valid_publish_status"),
        Index("ix_youtube_comment_replies_comment_status", "comment_id", "publish_status"),
        {"comment": "YouTube评论回复版本与发布状态"},
    )

    comment_id: Mapped[str] = mapped_column(ForeignKey("youtube_comments.id", ondelete="CASCADE"), nullable=False, comment="被回复评论内部ID")
    youtube_reply_id: Mapped[str | None] = mapped_column(String(120), unique=True, comment="发布后的YouTube回复ID")
    reply_text: Mapped[str] = mapped_column(Text, nullable=False, comment="频道语言回复正文")
    reply_translation: Mapped[str | None] = mapped_column(Text, comment="回复中文翻译")
    generation_method: Mapped[str] = mapped_column(String(20), nullable=False, comment="AI、人工或模板生成")
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="审核状态")
    publish_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="发布状态")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="回复实际发布时间")
    error_message: Mapped[str | None] = mapped_column(Text, comment="发布失败脱敏信息")


class YoutubeChannelDailyMetric(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_channel_daily_metrics"
    __table_args__ = (
        UniqueConstraint("channel_id", "metric_date", name="uq_youtube_channel_daily_metrics_day"),
        CheckConstraint("views >= 0 AND watch_time_minutes >= 0 AND subscribers_gained >= 0 AND subscribers_lost >= 0 AND impressions >= 0", name="metrics_nonnegative"),
        CheckConstraint("ctr IS NULL OR (ctr >= 0 AND ctr <= 1)", name="ctr_range"),
        Index("ix_youtube_channel_daily_metrics_date", "metric_date", "channel_id"),
        {"comment": "YouTube频道每日Analytics历史快照"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, comment="指标所属日期")
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="观看次数")
    watch_time_minutes: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, server_default="0", comment="观看时长分钟")
    subscribers_gained: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="新增订阅数")
    subscribers_lost: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="流失订阅数")
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="展示次数")
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), comment="展示点击率")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="本快照同步时间")


class YoutubeVideoDailyMetric(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_video_daily_metrics"
    __table_args__ = (
        UniqueConstraint("video_id", "metric_date", name="uq_youtube_video_daily_metrics_day"),
        CheckConstraint("views >= 0 AND impressions >= 0 AND watch_time_minutes >= 0 AND likes >= 0 AND comments >= 0 AND subscribers_gained >= 0", name="metrics_nonnegative"),
        CheckConstraint("ctr IS NULL OR (ctr >= 0 AND ctr <= 1)", name="ctr_range"),
        CheckConstraint("average_view_duration_seconds IS NULL OR average_view_duration_seconds >= 0", name="duration_nonnegative"),
        Index("ix_youtube_video_daily_metrics_date", "metric_date", "video_id"),
        {"comment": "YouTube视频每日Analytics历史快照"},
    )

    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.id", ondelete="CASCADE"), nullable=False, comment="视频内部ID")
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, comment="指标所属日期")
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="观看次数")
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="展示次数")
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), comment="展示点击率")
    watch_time_minutes: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, server_default="0", comment="观看时长分钟")
    average_view_duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), comment="平均观看时长秒数")
    likes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="点赞数")
    comments: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="评论数")
    subscribers_gained: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="带来的新增订阅数")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="本快照同步时间")


class YoutubeAnalyticsBreakdown(IdMixin, TimestampMixin, Base):
    __tablename__ = "youtube_analytics_breakdowns"
    __table_args__ = (
        CheckConstraint("scope_type IN ('channel','video')", name="valid_scope_type"),
        CheckConstraint("dimension_type IN ('country','device','traffic_source','age_group','gender','viewer_type')", name="valid_dimension_type"),
        CheckConstraint("(scope_type = 'channel' AND video_id IS NULL) OR (scope_type = 'video' AND video_id IS NOT NULL)", name="valid_scope_reference"),
        CheckConstraint("views >= 0 AND watch_time_minutes >= 0 AND impressions >= 0", name="metrics_nonnegative"),
        CheckConstraint("ctr IS NULL OR (ctr >= 0 AND ctr <= 1)", name="ctr_range"),
        UniqueConstraint("scope_type", "scope_entity_id", "metric_date", "dimension_type", "dimension_value", name="uq_youtube_analytics_breakdowns_identity"),
        Index("ix_youtube_analytics_breakdowns_channel_date", "channel_id", "metric_date", "dimension_type"),
        {"comment": "YouTube国家、设备、流量来源等维度指标"},
    )

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="频道级或视频级")
    scope_entity_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="频道ID或视频ID组成的非空作用域键")
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    video_id: Mapped[str | None] = mapped_column(ForeignKey("youtube_videos.id", ondelete="CASCADE"), comment="视频内部ID，频道级为空")
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, comment="指标所属日期")
    dimension_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="国家、设备或流量来源等维度")
    dimension_value: Mapped[str] = mapped_column(String(255), nullable=False, comment="维度值")
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="该维度观看次数")
    watch_time_minutes: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, server_default="0", comment="该维度观看时长分钟")
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", comment="该维度展示次数")
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5), comment="该维度展示点击率")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="本指标同步时间")


class SyncWatermark(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_watermarks"
    __table_args__ = (
        CheckConstraint("status IN ('idle','running','completed','failed')", name="valid_status"),
        UniqueConstraint("channel_id", "data_type", name="uq_sync_watermarks_channel_data_type"),
        Index("ix_sync_watermarks_status_lease", "status", "lease_expires_at"),
        {"comment": "按频道和数据类型隔离的YouTube同步水位"},
    )

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, comment="频道内部ID")
    data_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="视频、评论、频道指标等同步类型")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="idle", comment="同步状态")
    cursor_value: Mapped[str | None] = mapped_column(String(1000), comment="第三方分页或增量游标")
    data_through_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="数据已同步至该时间")
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近开始时间")
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近成功时间")
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近失败时间")
    error_code: Mapped[str | None] = mapped_column(String(120), comment="最近失败代码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="最近失败脱敏信息")
    lease_owner: Mapped[str | None] = mapped_column(String(120), comment="当前同步工作器")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="同步租约到期时间")


class ApiRequestLog(IdMixin, Base):
    __tablename__ = "api_request_logs"
    __table_args__ = (
        CheckConstraint("result IN ('success','failure','cancelled')", name="valid_result"),
        CheckConstraint("quota_units >= 0", name="quota_nonnegative"),
        Index("ix_api_request_logs_channel_time", "channel_id", "requested_at"),
        Index("ix_api_request_logs_data_type_time", "data_type", "requested_at"),
        {"comment": "YouTube API请求与结果日志"},
    )

    request_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, comment="调用方生成的API请求幂等键")
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), comment="关联频道内部ID")
    authorization_id: Mapped[str | None] = mapped_column(ForeignKey("account_channel_authorizations.id", ondelete="SET NULL"), comment="使用的频道授权关系ID")
    data_type: Mapped[str] = mapped_column(String(60), nullable=False, comment="请求对应的数据类型")
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, comment="YouTube API端点")
    http_method: Mapped[str] = mapped_column(String(10), nullable=False, comment="HTTP方法")
    http_status: Mapped[int | None] = mapped_column(Integer, comment="HTTP状态码")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="请求结果")
    quota_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="本次消耗配额单位")
    response_item_count: Mapped[int | None] = mapped_column(Integer, comment="成功解析的业务条目数")
    error_code: Mapped[str | None] = mapped_column(String(120), comment="失败代码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="失败脱敏信息")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="请求开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="请求结束时间")


class QuotaUsageLog(IdMixin, Base):
    __tablename__ = "quota_usage_logs"
    __table_args__ = (
        UniqueConstraint("api_request_log_id", name="uq_quota_usage_logs_request"),
        CheckConstraint("units >= 0", name="units_nonnegative"),
        Index("ix_quota_usage_logs_date_channel", "quota_date", "channel_id"),
        {"comment": "YouTube API配额消耗明细"},
    )

    api_request_log_id: Mapped[str] = mapped_column(ForeignKey("api_request_logs.id", ondelete="CASCADE"), nullable=False, comment="API请求日志ID")
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), comment="关联频道内部ID")
    account_id: Mapped[str | None] = mapped_column(ForeignKey("google_accounts.id", ondelete="SET NULL"), comment="配额所属Google账号ID")
    quota_date: Mapped[date] = mapped_column(Date, nullable=False, comment="YouTube配额统计日期")
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, comment="消耗配额的API端点")
    units: Mapped[int] = mapped_column(Integer, nullable=False, comment="消耗配额单位")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="记录时间")
