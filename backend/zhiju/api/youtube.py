from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.youtube import (
    AnalyticsBreakdownRead,
    AnalyticsBreakdownUpsert,
    ApiRequestRecordCreate,
    ApiRequestRecordRead,
    ChannelDailyMetricRead,
    ChannelDailyMetricUpsert,
    CommentRead,
    CommentAnalysisUpdate,
    CommentReplyCreate,
    CommentReplyRead,
    CommentReplyReview,
    CommentReplyStatusUpdate,
    CommentUpsert,
    PlaylistMembershipRead,
    PlaylistMembershipUpsert,
    PlaylistOrderChange,
    PlaylistOrderHistoryRead,
    QuotaUsageRead,
    QuotaUsageSummary,
    SyncComplete,
    SyncStart,
    SyncWatermarkRead,
    VideoDailyMetricRead,
    VideoDailyMetricUpsert,
    VideoDramaBindingUpdate,
    VideoRead,
    VideoUpsert,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError
from zhiju.services.youtube import (
    complete_sync,
    bind_video_to_drama,
    create_comment_reply,
    list_breakdowns,
    list_api_requests,
    list_channel_metrics,
    list_comment_replies,
    list_comments,
    list_playlist_memberships,
    list_playlist_order_history,
    list_quota_usage,
    list_sync_watermarks,
    list_video_metrics,
    list_videos,
    review_comment_reply,
    record_api_request,
    start_sync,
    summarize_quota_usage,
    change_playlist_membership_order,
    upsert_breakdown,
    upsert_channel_metric,
    upsert_comment,
    upsert_playlist_membership,
    upsert_video,
    upsert_video_metric,
    update_comment_analysis,
    update_comment_reply_status,
)


router = APIRouter(prefix="/v3/youtube", tags=["youtube-data"])


def _raise(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, NotFoundError) else 409, detail=str(exc))


