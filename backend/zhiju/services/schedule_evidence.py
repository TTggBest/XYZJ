"""Channel-scoped, read-only performance feedback frozen for each new R4 plan."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import select
from zhiju.models import ChannelSchedulePlan, Drama, YoutubeVideo
from zhiju.services.channel_analysis_sources import verify_authorization
from zhiju.services.youtube_channel_sync import _youtube_request_json
from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired
from zhiju.services.identity import ConflictError


def collect(session, snapshot, *, now=None, fetcher=None, authorize=None):
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or _youtube_request_json
    authorize = authorize or verify_authorization
    channel = snapshot['channel']
    end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=1)
    windows = {
        'recent_7d': (end - timedelta(days=6), end),
        'previous_7d': (end - timedelta(days=13), end - timedelta(days=7)),
        'recent_28d': (end - timedelta(days=27), end),
    }
    analytics = {name: {'status': 'unavailable', 'rows': [], 'window': {
        'start': str(start), 'end': str(stop), 'timezone': 'America/Los_Angeles'}}
        for name, (start, stop) in windows.items()}
    missing = ['实时展示量与CTR需Studio导出，Analytics本次不提供；缺失不等于0',
               '封面实图、前30秒/前6分钟留存和正片未读取，不能认定包装已兑现',
               'Analytics完整日仍可能延迟回补；缺行不是0，发布不足7天不能按成熟样本比较']
    try:
        token, _, _ = authorize(session, channel, fetcher)
    except (ValueError, RuntimeError, ConflictError, YouTubeAuthorizationRequired):
        token = None
        missing.append('当前频道授权或API读取失败，实时表现不可用；仅能提出待验证的承接假设')
    if token:
        for name, dataset in analytics.items():
            params = {'ids': 'channel==MINE', 'startDate': dataset['window']['start'],
                'endDate': dataset['window']['end'], 'dimensions': 'video',
                'metrics': 'views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained',
                'sort': '-views', 'maxResults': 200}
            try:
                rows = []; offset = 1
                while True:
                    page = fetcher('https://youtubeanalytics.googleapis.com/v2/reports?' +
                                   urlencode({**params, 'startIndex': offset}), token)
                    columns = [header['name'] for header in page.get('columnHeaders', [])]
                    values = page.get('rows', [])
                    rows.extend(dict(zip(columns, row)) for row in values)
                    if len(values) < 200:
                        break
                    offset += 200
                dataset.update(status='available', rows=rows)
            except (ValueError, RuntimeError, YouTubeAuthorizationRequired):
                # Do not treat partial pages or errors as a zero-view result.
                dataset['reason'] = '当前窗口API未完整取得，未用其他窗口或0值代替'

    videos = []
    for video, drama in session.execute(select(YoutubeVideo, Drama).outerjoin(
        Drama, Drama.id == YoutubeVideo.drama_id).where(
            YoutubeVideo.channel_id == channel['id'], YoutubeVideo.deleted_at.is_(None))):
        videos.append({'youtube_video_id': video.youtube_video_id, 'drama_id': video.drama_id,
            'title': video.title, 'published_at': video.published_at.isoformat() if video.published_at else None,
            'duration_seconds': video.duration_seconds, 'privacy_status': video.privacy_status,
            'publish_status': video.publish_status,
            'metadata_synced_at': video.last_synced_at.isoformat() if video.last_synced_at else None,
            'plot': (drama.content_summary or drama.plot_archive) if drama else None})
    previous_id = session.scalar(select(ChannelSchedulePlan.id).where(
        ChannelSchedulePlan.channel_id == channel['id'], ChannelSchedulePlan.status == 'applied')
        .order_by(ChannelSchedulePlan.created_at.desc(), ChannelSchedulePlan.id.desc()).limit(1))
    previous = session.get(ChannelSchedulePlan, previous_id) if previous_id else None
    normalized = snapshot.get('guidance', {}).get('normalized_snapshot') or {}
    return {'collected_at': now.isoformat(), 'channel_id': channel['id'], 'analytics': analytics,
        'videos': videos, 'missing': missing, 'previous_plan_id': previous_id,
        'previous_review': deepcopy((previous.result or {}).get('planning_review')) if previous else None,
        'applied_studio': {'windows': deepcopy(normalized.get('studio_windows') or {
                row['source']: row.get('window') for row in normalized.get('source_manifest', [])
                if row['source'].startswith('studio/')}),
            'analysis_generated_at': normalized.get('generated_at'),
            'content': deepcopy(normalized.get('studio_content', [])),
            'retention_observations': deepcopy(normalized.get('retention_intro_30s_pct', 'unavailable')),
            'traffic': deepcopy(normalized.get('traffic_28d_video_pct', 'unavailable')),
            'note': '已应用分析的历史导出与结构化观察，不是本次实时CTR或媒体复核；按其实际窗口判断新旧，不混加窗口'}}
