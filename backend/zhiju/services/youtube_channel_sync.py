import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import (
    AccountChannelAuthorization,
    Channel,
    ChannelPlaylist,
    OAuthGrant,
    OperationPackage,
    OperationTask,
    WorkOrder,
    YoutubeVideo,
)
from zhiju.schemas.youtube import SyncComplete, SyncStart, VideoUpsert
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError, _audit
from zhiju.services.youtube import complete_sync, start_sync, upsert_video
from zhiju.services.youtube_oauth import (
    OAUTH_TOKEN_KEYCHAIN_SERVICE,
    load_oauth_client_config,
    load_oauth_token,
    refresh_oauth_access_token,
    save_oauth_token,
)


YOUTUBE_API_ROOT = "https://www.googleapis.com/youtube/v3"
_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def parse_youtube_duration(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("YouTube视频时长格式无效")
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def ensure_grant_access_token(
    session: Session,
    store: object,
    grant: object,
    *,
    now: datetime | None = None,
    refresher: Callable[[str], Mapping[str, object]] | None = None,
) -> str:
    current_time = now or datetime.now(timezone.utc)
    token = load_oauth_token(store, grant.id)
    if token is None:
        raise ValueError("YouTube授权令牌不存在，请重新授权频道")
    access_token = str(token.get("access_token") or "").strip()
    expires_at = _as_utc(grant.token_expires_at)
    if access_token and (expires_at is None or expires_at > current_time + timedelta(seconds=60)):
        return access_token

    refresh_token = str(token.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError("YouTube授权缺少刷新令牌，请重新授权频道")
    if refresher is None:
        config = load_oauth_client_config(store)
        refresher = lambda value: refresh_oauth_access_token(config, value)
    refreshed = dict(refresher(refresh_token))
    new_access_token = str(refreshed.get("access_token") or "").strip()
    if not new_access_token:
        raise ValueError("Google刷新授权后未返回访问令牌")
    refreshed["refresh_token"] = refresh_token
    save_oauth_token(store, grant.id, refreshed)
    expires_in = int(refreshed.get("expires_in") or 0)
    grant.token_expires_at = current_time + timedelta(seconds=expires_in) if expires_in else None
    grant.last_refreshed_at = current_time
    session.commit()
    return new_access_token


def _youtube_request_json(url: str, access_token: str) -> Mapping[str, object]:
    request = Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"YouTube API请求失败：HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("无法连接YouTube API") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("YouTube API返回了无效数据") from exc
    if not isinstance(payload, dict):
        raise ValueError("YouTube API返回了无效数据")
    return payload


def _youtube_post_json(
    url: str,
    access_token: str,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"YouTube API请求失败：HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("无法连接YouTube API") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("YouTube API返回了无效数据") from exc
    if not isinstance(result, dict):
        raise ValueError("YouTube API返回了无效数据")
    return result


def _api_url(path: str, **params: object) -> str:
    return f"{YOUTUBE_API_ROOT}/{path}?{urlencode(params)}"


def create_remote_youtube_playlist(
    access_token: str,
    title: str,
    description: str,
) -> Mapping[str, object]:
    return _youtube_post_json(
        _api_url("playlists", part="snippet,status"),
        access_token,
        {
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": "public"},
        },
    )


def create_authorized_channel_playlist(
    session: Session,
    store: object,
    *,
    channel_id: str,
    playlist_id: str,
    creator: Callable[[str, str, str], Mapping[str, object]] = create_remote_youtube_playlist,
    now: datetime | None = None,
) -> ChannelPlaylist:
    current_time = now or datetime.now(timezone.utc)
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise NotFoundError("频道不存在")
    playlist = session.scalar(
        select(ChannelPlaylist)
        .where(
            ChannelPlaylist.id == playlist_id,
            ChannelPlaylist.channel_id == channel_id,
            ChannelPlaylist.status != "deleted",
        )
        .with_for_update()
    )
    if playlist is None:
        raise NotFoundError("播放列表不存在")
    if playlist.youtube_playlist_id:
        raise ConflictError("播放列表已绑定YouTube播放列表")
    authorization = session.scalar(
        select(AccountChannelAuthorization)
        .where(
            AccountChannelAuthorization.channel_id == channel_id,
            AccountChannelAuthorization.status == "active",
            AccountChannelAuthorization.verified_youtube_channel_id == channel.youtube_channel_id,
        )
        .order_by(AccountChannelAuthorization.verified_at.desc())
        .limit(1)
    )
    if authorization is None:
        raise ConflictError("频道没有匹配且有效的YouTube授权绑定")
    grant = session.get(OAuthGrant, authorization.oauth_grant_id)
    if grant is None or grant.status != "active":
        raise ConflictError("频道授权使用的OAuth Grant不可用")
    access_token = ensure_grant_access_token(session, store, grant, now=current_time)
    resource = creator(
        access_token,
        playlist.local_name,
        playlist.local_description or "",
    )
    youtube_playlist_id = str(resource.get("id") or "").strip()
    if not youtube_playlist_id:
        raise ValueError("YouTube API未返回播放列表ID")
    playlist.youtube_playlist_id = youtube_playlist_id
    playlist.url = f"https://www.youtube.com/playlist?list={youtube_playlist_id}"
    playlist.status = "active"
    try:
        session.flush()
        _audit(session, "playlist.youtube_created", "channel_playlist", playlist.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("YouTube播放列表ID与现有记录冲突") from exc
    session.refresh(playlist)
    return playlist


def fetch_channel_upload_videos(
    access_token: str,
    youtube_channel_id: str,
    *,
    requester: Callable[[str, str], Mapping[str, object]] | None = None,
) -> list[Mapping[str, object]]:
    request_json = requester or _youtube_request_json
    channel_payload = request_json(
        _api_url("channels", part="contentDetails", id=youtube_channel_id),
        access_token,
    )
    channel_items = channel_payload.get("items")
    channel_item = channel_items[0] if isinstance(channel_items, list) and channel_items else None
    content_details = channel_item.get("contentDetails") if isinstance(channel_item, dict) else None
    related_playlists = content_details.get("relatedPlaylists") if isinstance(content_details, dict) else None
    uploads_id = str(related_playlists.get("uploads") or "").strip() if isinstance(related_playlists, dict) else ""
    if not uploads_id:
        raise ValueError("YouTube频道未返回上传视频播放列表")

    video_ids: list[str] = []
    page_token = ""
    while True:
        params: dict[str, object] = {
            "part": "contentDetails",
            "playlistId": uploads_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        page = request_json(_api_url("playlistItems", **params), access_token)
        items = page.get("items")
        if not isinstance(items, list):
            items = []
        for item in items:
            details = item.get("contentDetails") if isinstance(item, dict) else None
            video_id = str(details.get("videoId") or "").strip() if isinstance(details, dict) else ""
            if video_id and video_id not in video_ids:
                video_ids.append(video_id)
        page_token = str(page.get("nextPageToken") or "").strip()
        if not page_token:
            break

    resources: dict[str, Mapping[str, object]] = {}
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset : offset + 50]
        payload = request_json(
            _api_url(
                "videos",
                part="snippet,contentDetails,status",
                id=",".join(batch),
                maxResults=50,
            ),
            access_token,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
        for item in items:
            if isinstance(item, dict):
                video_id = str(item.get("id") or "").strip()
                if video_id:
                    resources[video_id] = item
    return [resources[video_id] for video_id in video_ids if video_id in resources]


def _parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("YouTube视频时间格式无效") from exc


def _linkage_for_video(session: Session, channel_id: str, video_id: str) -> dict[str, str | None]:
    task = session.scalar(
        select(OperationTask)
        .where(
            OperationTask.channel_id == channel_id,
            OperationTask.source_video_id == video_id,
        )
        .order_by(OperationTask.created_at.desc())
        .limit(1)
    )
    if task is None:
        return {"operation_package_id": None, "drama_id": None, "schedule_id": None}
    package = session.scalar(
        select(OperationPackage)
        .join(WorkOrder, WorkOrder.id == OperationPackage.work_order_id)
        .where(
            WorkOrder.task_id == task.id,
            OperationPackage.status.in_(("approved", "delivered")),
        )
        .order_by(OperationPackage.version_number.desc())
        .limit(1)
    )
    return {
        "operation_package_id": package.id if package else None,
        "drama_id": task.drama_id,
        "schedule_id": task.schedule_id,
    }


def _video_payload(
    channel_id: str,
    resource: Mapping[str, object],
    linkage: Mapping[str, str | None],
    now: datetime,
) -> VideoUpsert:
    video_id = str(resource.get("id") or "").strip()
    snippet = resource.get("snippet") if isinstance(resource.get("snippet"), dict) else {}
    status = resource.get("status") if isinstance(resource.get("status"), dict) else {}
    details = resource.get("contentDetails") if isinstance(resource.get("contentDetails"), dict) else {}
    title = str(snippet.get("title") or "").strip()
    if not video_id or not title:
        raise ValueError("YouTube视频缺少ID或标题")
    privacy = str(status.get("privacyStatus") or "private").strip()
    if privacy not in {"public", "private", "unlisted"}:
        raise ValueError("YouTube视频隐私状态无效")
    published_at = _parse_timestamp(snippet.get("publishedAt"))
    scheduled_at = _parse_timestamp(status.get("publishAt"))
    upload_status = str(status.get("uploadStatus") or "processed").strip()
    if upload_status in {"failed", "rejected"}:
        publish_status = "error"
    elif scheduled_at is not None and scheduled_at > now:
        publish_status = "scheduled"
    elif privacy in {"public", "unlisted"} and published_at is not None:
        publish_status = "published"
    else:
        publish_status = "draft"
    duration = str(details.get("duration") or "").strip()
    return VideoUpsert(
        youtube_video_id=video_id,
        channel_id=channel_id,
        operation_package_id=linkage.get("operation_package_id"),
        drama_id=linkage.get("drama_id"),
        schedule_id=linkage.get("schedule_id"),
        title=title,
        description=str(snippet.get("description") or "") or None,
        url=f"https://www.youtube.com/watch?v={video_id}",
        privacy_status=privacy,
        publish_status=publish_status,
        scheduled_publish_at=scheduled_at if publish_status == "scheduled" else None,
        published_at=published_at if publish_status == "published" else None,
        duration_seconds=parse_youtube_duration(duration) if duration else None,
        source="youtube_sync",
        etag=str(resource.get("etag") or "") or None,
        last_synced_at=now,
    )


def sync_authorized_channel_videos(
    session: Session,
    store: object,
    *,
    channel_id: str,
    fetcher: Callable[[str, str], list[Mapping[str, object]]] = fetch_channel_upload_videos,
    now: datetime | None = None,
) -> dict[str, int]:
    current_time = now or datetime.now(timezone.utc)
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise NotFoundError("频道不存在")
    authorization = session.scalar(
        select(AccountChannelAuthorization)
        .where(
            AccountChannelAuthorization.channel_id == channel_id,
            AccountChannelAuthorization.status == "active",
            AccountChannelAuthorization.verified_youtube_channel_id == channel.youtube_channel_id,
        )
        .order_by(AccountChannelAuthorization.verified_at.desc())
        .limit(1)
    )
    if authorization is None:
        raise ConflictError("频道没有匹配且有效的YouTube授权绑定")
    grant = session.get(OAuthGrant, authorization.oauth_grant_id)
    if grant is None or grant.status != "active":
        raise ConflictError("频道授权使用的OAuth Grant不可用")
    access_token = ensure_grant_access_token(session, store, grant, now=current_time)
    worker_key = f"channel-video-sync:{channel_id}"
    start_sync(
        session,
        channel_id,
        "videos",
        SyncStart(authorization_id=authorization.id, worker_key=worker_key),
    )
    try:
        resources = fetcher(access_token, channel.youtube_channel_id)
        inserted = 0
        updated = 0
        bound = 0
        for resource in resources:
            video_id = str(resource.get("id") or "").strip()
            existing = session.scalar(
                select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == video_id)
            )
            linkage = _linkage_for_video(session, channel.id, video_id)
            video = upsert_video(
                session,
                _video_payload(channel.id, resource, linkage, current_time),
            )
            if existing is None:
                inserted += 1
            else:
                updated += 1
            if video.drama_id is not None:
                bound += 1
        complete_sync(
            session,
            channel_id,
            "videos",
            SyncComplete(
                worker_key=worker_key,
                success=True,
                data_through_at=current_time,
            ),
        )
        return {
            "fetched": len(resources),
            "inserted": inserted,
            "updated": updated,
            "bound": bound,
            "unmatched": len(resources) - bound,
        }
    except Exception as exc:
        try:
            complete_sync(
                session,
                channel_id,
                "videos",
                SyncComplete(
                    worker_key=worker_key,
                    success=False,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                ),
            )
        except Exception:
            session.rollback()
        raise