@router.get("/api-requests", response_model=list[ApiRequestRecordRead])
def get_api_requests(
    channel_id: str | None = None,
    authorization_id: str | None = None,
    data_type: str | None = None,
    request_result: str | None = Query(default=None, alias="result"),
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_db),
) -> list[ApiRequestRecordRead]:
    return list_api_requests(
        session,
        channel_id=channel_id,
        authorization_id=authorization_id,
        data_type=data_type,
        result=request_result,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/api-requests", response_model=ApiRequestRecordRead)
def post_api_request(
    payload: ApiRequestRecordCreate,
    session: Session = Depends(get_db),
) -> ApiRequestRecordRead:
    try:
        return record_api_request(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/quota-usage", response_model=list[QuotaUsageRead])
def get_quota_usage(
    channel_id: str | None = None,
    account_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_db),
) -> list[QuotaUsageRead]:
    return list_quota_usage(
        session,
        channel_id=channel_id,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/quota-usage/summary", response_model=list[QuotaUsageSummary])
def get_quota_usage_summary(
    channel_id: str | None = None,
    account_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_db),
) -> list[QuotaUsageSummary]:
    return summarize_quota_usage(
        session,
        channel_id=channel_id,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/videos", response_model=list[VideoRead])
def get_videos(
    channel_id: str | None = None,
    publish_status: str | None = Query(default=None, alias="status"),
    privacy_status: str | None = None,
    session: Session = Depends(get_db),
) -> list[VideoRead]:
    return list_videos(session, channel_id=channel_id, publish_status=publish_status, privacy_status=privacy_status)


@router.post("/videos", response_model=VideoRead)
def post_video(payload: VideoUpsert, session: Session = Depends(get_db)) -> VideoRead:
    try:
        return upsert_video(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch("/videos/{video_id}/drama-binding", response_model=VideoRead)
def patch_video_drama_binding(
    video_id: str,
    payload: VideoDramaBindingUpdate,
    session: Session = Depends(get_db),
) -> VideoRead:
    try:
        return bind_video_to_drama(session, video_id, payload.drama_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/playlist-memberships", response_model=list[PlaylistMembershipRead])
def get_playlist_memberships(
    playlist_id: str | None = None,
    video_id: str | None = None,
    membership_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> list[PlaylistMembershipRead]:
    return list_playlist_memberships(
        session,
        playlist_id=playlist_id,
        video_id=video_id,
        status=membership_status,
    )


@router.put("/playlist-memberships", response_model=PlaylistMembershipRead)
def put_playlist_membership(
    payload: PlaylistMembershipUpsert,
    session: Session = Depends(get_db),
) -> PlaylistMembershipRead:
    try:
        return upsert_playlist_membership(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch(
    "/playlist-memberships/{membership_id}/order",
    response_model=PlaylistMembershipRead,
)
def patch_playlist_membership_order(
    membership_id: str,
    payload: PlaylistOrderChange,
    session: Session = Depends(get_db),
) -> PlaylistMembershipRead:
    try:
        return change_playlist_membership_order(session, membership_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/playlists/{playlist_id}/order-history",
    response_model=list[PlaylistOrderHistoryRead],
)
def get_playlist_order_history(
    playlist_id: str, session: Session = Depends(get_db)
) -> list[PlaylistOrderHistoryRead]:
    try:
        return list_playlist_order_history(session, playlist_id)
    except NotFoundError as exc:
        raise _raise(exc) from exc


@router.get("/comments", response_model=list[CommentRead])
def get_comments(
    channel_id: str | None = None,
    video_id: str | None = None,
    reply_status: str | None = None,
    include_channel_owner: bool = False,
    session: Session = Depends(get_db),
) -> list[CommentRead]:
    return list_comments(
        session,
        channel_id=channel_id,
        video_id=video_id,
        reply_status=reply_status,
        include_channel_owner=include_channel_owner,
    )


@router.post("/comments", response_model=CommentRead)
def post_comment(payload: CommentUpsert, session: Session = Depends(get_db)) -> CommentRead:
    try:
        return upsert_comment(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch("/comments/{comment_id}/analysis", response_model=CommentRead)
def patch_comment_analysis(
    comment_id: str,
    payload: CommentAnalysisUpdate,
    session: Session = Depends(get_db),
) -> CommentRead:
    try:
        return update_comment_analysis(session, comment_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/comment-replies", response_model=list[CommentReplyRead])
def get_comment_replies(
    comment_id: str | None = None,
    session: Session = Depends(get_db),
) -> list[CommentReplyRead]:
    return list_comment_replies(session, comment_id)


@router.post("/comment-replies", response_model=CommentReplyRead)
def post_comment_reply(payload: CommentReplyCreate, session: Session = Depends(get_db)) -> CommentReplyRead:
    try:
        return create_comment_reply(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch("/comment-replies/{reply_id}/review", response_model=CommentReplyRead)
def patch_comment_reply_review(
    reply_id: str,
    payload: CommentReplyReview,
    session: Session = Depends(get_db),
) -> CommentReplyRead:
    try:
        return review_comment_reply(session, reply_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch("/comment-replies/{reply_id}/status", response_model=CommentReplyRead)
def patch_comment_reply_status(
    reply_id: str,
    payload: CommentReplyStatusUpdate,
    session: Session = Depends(get_db),
) -> CommentReplyRead:
    try:
        return update_comment_reply_status(session, reply_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/channel-daily-metrics", response_model=list[ChannelDailyMetricRead])
def get_channel_daily_metrics(
    channel_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_db),
) -> list[ChannelDailyMetricRead]:
    return list_channel_metrics(session, channel_id, date_from, date_to)


@router.post("/channel-daily-metrics", response_model=ChannelDailyMetricRead)
def post_channel_daily_metric(
    payload: ChannelDailyMetricUpsert,
    session: Session = Depends(get_db),
) -> ChannelDailyMetricRead:
    try:
        return upsert_channel_metric(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/video-daily-metrics", response_model=list[VideoDailyMetricRead])
def get_video_daily_metrics(
    video_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_db),
) -> list[VideoDailyMetricRead]:
    return list_video_metrics(session, video_id, date_from, date_to)


@router.post("/video-daily-metrics", response_model=VideoDailyMetricRead)
def post_video_daily_metric(
    payload: VideoDailyMetricUpsert,
    session: Session = Depends(get_db),
) -> VideoDailyMetricRead:
    try:
        return upsert_video_metric(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/analytics-breakdowns", response_model=list[AnalyticsBreakdownRead])
def get_analytics_breakdowns(
    channel_id: str | None = None,
    video_id: str | None = None,
    metric_date: date | None = None,
    dimension_type: str | None = None,
    session: Session = Depends(get_db),
) -> list[AnalyticsBreakdownRead]:
    return list_breakdowns(session, channel_id, video_id, metric_date, dimension_type)


@router.post("/analytics-breakdowns", response_model=AnalyticsBreakdownRead)
def post_analytics_breakdown(
    payload: AnalyticsBreakdownUpsert,
    session: Session = Depends(get_db),
) -> AnalyticsBreakdownRead:
    try:
        return upsert_breakdown(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/sync-watermarks", response_model=list[SyncWatermarkRead])
def get_sync_watermarks(
    channel_id: str | None = None,
    data_type: str | None = None,
    session: Session = Depends(get_db),
) -> list[SyncWatermarkRead]:
    return list_sync_watermarks(session, channel_id, data_type)


@router.post("/sync-watermarks/{channel_id}/{data_type}/start", response_model=SyncWatermarkRead)
def post_sync_start(
    channel_id: str,
    data_type: str,
    payload: SyncStart,
    session: Session = Depends(get_db),
) -> SyncWatermarkRead:
    try:
        return start_sync(session, channel_id, data_type, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post("/sync-watermarks/{channel_id}/{data_type}/complete", response_model=SyncWatermarkRead)
def post_sync_complete(
    channel_id: str,
    data_type: str,
    payload: SyncComplete,
    session: Session = Depends(get_db),
) -> SyncWatermarkRead:
    try:
        return complete_sync(session, channel_id, data_type, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc
