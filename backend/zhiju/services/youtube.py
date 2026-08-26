from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import (
    AccountChannelAuthorization,
    ApiRequestLog,
    Channel,
    ChannelPlaylist,
    ChannelScheduleEntry,
    Drama,
    OperationPackage,
    OAuthGrant,
    QuotaUsageLog,
    ScheduleChangeHistory,
    SyncWatermark,
    SystemEvent,
    YoutubeAnalyticsBreakdown,
    YoutubeChannelDailyMetric,
    YoutubeComment,
    YoutubeCommentReply,
    YoutubePlaylistOrderHistory,
    YoutubeVideo,
    YoutubeVideoDailyMetric,
    YoutubeVideoPlaylistMembership,
    YoutubeVideoStatusHistory,
)
from zhiju.schemas.youtube import (
    AnalyticsBreakdownUpsert,
    ApiRequestRecordCreate,
    ChannelDailyMetricUpsert,
    CommentReplyCreate,
    CommentReplyReview,
    CommentReplyStatusUpdate,
    CommentAnalysisUpdate,
    CommentUpsert,
    PlaylistMembershipUpsert,
    PlaylistOrderChange,
    SyncComplete,
    SyncStart,
    VideoDailyMetricUpsert,
    VideoUpsert,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError, _audit


def _channel(session: Session, channel_id: str) -> Channel:
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise NotFoundError("频道不存在")
    return channel


def _video(session: Session, video_id: str) -> YoutubeVideo:
    video = session.get(YoutubeVideo, video_id)
    if video is None:
        raise NotFoundError("YouTube视频不存在")
    return video


def _api_request_payload(
    request: ApiRequestLog, quota: QuotaUsageLog
) -> dict[str, object]:
    return {
        **request.__dict__,
        "account_id": quota.account_id,
        "quota_log_id": quota.id,
        "quota_date": quota.quota_date,
        "recorded_at": quota.recorded_at,
    }


def record_api_request(
    session: Session, payload: ApiRequestRecordCreate
) -> dict[str, object]:
    request_key = payload.request_key.strip()
    existing = session.scalar(
        select(ApiRequestLog).where(ApiRequestLog.request_key == request_key)
    )
    if existing is not None:
        quota = session.scalar(
            select(QuotaUsageLog).where(
                QuotaUsageLog.api_request_log_id == existing.id
            )
        )
        if quota is None:
            raise ConflictError("API请求日志缺少配额明细")
        expected_channel_id = payload.channel_id
        if payload.authorization_id:
            authorization = session.get(
                AccountChannelAuthorization, payload.authorization_id
            )
            if authorization is not None and expected_channel_id is None:
                expected_channel_id = authorization.channel_id
        immutable_values = (
            existing.channel_id,
            existing.authorization_id,
            existing.data_type,
            existing.endpoint,
            existing.http_method,
            existing.result,
            existing.quota_units,
            quota.quota_date,
        )
        submitted_values = (
            expected_channel_id,
            payload.authorization_id,
            payload.data_type.strip(),
            payload.endpoint.strip(),
            payload.http_method.strip().upper(),
            payload.result,
            payload.quota_units,
            payload.quota_date,
        )
        if immutable_values != submitted_values:
            raise ConflictError("API请求幂等键对应的内容不一致")
        return _api_request_payload(existing, quota)

    channel_id = payload.channel_id
    authorization = None
    if payload.authorization_id:
        authorization = session.get(
            AccountChannelAuthorization, payload.authorization_id
        )
        if authorization is None:
            raise NotFoundError("频道授权关系不存在")
        if authorization.status != "active":
            raise ConflictError("频道授权关系不是有效状态")
        if channel_id is None:
            channel_id = authorization.channel_id
        elif authorization.channel_id != channel_id:
            raise ConflictError("频道授权关系与API请求频道不一致")
    if channel_id is not None:
        _channel(session, channel_id)

    values = payload.model_dump(exclude={"quota_date", "channel_id"})
    values["request_key"] = request_key
    values["data_type"] = payload.data_type.strip()
    values["endpoint"] = payload.endpoint.strip()
    values["http_method"] = payload.http_method.strip().upper()
    request = ApiRequestLog(channel_id=channel_id, **values)
    session.add(request)
    try:
        session.flush()
        quota = QuotaUsageLog(
            api_request_log_id=request.id,
            channel_id=channel_id,
            account_id=authorization.account_id if authorization else None,
            quota_date=payload.quota_date,
            endpoint=request.endpoint,
            units=request.quota_units,
            recorded_at=payload.finished_at or payload.requested_at,
        )
        session.add(quota)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("API请求幂等键或配额记录冲突") from exc
    session.refresh(request)
    session.refresh(quota)
    return _api_request_payload(request, quota)


def list_api_requests(
    session: Session,
    *,
    channel_id: str | None = None,
    authorization_id: str | None = None,
    data_type: str | None = None,
    result: str | None = None,
    date_from=None,
    date_to=None,
) -> list[dict[str, object]]:
    statement = (
        select(ApiRequestLog, QuotaUsageLog)
        .join(QuotaUsageLog, QuotaUsageLog.api_request_log_id == ApiRequestLog.id)
    )
    if channel_id:
        statement = statement.where(ApiRequestLog.channel_id == channel_id)
    if authorization_id:
        statement = statement.where(ApiRequestLog.authorization_id == authorization_id)
    if data_type:
        statement = statement.where(ApiRequestLog.data_type == data_type)
    if result:
        statement = statement.where(ApiRequestLog.result == result)
    if date_from:
        statement = statement.where(func.date(ApiRequestLog.requested_at) >= date_from)
    if date_to:
        statement = statement.where(func.date(ApiRequestLog.requested_at) <= date_to)
    rows = session.execute(
        statement.order_by(ApiRequestLog.requested_at.desc(), ApiRequestLog.id)
    ).all()
    return [_api_request_payload(request, quota) for request, quota in rows]


def list_quota_usage(
    session: Session,
    *,
    channel_id: str | None = None,
    account_id: str | None = None,
    date_from=None,
    date_to=None,
) -> list[dict[str, object]]:
    statement = (
        select(QuotaUsageLog, ApiRequestLog.request_key)
        .join(ApiRequestLog, ApiRequestLog.id == QuotaUsageLog.api_request_log_id)
    )
    if channel_id:
        statement = statement.where(QuotaUsageLog.channel_id == channel_id)
    if account_id:
        statement = statement.where(QuotaUsageLog.account_id == account_id)
    if date_from:
        statement = statement.where(QuotaUsageLog.quota_date >= date_from)
    if date_to:
        statement = statement.where(QuotaUsageLog.quota_date <= date_to)
    rows = session.execute(
        statement.order_by(QuotaUsageLog.quota_date.desc(), QuotaUsageLog.recorded_at.desc())
    ).all()
    return [
        {**quota.__dict__, "request_key": request_key}
        for quota, request_key in rows
    ]


def summarize_quota_usage(
    session: Session,
    *,
    channel_id: str | None = None,
    account_id: str | None = None,
    date_from=None,
    date_to=None,
) -> list[dict[str, object]]:
    statement = select(
        QuotaUsageLog.quota_date,
        QuotaUsageLog.channel_id,
        QuotaUsageLog.account_id,
        QuotaUsageLog.endpoint,
        func.count(QuotaUsageLog.id).label("request_count"),
        func.sum(QuotaUsageLog.units).label("total_units"),
    )
    if channel_id:
        statement = statement.where(QuotaUsageLog.channel_id == channel_id)
    if account_id:
        statement = statement.where(QuotaUsageLog.account_id == account_id)
    if date_from:
        statement = statement.where(QuotaUsageLog.quota_date >= date_from)
    if date_to:
        statement = statement.where(QuotaUsageLog.quota_date <= date_to)
    rows = session.execute(
        statement.group_by(
            QuotaUsageLog.quota_date,
            QuotaUsageLog.channel_id,
            QuotaUsageLog.account_id,
            QuotaUsageLog.endpoint,
        ).order_by(QuotaUsageLog.quota_date.desc(), QuotaUsageLog.endpoint)
    ).all()
    return [dict(row._mapping) for row in rows]


def upsert_video(session: Session, payload: VideoUpsert) -> YoutubeVideo:
    _channel(session, payload.channel_id)
    video = session.scalar(
        select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == payload.youtube_video_id).with_for_update()
    )
    if video is not None and video.channel_id != payload.channel_id:
        raise ConflictError("YouTube视频ID已属于其他频道")
    if (
        video is not None
        and video.operation_package_id is not None
        and payload.operation_package_id is not None
        and video.operation_package_id != payload.operation_package_id
    ):
        raise ConflictError("YouTube视频已经绑定运营包，不能改绑")

    package_id = payload.operation_package_id or (
        video.operation_package_id if video is not None else None
    )
    package = None
    if package_id:
        package = session.scalar(
            select(OperationPackage)
            .where(OperationPackage.id == package_id)
            .with_for_update()
        )
        if package is None or package.channel_id != payload.channel_id:
            raise ConflictError("运营包不存在或不属于当前频道")
        first_link = video is None or video.operation_package_id is None
        if first_link and package.status not in {"approved", "delivered"}:
            raise ConflictError("运营包尚未通过最终审核，不能绑定YouTube视频")
        occupied = session.scalar(
            select(YoutubeVideo.id).where(
                YoutubeVideo.operation_package_id == package.id,
                YoutubeVideo.id != (video.id if video is not None else ""),
            )
        )
        if occupied is not None:
            raise ConflictError("该运营包已经绑定其他YouTube视频")

    drama_id = payload.drama_id or (
        package.drama_id if package is not None else (video.drama_id if video else None)
    )
    schedule_id = payload.schedule_id or (
        package.schedule_id if package is not None else (video.schedule_id if video else None)
    )
    if package is not None and drama_id != package.drama_id:
        raise ConflictError("视频剧目与运营包剧目不一致")
    if package is not None and package.schedule_id and schedule_id != package.schedule_id:
        raise ConflictError("视频排期与运营包排期不一致")
    if drama_id and session.get(Drama, drama_id) is None:
        raise NotFoundError("剧目不存在")
    schedule = None
    if schedule_id:
        schedule = session.scalar(
            select(ChannelScheduleEntry)
            .where(ChannelScheduleEntry.id == schedule_id)
            .with_for_update()
        )
        if schedule is None or schedule.channel_id != payload.channel_id:
            raise ConflictError("排期不存在或不属于当前频道")
        if drama_id and schedule.drama_id != drama_id:
            raise ConflictError("视频剧目与排期剧目不一致")

    values = payload.model_dump()
    values.update(
        operation_package_id=package_id,
        drama_id=drama_id,
        schedule_id=schedule_id,
    )
    now = datetime.now(timezone.utc)
    if video is None:
        video = YoutubeVideo(**values)
        video.last_synced_at = payload.last_synced_at or now
        session.add(video)
        session.flush()
        session.add(
            YoutubeVideoStatusHistory(
                video_id=video.id,
                old_publish_status=None,
                new_publish_status=video.publish_status,
                old_privacy_status=None,
                new_privacy_status=video.privacy_status,
                reason="首次登记YouTube视频",
                source=payload.source,
                changed_at=now,
            )
        )
        action = "youtube_video.created"
    else:
        old_publish = video.publish_status
        old_privacy = video.privacy_status
        for field, value in values.items():
            setattr(video, field, value)
        video.last_synced_at = payload.last_synced_at or now
        if old_publish != video.publish_status or old_privacy != video.privacy_status:
            session.add(
                YoutubeVideoStatusHistory(
                    video_id=video.id,
                    old_publish_status=old_publish,
                    new_publish_status=video.publish_status,
                    old_privacy_status=old_privacy,
                    new_privacy_status=video.privacy_status,
                    reason="YouTube视频同步状态变化",
                    source=payload.source,
                    changed_at=now,
                )
            )
        action = "youtube_video.updated"
    session.flush()
    video.deleted_at = now if payload.publish_status == "deleted" else None
    if (
        package is not None
        and package.status == "approved"
        and payload.publish_status in {"draft", "scheduled", "published"}
    ):
        old_package_status = package.status
        package.status = "delivered"
        package.delivered_at = now
        session.add(
            SystemEvent(
                entity_type="operation_package",
                entity_id=package.id,
                old_status=old_package_status,
                new_status="delivered",
                reason=f"绑定YouTube视频 {payload.youtube_video_id}",
                actor_type="system",
                occurred_at=now,
            )
        )
        _audit(session, "package.delivered", "operation_package", package.id)
    if schedule is not None:
        target_schedule_status = None
        if payload.publish_status == "scheduled" and schedule.status in {"planned", "reserved"}:
            target_schedule_status = "confirmed"
        elif payload.publish_status == "published" and schedule.status in {
            "planned",
            "reserved",
            "confirmed",
        }:
            target_schedule_status = "published"
        elif payload.publish_status in {"scheduled", "published"} and schedule.status in {
            "replaced",
            "cancelled",
        }:
            raise ConflictError("已替换或取消的排期不能绑定预约或已发布视频")
        if target_schedule_status is not None:
            old_schedule_status = schedule.status
            schedule.status = target_schedule_status
            session.add(
                ScheduleChangeHistory(
                    schedule_id=schedule.id,
                    old_drama_id=schedule.drama_id,
                    new_drama_id=schedule.drama_id,
                    old_planned_utc_time=schedule.planned_utc_time,
                    new_planned_utc_time=schedule.planned_utc_time,
                    old_status=old_schedule_status,
                    new_status=target_schedule_status,
                    reason=f"YouTube视频回写: {payload.youtube_video_id}",
                    actor_type="system",
                    changed_at=now,
                )
            )
            _audit(session, "schedule.status_changed", "channel_schedule_entry", schedule.id)
    _audit(session, action, "youtube_video", video.id)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("YouTube视频或运营包绑定发生冲突") from exc
    session.refresh(video)
    return video


