"""Refresh a channel's current views and remove only evidenced low-view releases."""
import json
import logging
from datetime import datetime, timezone
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.request import Request

from sqlalchemy import delete, or_, select, update

from zhiju.models import (
    AccountChannelAuthorization, AuditEvent, Channel, ChannelScheduleEntry, MediaAsset,
    OAuthGrant, OperationPackage, OperationTask, WorkOrder, YoutubeVideo,
)
from zhiju.models.settings import ImageProcessingItem
from zhiju.models.v14 import V14Attempt, V14Run
from zhiju.services.channel import NotFoundError
from zhiju.services.google_http import open_google_url
from zhiju.services.identity import ConflictError, _audit
from zhiju.services.youtube_channel_sync import (
    _api_url, _as_utc, _youtube_request_json, ensure_grant_access_token,
    fetch_channel_upload_videos, parse_youtube_duration,
)
from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired


MIN_AGE_DAYS = 5
MIN_PEERS = 5
MAX_PEERS = 20
THRESHOLD_RATIO = 0.2
logger = logging.getLogger(__name__)


def _snapshot(session, store, channel_id, requester, now):
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        raise NotFoundError('频道不存在')
    authorization = session.scalar(select(AccountChannelAuthorization).where(
        AccountChannelAuthorization.channel_id == channel_id,
        AccountChannelAuthorization.status == 'active',
        AccountChannelAuthorization.verified_youtube_channel_id == channel.youtube_channel_id,
    ).order_by(AccountChannelAuthorization.verified_at.desc()).limit(1))
    grant = session.get(OAuthGrant, authorization.oauth_grant_id) if authorization else None
    if grant is None or grant.status != 'active':
        raise YouTubeAuthorizationRequired('频道没有有效的 YouTube 授权，请重新授权频道')
    token = ensure_grant_access_token(session, store, grant, now=now)
    resources = fetch_channel_upload_videos(token, channel.youtube_channel_id,
                                           requester=requester, include_statistics=True)
    known = {row.youtube_video_id: row for row in session.scalars(select(YoutubeVideo).where(
        YoutubeVideo.channel_id == channel_id))}
    _confirm_interrupted_deletions(session, channel, known, resources, token, requester, now)
    eligible, skipped = [], []
    for resource in resources:
        external_id = resource['id']
        snippet, status = resource.get('snippet', {}), resource.get('status', {})
        if snippet.get('channelId') != channel.youtube_channel_id:
            raise ConflictError('YouTube 返回了其他频道的视频，本次未删除任何视频')
        video = known.get(external_id)
        reason = None
        if status.get('privacyStatus') != 'public':
            reason = '尚未公开'
        elif video is None or not video.drama_id:
            reason = '未关联剧库'
        elif video.deleted_at is not None:
            reason = '视频已删除，等待本地清理'
        try:
            published = _as_utc(datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00')))
            age = (now - published).total_seconds() / 86400
        except (KeyError, TypeError, ValueError):
            published, age = None, None
        try:
            raw_views = resource.get('statistics', {}).get('viewCount')
            views = int(raw_views) if raw_views is not None else None
            if views is not None and views < 0:
                views = None
        except (ValueError, TypeError):
            views = None
        if not reason:
            if age is None:
                reason = '缺少实际公开时间'
            elif age < MIN_AGE_DAYS:
                reason = '上线不足 5 天'
            elif views is None:
                reason = '未获取到播放量'
            else:
                try:
                    if parse_youtube_duration(resource.get('contentDetails', {}).get('duration', '')) < 1800:
                        reason = '非长剧视频'
                except ValueError:
                    reason = '缺少视频时长'
        if reason:
            skipped.append({'youtube_video_id': external_id, 'reason': reason})
            continue
        eligible.append({'video_id': video.id, 'youtube_video_id': external_id, 'drama_id': video.drama_id,
                         'title': snippet.get('title') or video.title, 'views': views,
                         'published_at': published.isoformat(), 'age_days': age})
    candidates = []
    for row in eligible:
        peers = sorted((other for other in eligible
                        if other['video_id'] != row['video_id']
                        and abs(other['age_days'] - row['age_days']) <= max(2, row['age_days'] * 0.25)),
                       key=lambda other: (abs(other['age_days'] - row['age_days']), other['youtube_video_id']))[:MAX_PEERS]
        if len(peers) < MIN_PEERS:
            skipped.append({'youtube_video_id': row['youtube_video_id'], 'reason': '相近上线天数的有效样本不足 5 个'})
            continue
        baseline = median(other['views'] for other in peers)
        threshold = baseline * THRESHOLD_RATIO
        if row['views'] < threshold:
            candidates.append({**row, 'baseline_views': baseline, 'threshold_views': threshold,
                               'sample_count': len(peers)})
    removed_ids = set(session.scalars(select(AuditEvent.entity_id).where(
        AuditEvent.action == 'youtube.low_view_removed', AuditEvent.entity_type == 'youtube_video')))
    report = {'channel_id': channel_id, 'channel_name': channel.original_name, 'fetched_at': now.isoformat(),
              'fetched_count': len(resources), 'min_age_days': MIN_AGE_DAYS, 'threshold_ratio': THRESHOLD_RATIO,
              'candidates': candidates, 'skipped': skipped,
              'pending_cleanup': [{'video_id': row.id, 'youtube_video_id': row.youtube_video_id, 'title': row.title}
                                  for row in known.values() if row.publish_status == 'deleted'
                                  and row.deleted_at is not None and row.id in removed_ids]}
    return token, report


def preview_cleanup(session, store, *, channel_id, requester=None, now=None):
    """Every preview uses fresh Data API values, without deleting anything."""
    _, report = _snapshot(session, store, channel_id, requester, _as_utc(now or datetime.now(timezone.utc)))
    return report


def _confirm_interrupted_deletions(session, channel, known, resources, token, requester, now):
    attempts = session.scalars(select(AuditEvent).where(
        AuditEvent.action == 'youtube.low_view_delete_started',
        AuditEvent.entity_id.in_([row.id for row in known.values() if row.deleted_at is None]),
    ).order_by(AuditEvent.occurred_at))
    attempted = {event.entity_id: json.loads(event.change_summary) for event in attempts}
    returned = {row['id'] for row in resources}
    missing = [row for row in known.values() if row.id in attempted and row.youtube_video_id not in returned]
    if not missing:
        return
    request_json = requester or _youtube_request_json
    for offset in range(0, len(missing), 50):
        chunk = missing[offset:offset + 50]
        response = request_json(_api_url('videos', part='snippet,contentDetails,status,statistics',
                                         id=','.join(row.youtube_video_id for row in chunk)), token)
        items = response.get('items')
        if not isinstance(items, list):
            raise ValueError('无法确认上次视频删除结果，本次未清理关联数据')
        if any(row.get('snippet', {}).get('channelId') != channel.youtube_channel_id for row in items):
            raise ConflictError('视频状态复查返回了其他频道的数据，未清理关联数据')
        resources.extend(items)
        readable = {row['id'] for row in items}
        for video in chunk:
            if video.youtube_video_id not in readable:
                video.publish_status, video.deleted_at = 'deleted', now
                _audit(session, 'youtube.low_view_removed', 'youtube_video', video.id,
                       json.dumps({**attempted[video.id], 'confirmation': 'API按视频ID复查确认不存在'}, ensure_ascii=False))
    session.commit()


def delete_youtube_video(token, external_id):
    request = Request(_api_url('videos', id=external_id), method='DELETE',
                      headers={'Authorization': f'Bearer {token}'})
    try:
        with open_google_url(request, timeout=30) as response:
            if response.status != 204:
                raise ValueError('YouTube 未确认视频删除成功')
    except HTTPError as exc:
        if exc.code == 401:
            raise YouTubeAuthorizationRequired('YouTube 授权失效，请重新授权频道') from None
        raise ValueError(f'YouTube 视频删除失败：HTTP {exc.code}') from None
    except (URLError, TimeoutError) as exc:
        raise ValueError('无法确认 YouTube 视频删除结果，请重新获取频道数据') from exc


def _release_links(session, video):
    """Resolve this specific release, never all releases of the same drama."""
    def owned(row):
        if row is None or row.channel_id != video.channel_id or row.drama_id != video.drama_id:
            raise ConflictError('视频的排期或运营包关联不一致，请先核对关联')
        return row

    root_package = owned(session.get(OperationPackage, video.operation_package_id)) if video.operation_package_id else None
    root_order = owned(session.get(WorkOrder, root_package.work_order_id)) if root_package else None
    source_tasks = list(session.scalars(select(OperationTask).where(OperationTask.channel_id == video.channel_id,
        or_(OperationTask.source_video_id == video.youtube_video_id,
            OperationTask.id == (root_order.task_id if root_order else None)))))
    for task in source_tasks:
        owned(task)
    schedule_ids = {value for value in (
        video.schedule_id, root_package.schedule_id if root_package else None,
        root_order.schedule_id if root_order else None, *(row.schedule_id for row in source_tasks)) if value}
    schedules = list(session.scalars(select(ChannelScheduleEntry).where(
        ChannelScheduleEntry.channel_id == video.channel_id,
        or_(ChannelScheduleEntry.id.in_(schedule_ids), ChannelScheduleEntry.source_video_id == video.youtube_video_id))))
    if schedule_ids - {row.id for row in schedules}:
        raise ConflictError('视频关联的原排期不存在于当前频道')
    schedule_ids = {row.id for row in schedules}
    tasks = list(session.scalars(select(OperationTask).where(OperationTask.channel_id == video.channel_id,
        or_(OperationTask.schedule_id.in_(schedule_ids), OperationTask.id.in_([row.id for row in source_tasks])))))
    task_ids = {row.id for row in tasks}
    orders = list(session.scalars(select(WorkOrder).where(WorkOrder.channel_id == video.channel_id,
        or_(WorkOrder.schedule_id.in_(schedule_ids), WorkOrder.task_id.in_(task_ids),
            WorkOrder.id == (root_package.work_order_id if root_package else None)))))
    for order in orders:
        if order.task_id not in task_ids:
            tasks.append(owned(session.get(OperationTask, order.task_id)))
            task_ids.add(order.task_id)
    order_ids = {row.id for row in orders}
    packages = list(session.scalars(select(OperationPackage).where(OperationPackage.channel_id == video.channel_id,
        or_(OperationPackage.work_order_id.in_(order_ids), OperationPackage.schedule_id.in_(schedule_ids),
            OperationPackage.id == video.operation_package_id))))
    for row in [*schedules, *tasks, *orders, *packages]:
        owned(row)
        if getattr(row, 'source_video_id', None) not in (None, '', video.youtube_video_id):
            raise ConflictError('原排期或任务已经绑定其他视频，请先核对关联')
    package_ids = {row.id for row in packages}
    runs = list(session.scalars(select(V14Run).where(
        or_(V14Run.package_id.in_(package_ids), V14Run.work_order_id.in_(order_ids)))))
    if any(row.status in ('queued', 'running') for row in runs) or any(row.status == 'running' for row in orders):
        raise ConflictError('关联工单仍在生产，请先停止该工单后清理')
    if session.scalar(select(YoutubeVideo.id).where(YoutubeVideo.id != video.id,
            or_(YoutubeVideo.operation_package_id.in_(package_ids), YoutubeVideo.schedule_id.in_(schedule_ids))).limit(1)):
        raise ConflictError('关联排期或运营包还绑定了其他视频，请先核对关联')
    return schedules, tasks, orders, packages, runs


def _clean_release(session, video, links):
    schedules, tasks, orders, packages, runs = links
    schedule_ids, package_ids, run_ids = [row.id for row in schedules], [row.id for row in packages], [row.id for row in runs]
    # These references restrict parent deletion. Other package/video children use
    # the existing database CASCADE rules, including metrics, comments and posts.
    session.execute(delete(V14Attempt).where(V14Attempt.run_id.in_(run_ids)))
    session.execute(delete(V14Run).where(V14Run.id.in_(run_ids)))
    session.execute(delete(ImageProcessingItem).where(or_(ImageProcessingItem.package_id.in_(package_ids),
                                                         ImageProcessingItem.schedule_id.in_(schedule_ids))))
    session.execute(update(MediaAsset).where(MediaAsset.operation_package_id.in_(package_ids)).values(
        operation_package_id=None))
    session.execute(update(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id == video.channel_id,
        ChannelScheduleEntry.replaced_by_schedule_id.in_(schedule_ids)).values(replaced_by_schedule_id=None))
    session.delete(video)
    session.flush()
    for rows in (packages, orders, tasks, schedules):
        for row in rows:
            session.delete(row)
        session.flush()
    return {'schedules': len(schedules), 'tasks': len(tasks), 'work_orders': len(orders), 'packages': len(packages)}


def execute_cleanup(session, store, *, channel_id, video_ids, requester=None, deleter=None, now=None):
    """Re-read current views before deleting the user's selected preview rows."""
    now = _as_utc(now or datetime.now(timezone.utc))
    token, report = _snapshot(session, store, channel_id, requester, now)
    candidates = {row['video_id']: row for row in report['candidates']}
    pending = {row['video_id'] for row in report['pending_cleanup']}
    result = {'channel_id': channel_id, 'fetched_at': report['fetched_at'], 'deleted_count': 0,
              'cleaned_count': 0, 'completed': [], 'failed': [], 'skipped': []}
    for video_id in dict.fromkeys(video_ids):
        if video_id not in candidates and video_id not in pending:
            result['skipped'].append({'video_id': video_id, 'reason': '当前数据已不符合清理条件，请重新查看清单'})
            continue
        video = session.scalar(select(YoutubeVideo).where(YoutubeVideo.id == video_id,
            YoutubeVideo.channel_id == channel_id).with_for_update().execution_options(populate_existing=True))
        if video is None:
            result['skipped'].append({'video_id': video_id, 'reason': '视频记录已清理'})
            continue
        external_id = video.youtube_video_id
        details = {'channel_id': channel_id, 'drama_id': video.drama_id, 'youtube_video_id': external_id}
        removed = video_id in pending
        attempted = False
        try:
            links = _release_links(session, video)
            if not removed:
                _audit(session, 'youtube.low_view_delete_started', 'youtube_video', video_id,
                       json.dumps({**details, 'assessment': candidates[video_id]}, ensure_ascii=False))
                session.commit()
                attempted = True
                (deleter or delete_youtube_video)(token, external_id)
                removed = True
                result['deleted_count'] += 1
                video.publish_status, video.deleted_at = 'deleted', now
                _audit(session, 'youtube.low_view_removed', 'youtube_video', video_id,
                       json.dumps({**details, 'assessment': candidates[video_id]}, ensure_ascii=False))
                session.commit()
                links = _release_links(session, video)
            counts = _clean_release(session, video, links)
            _audit(session, 'youtube.low_view_cleaned', 'youtube_video', video_id,
                   json.dumps({**details, 'cleaned': counts}, ensure_ascii=False))
            session.commit()
            result['cleaned_count'] += 1
            result['completed'].append({**details, 'video_id': video_id, 'cleaned': counts})
        except (ConflictError, ValueError, RuntimeError) as exc:
            session.rollback()
            result['failed'].append({'video_id': video_id, 'youtube_video_id': external_id,
                                    'remote_deleted': True if removed else None if attempted else False,
                                    'reason': str(exc)})
        except Exception:
            session.rollback()
            logger.exception('Low-view cleanup failed for channel %s video %s', channel_id, external_id)
            # A successful remote delete has already been committed separately.
            # Keep its marker for the next attempt instead of replaying DELETE.
            result['failed'].append({'video_id': video_id, 'youtube_video_id': external_id,
                                    'remote_deleted': True if removed else None if attempted else False,
                                    'reason': '本地关联清理失败，可重新打开清理功能继续处理' if removed else '处理失败，本地排期保留'})
    return result