def list_videos(session: Session, *, channel_id=None, publish_status=None, privacy_status=None) -> list[YoutubeVideo]:
    statement = select(YoutubeVideo)
    if channel_id:
        statement = statement.where(YoutubeVideo.channel_id == channel_id)
    if publish_status:
        statement = statement.where(YoutubeVideo.publish_status == publish_status)
    if privacy_status:
        statement = statement.where(YoutubeVideo.privacy_status == privacy_status)
    return list(session.scalars(statement.order_by(YoutubeVideo.published_at.desc(), YoutubeVideo.created_at.desc())))


def _playlist(session: Session, playlist_id: str) -> ChannelPlaylist:
    playlist = session.get(ChannelPlaylist, playlist_id)
    if playlist is None or playlist.status == "deleted":
        raise NotFoundError("播放列表不存在")
    return playlist


def _ensure_playlist_position_available(
    session: Session,
    playlist_id: str,
    position_number: int | None,
    membership_id: str | None = None,
) -> None:
    if position_number is None:
        return
    statement = select(YoutubeVideoPlaylistMembership.id).where(
        YoutubeVideoPlaylistMembership.playlist_id == playlist_id,
        YoutubeVideoPlaylistMembership.position_number == position_number,
        YoutubeVideoPlaylistMembership.status == "active",
    )
    if membership_id:
        statement = statement.where(YoutubeVideoPlaylistMembership.id != membership_id)
    if session.scalar(statement) is not None:
        raise ConflictError("播放列表中的有效视频位置不能重复")


def _playlist_history(
    session: Session,
    membership: YoutubeVideoPlaylistMembership,
    *,
    old_position: int | None,
    old_score,
    old_status: str | None,
    reason: str,
    actor_type: str,
) -> None:
    session.add(
        YoutubePlaylistOrderHistory(
            membership_id=membership.id,
            playlist_id=membership.playlist_id,
            video_id=membership.video_id,
            old_position=old_position,
            new_position=membership.position_number,
            old_score=old_score,
            new_score=membership.score,
            old_status=old_status,
            new_status=membership.status,
            reason=reason,
            actor_type=actor_type,
            changed_at=datetime.now(timezone.utc),
        )
    )


def upsert_playlist_membership(
    session: Session, payload: PlaylistMembershipUpsert
) -> YoutubeVideoPlaylistMembership:
    video = _video(session, payload.video_id)
    playlist = _playlist(session, payload.playlist_id)
    if video.channel_id != playlist.channel_id:
        raise ConflictError("视频与播放列表不属于同一频道")
    membership = session.scalar(
        select(YoutubeVideoPlaylistMembership)
        .where(
            YoutubeVideoPlaylistMembership.video_id == video.id,
            YoutubeVideoPlaylistMembership.playlist_id == playlist.id,
        )
        .with_for_update()
    )
    _ensure_playlist_position_available(
        session,
        playlist.id,
        payload.position_number if payload.status == "active" else None,
        membership.id if membership else None,
    )
    now = datetime.now(timezone.utc)
    values = payload.model_dump()
    if payload.source == "youtube_sync" and values["last_synced_at"] is None:
        values["last_synced_at"] = now
    if membership is None:
        membership = YoutubeVideoPlaylistMembership(**values)
        session.add(membership)
        session.flush()
        _playlist_history(
            session,
            membership,
            old_position=None,
            old_score=None,
            old_status=None,
            reason="首次登记视频播放列表归属",
            actor_type=payload.source,
        )
        action = "youtube_playlist_membership.created"
    else:
        old_position = membership.position_number
        old_score = membership.score
        old_status = membership.status
        for field, value in values.items():
            setattr(membership, field, value)
        if (
            old_position != membership.position_number
            or old_score != membership.score
            or old_status != membership.status
        ):
            _playlist_history(
                session,
                membership,
                old_position=old_position,
                old_score=old_score,
                old_status=old_status,
                reason="YouTube同步播放列表位置或归属变化"
                if payload.source == "youtube_sync"
                else "人工更新播放列表归属",
                actor_type=payload.source,
            )
        action = "youtube_playlist_membership.updated"
    try:
        session.flush()
        _audit(session, action, "youtube_playlist_membership", membership.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("视频播放列表归属数据冲突") from exc
    session.refresh(membership)
    return membership


def list_playlist_memberships(
    session: Session,
    *,
    playlist_id: str | None = None,
    video_id: str | None = None,
    status: str | None = None,
) -> list[YoutubeVideoPlaylistMembership]:
    statement = select(YoutubeVideoPlaylistMembership)
    if playlist_id:
        statement = statement.where(YoutubeVideoPlaylistMembership.playlist_id == playlist_id)
    if video_id:
        statement = statement.where(YoutubeVideoPlaylistMembership.video_id == video_id)
    if status:
        statement = statement.where(YoutubeVideoPlaylistMembership.status == status)
    return list(
        session.scalars(
            statement.order_by(
                YoutubeVideoPlaylistMembership.playlist_id,
                YoutubeVideoPlaylistMembership.position_number,
                YoutubeVideoPlaylistMembership.created_at,
            )
        )
    )


def change_playlist_membership_order(
    session: Session, membership_id: str, payload: PlaylistOrderChange
) -> YoutubeVideoPlaylistMembership:
    membership = session.scalar(
        select(YoutubeVideoPlaylistMembership)
        .where(YoutubeVideoPlaylistMembership.id == membership_id)
        .with_for_update()
    )
    if membership is None:
        raise NotFoundError("视频播放列表归属不存在")
    if membership.status != "active":
        raise ConflictError("已移除的视频不能参与播放列表重排")
    _ensure_playlist_position_available(
        session, membership.playlist_id, payload.position_number, membership.id
    )
    old_position = membership.position_number
    old_score = membership.score
    membership.position_number = payload.position_number
    membership.score = payload.score
    membership.source = "analytics_reorder"
    if old_position != membership.position_number or old_score != membership.score:
        _playlist_history(
            session,
            membership,
            old_position=old_position,
            old_score=old_score,
            old_status=membership.status,
            reason=payload.reason,
            actor_type="analytics_reorder",
        )
    session.flush()
    _audit(session, "youtube_playlist_membership.reordered", "youtube_playlist_membership", membership.id)
    session.commit()
    session.refresh(membership)
    return membership


def list_playlist_order_history(
    session: Session, playlist_id: str
) -> list[YoutubePlaylistOrderHistory]:
    _playlist(session, playlist_id)
    return list(
        session.scalars(
            select(YoutubePlaylistOrderHistory)
            .where(YoutubePlaylistOrderHistory.playlist_id == playlist_id)
            .order_by(YoutubePlaylistOrderHistory.changed_at.desc())
        )
    )


def upsert_comment(session: Session, payload: CommentUpsert) -> YoutubeComment:
    video = _video(session, payload.video_id)
    if video.channel_id != payload.channel_id:
        raise ConflictError("评论频道与视频频道不一致")
    if payload.parent_comment_id:
        parent = session.get(YoutubeComment, payload.parent_comment_id)
        if parent is None:
            raise NotFoundError("父评论不存在")
        if parent.video_id != payload.video_id or parent.channel_id != payload.channel_id:
            raise ConflictError("父评论与当前评论不属于同一视频和频道")
    comment = session.scalar(
        select(YoutubeComment).where(YoutubeComment.youtube_comment_id == payload.youtube_comment_id).with_for_update()
    )
    if comment is None:
        comment = YoutubeComment(**payload.model_dump())
        session.add(comment)
        action = "youtube_comment.created"
    else:
        if comment.video_id != payload.video_id:
            raise ConflictError("YouTube评论ID已属于其他视频")
        source_fields = {
            "parent_comment_id",
            "author_channel_id",
            "author_display_name",
            "original_text",
            "published_at",
            "youtube_updated_at",
            "like_count",
            "is_channel_owner",
            "moderation_status",
            "last_synced_at",
        }
        for field, value in payload.model_dump(include=source_fields).items():
            setattr(comment, field, value)
        action = "youtube_comment.updated"
    session.flush()
    _audit(session, action, "youtube_comment", comment.id)
    session.commit()
    session.refresh(comment)
    return comment


def list_comments(
    session: Session,
    *,
    channel_id=None,
    video_id=None,
    reply_status=None,
    include_channel_owner=False,
) -> list[YoutubeComment]:
    statement = select(YoutubeComment)
    if channel_id:
        statement = statement.where(YoutubeComment.channel_id == channel_id)
    if video_id:
        statement = statement.where(YoutubeComment.video_id == video_id)
    if reply_status:
        statement = statement.where(YoutubeComment.reply_status == reply_status)
    if not include_channel_owner:
        statement = statement.where(YoutubeComment.is_channel_owner.is_(False))
    return list(session.scalars(statement.order_by(YoutubeComment.published_at.desc())))


def update_comment_analysis(
    session: Session, comment_id: str, payload: CommentAnalysisUpdate
) -> YoutubeComment:
    comment = session.get(YoutubeComment, comment_id)
    if comment is None:
        raise NotFoundError("评论不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(comment, field, value)
    if comment.recommended_reply and comment.reply_status == "unreplied":
        comment.reply_status = "suggested"
    session.flush()
    _audit(session, "youtube_comment.analysis_updated", "youtube_comment", comment.id)
    session.commit()
    session.refresh(comment)
    return comment


def _reply_event(
    session: Session,
    reply: YoutubeCommentReply,
    old_status: str | None,
    reason: str,
) -> None:
    session.add(
        SystemEvent(
            entity_type="youtube_comment_reply",
            entity_id=reply.id,
            old_status=old_status,
            new_status=reply.publish_status,
            reason=reason,
            actor_type="system",
            occurred_at=datetime.now(timezone.utc),
        )
    )


def create_comment_reply(session: Session, payload: CommentReplyCreate) -> YoutubeCommentReply:
    comment = session.get(YoutubeComment, payload.comment_id)
    if comment is None:
        raise NotFoundError("评论不存在")
    if comment.is_channel_owner:
        raise ConflictError("频道自己的评论不能进入回复队列")
    if comment.moderation_status != "published":
        raise ConflictError("只有正常公开的评论可以回复")
    if payload.approval_status == "rejected":
        raise ConflictError("已拒绝状态不能用于创建新回复")
    if payload.publish_status == "queued" and payload.approval_status not in {
        "approved",
        "not_required",
    }:
        raise ConflictError("回复尚未通过审核，不能进入发布队列")
    active = session.scalar(
        select(YoutubeCommentReply).where(
            YoutubeCommentReply.comment_id == comment.id,
            YoutubeCommentReply.publish_status.in_(("queued", "published")),
        )
    )
    if active is not None:
        raise ConflictError("该评论已有待发布或已发布回复")
    reply = YoutubeCommentReply(**payload.model_dump())
    session.add(reply)
    session.flush()
    comment.reply_status = "suggested"
    _reply_event(session, reply, None, "创建评论回复")
    _audit(session, "youtube_comment_reply.created", "youtube_comment_reply", reply.id)
    session.commit()
    session.refresh(reply)
    return reply


def list_comment_replies(session: Session, comment_id: str | None = None) -> list[YoutubeCommentReply]:
    statement = select(YoutubeCommentReply)
    if comment_id:
        statement = statement.where(YoutubeCommentReply.comment_id == comment_id)
    return list(session.scalars(statement.order_by(YoutubeCommentReply.created_at.desc())))


def review_comment_reply(
    session: Session, reply_id: str, payload: CommentReplyReview
) -> YoutubeCommentReply:
    reply = session.scalar(
        select(YoutubeCommentReply).where(YoutubeCommentReply.id == reply_id).with_for_update()
    )
    if reply is None:
        raise NotFoundError("评论回复不存在")
    if reply.publish_status == "published":
        raise ConflictError("已发布回复不能再审核")
    reply.approval_status = payload.decision
    if payload.decision == "rejected":
        old_status = reply.publish_status
        reply.publish_status = "cancelled"
        comment = session.get(YoutubeComment, reply.comment_id)
        comment.reply_status = "suggested" if comment.recommended_reply else "unreplied"
        _reply_event(session, reply, old_status, "评论回复审核拒绝")
    session.flush()
    _audit(session, f"youtube_comment_reply.{payload.decision}", "youtube_comment_reply", reply.id)
    session.commit()
    session.refresh(reply)
    return reply


def update_comment_reply_status(
    session: Session, reply_id: str, payload: CommentReplyStatusUpdate
) -> YoutubeCommentReply:
    reply = session.scalar(
        select(YoutubeCommentReply).where(YoutubeCommentReply.id == reply_id).with_for_update()
    )
    if reply is None:
        raise NotFoundError("评论回复不存在")
    allowed = {
        "draft": {"queued", "cancelled"},
        "queued": {"published", "failed", "cancelled"},
        "failed": {"queued", "cancelled"},
        "published": set(),
        "cancelled": set(),
    }
    if payload.status not in allowed[reply.publish_status]:
        raise ConflictError(f"评论回复不能从{reply.publish_status}变更为{payload.status}")
    if payload.status == "queued" and reply.approval_status not in {"approved", "not_required"}:
        raise ConflictError("回复尚未通过审核，不能进入发布队列")
    if payload.status == "published" and not payload.youtube_reply_id:
        raise ConflictError("发布成功必须提供YouTube回复ID")
    if payload.status == "failed" and not payload.error_message:
        raise ConflictError("发布失败必须记录脱敏错误信息")
    comment = session.get(YoutubeComment, reply.comment_id)
    old_status = reply.publish_status
    reply.publish_status = payload.status
    if payload.status == "published":
        reply.youtube_reply_id = payload.youtube_reply_id
        reply.published_at = payload.published_at or datetime.now(timezone.utc)
        reply.error_message = None
        comment.reply_status = "replied"
    elif payload.status == "failed":
        reply.error_message = payload.error_message
        comment.reply_status = "failed"
    elif payload.status == "queued":
        reply.error_message = None
        comment.reply_status = "suggested"
    else:
        comment.reply_status = "suggested" if comment.recommended_reply else "unreplied"
    try:
        session.flush()
        _reply_event(session, reply, old_status, f"评论回复状态变更为{payload.status}")
        _audit(session, "youtube_comment_reply.status_updated", "youtube_comment_reply", reply.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("YouTube回复ID已经登记") from exc
    session.refresh(reply)
    return reply


def upsert_channel_metric(session: Session, payload: ChannelDailyMetricUpsert) -> YoutubeChannelDailyMetric:
    _channel(session, payload.channel_id)
    row = session.scalar(
        select(YoutubeChannelDailyMetric)
        .where(
            YoutubeChannelDailyMetric.channel_id == payload.channel_id,
            YoutubeChannelDailyMetric.metric_date == payload.metric_date,
        )
        .with_for_update()
    )
    if row is None:
        row = YoutubeChannelDailyMetric(**payload.model_dump())
        session.add(row)
    else:
        for field, value in payload.model_dump().items():
            setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return row


def list_channel_metrics(session: Session, channel_id=None, date_from=None, date_to=None):
    statement = select(YoutubeChannelDailyMetric)
    if channel_id:
        statement = statement.where(YoutubeChannelDailyMetric.channel_id == channel_id)
    if date_from:
        statement = statement.where(YoutubeChannelDailyMetric.metric_date >= date_from)
    if date_to:
        statement = statement.where(YoutubeChannelDailyMetric.metric_date <= date_to)
    return list(session.scalars(statement.order_by(YoutubeChannelDailyMetric.metric_date.desc())))


def upsert_video_metric(session: Session, payload: VideoDailyMetricUpsert) -> YoutubeVideoDailyMetric:
    _video(session, payload.video_id)
    row = session.scalar(
        select(YoutubeVideoDailyMetric)
        .where(YoutubeVideoDailyMetric.video_id == payload.video_id, YoutubeVideoDailyMetric.metric_date == payload.metric_date)
        .with_for_update()
    )
    if row is None:
        row = YoutubeVideoDailyMetric(**payload.model_dump())
        session.add(row)
    else:
        for field, value in payload.model_dump().items():
            setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return row


def list_video_metrics(session: Session, video_id=None, date_from=None, date_to=None):
    statement = select(YoutubeVideoDailyMetric)
    if video_id:
        statement = statement.where(YoutubeVideoDailyMetric.video_id == video_id)
    if date_from:
        statement = statement.where(YoutubeVideoDailyMetric.metric_date >= date_from)
    if date_to:
        statement = statement.where(YoutubeVideoDailyMetric.metric_date <= date_to)
    return list(session.scalars(statement.order_by(YoutubeVideoDailyMetric.metric_date.desc())))


def upsert_breakdown(session: Session, payload: AnalyticsBreakdownUpsert) -> YoutubeAnalyticsBreakdown:
    _channel(session, payload.channel_id)
    if payload.scope_type == "video":
        if not payload.video_id:
            raise ConflictError("视频级分析必须提供video_id")
        video = _video(session, payload.video_id)
        if video.channel_id != payload.channel_id:
            raise ConflictError("分析视频不属于当前频道")
        scope_entity_id = video.id
    else:
        if payload.video_id:
            raise ConflictError("频道级分析不能提供video_id")
        scope_entity_id = payload.channel_id
    row = session.scalar(
        select(YoutubeAnalyticsBreakdown)
        .where(
            YoutubeAnalyticsBreakdown.scope_type == payload.scope_type,
            YoutubeAnalyticsBreakdown.scope_entity_id == scope_entity_id,
            YoutubeAnalyticsBreakdown.metric_date == payload.metric_date,
            YoutubeAnalyticsBreakdown.dimension_type == payload.dimension_type,
            YoutubeAnalyticsBreakdown.dimension_value == payload.dimension_value,
        )
        .with_for_update()
    )
    values = payload.model_dump()
    if row is None:
        row = YoutubeAnalyticsBreakdown(scope_entity_id=scope_entity_id, **values)
        session.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return row


def list_breakdowns(session: Session, channel_id=None, video_id=None, metric_date=None, dimension_type=None):
    statement = select(YoutubeAnalyticsBreakdown)
    if channel_id:
        statement = statement.where(YoutubeAnalyticsBreakdown.channel_id == channel_id)
    if video_id:
        statement = statement.where(YoutubeAnalyticsBreakdown.video_id == video_id)
    if metric_date:
        statement = statement.where(YoutubeAnalyticsBreakdown.metric_date == metric_date)
    if dimension_type:
        statement = statement.where(YoutubeAnalyticsBreakdown.dimension_type == dimension_type)
    return list(session.scalars(statement.order_by(YoutubeAnalyticsBreakdown.metric_date.desc(), YoutubeAnalyticsBreakdown.dimension_type, YoutubeAnalyticsBreakdown.dimension_value)))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def start_sync(session: Session, channel_id: str, data_type: str, payload: SyncStart) -> SyncWatermark:
    channel = _channel(session, channel_id)
    if channel.status in {"paused", "archived", "deleted"}:
        raise ConflictError("暂停、归档或删除的频道不能启动YouTube同步")
    authorization = session.get(AccountChannelAuthorization, payload.authorization_id)
    if (
        authorization is None
        or authorization.channel_id != channel_id
        or authorization.status != "active"
        or authorization.verified_youtube_channel_id != channel.youtube_channel_id
    ):
        raise ConflictError("频道没有匹配且有效的YouTube授权绑定，禁止同步")
    grant = session.get(OAuthGrant, authorization.oauth_grant_id)
    if grant is None or grant.status != "active":
        raise ConflictError("频道授权使用的OAuth Grant不可用，禁止同步")
    row = session.scalar(
        select(SyncWatermark)
        .where(SyncWatermark.channel_id == channel_id, SyncWatermark.data_type == data_type)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = SyncWatermark(channel_id=channel_id, data_type=data_type, status="idle")
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError("该频道和数据类型的同步水位已被并发创建") from exc
    if row.status == "running" and _as_utc(row.lease_expires_at) and _as_utc(row.lease_expires_at) > now:
        raise ConflictError("该频道和数据类型已有运行中的同步任务")
    row.status = "running"
    row.last_started_at = now
    row.lease_owner = payload.worker_key
    row.lease_expires_at = now + timedelta(seconds=payload.lease_seconds)
    row.error_code = None
    row.error_message = None
    _audit(session, "youtube_sync.started", "sync_watermark", row.id)
    session.commit()
    session.refresh(row)
    return row


def complete_sync(session: Session, channel_id: str, data_type: str, payload: SyncComplete) -> SyncWatermark:
    row = session.scalar(
        select(SyncWatermark)
        .where(SyncWatermark.channel_id == channel_id, SyncWatermark.data_type == data_type)
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("同步水位不存在")
    if row.status != "running" or row.lease_owner != payload.worker_key:
        raise ConflictError("只有持有当前租约的工作器可以完成同步")
    now = datetime.now(timezone.utc)
    if payload.success:
        row.status = "completed"
        row.cursor_value = payload.cursor_value
        row.data_through_at = payload.data_through_at
        row.last_completed_at = now
        row.error_code = None
        row.error_message = None
        action = "youtube_sync.completed"
    else:
        row.status = "failed"
        row.last_failed_at = now
        row.error_code = payload.error_code or "SYNC_FAILED"
        row.error_message = payload.error_message
        action = "youtube_sync.failed"
    row.lease_owner = None
    row.lease_expires_at = None
    _audit(session, action, "sync_watermark", row.id)
    session.commit()
    session.refresh(row)
    return row


def list_sync_watermarks(session: Session, channel_id=None, data_type=None):
    statement = select(SyncWatermark)
    if channel_id:
        statement = statement.where(SyncWatermark.channel_id == channel_id)
    if data_type:
        statement = statement.where(SyncWatermark.data_type == data_type)
    return list(session.scalars(statement.order_by(SyncWatermark.updated_at.desc())))
