from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool

from zhiju.database import TenantSession
from zhiju.models import Base, Channel, Drama, GoogleAccount, OAuthGrant, AccountChannelAuthorization, YoutubeVideo
from zhiju.services import low_view_cleanup as service


NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


class TokenStore:
    def get(self, service, account):
        return '{"access_token":"fixture-access"}'


@pytest.fixture
def data():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    event.listen(engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
    Base.metadata.create_all(engine)
    with TenantSession(engine, info={'tenant_id': 'test-tenant'}) as s:
        channel = Channel(original_name='测试频道', youtube_channel_id='UC-owned', default_language='en',
                          timezone='Asia/Shanghai', status='active', daily_publish_count=1)
        drama = Drama(drama_number=1, drama_code='D-1', chinese_title='女主夺回公司', normalized_title='女主夺回公司',
                      status='active', content_summary='女主夺回公司。')
        account = GoogleAccount(nickname='测试账号', google_email='test@example.com', status='active', authorization_status='authorized')
        s.add_all([channel, drama, account]); s.flush()
        grant = OAuthGrant(account_id=account.id, provider_subject='test-subject', credential_ref='fixture',
                           status='active', token_expires_at=NOW + timedelta(hours=1))
        s.add(grant); s.flush()
        s.add(AccountChannelAuthorization(account_id=account.id, channel_id=channel.id, oauth_grant_id=grant.id,
                                         status='active', verified_youtube_channel_id=channel.youtube_channel_id, verified_at=NOW))
        resources = []
        for index, views in enumerate([99, 1000, 1000, 1000, 1000, 1000]):
            external_id = f'video{index:06d}'
            s.add(YoutubeVideo(youtube_video_id=external_id, channel_id=channel.id, drama_id=drama.id,
                               title=f'剧目{index}', url=f'https://youtu.be/{external_id}', privacy_status='public',
                               publish_status='published', duration_seconds=3600, source='youtube_sync', published_at=NOW - timedelta(days=5)))
            resources.append(remote(external_id, views))
        s.commit()
        calls = []

        def requester(url, token):
            assert token == 'fixture-access'
            calls.append(url)
            path, query = urlparse(url).path, parse_qs(urlparse(url).query)
            if path.endswith('/channels'):
                return {'items': [{'contentDetails': {'relatedPlaylists': {'uploads': 'UU-owned'}}}]}
            if path.endswith('/playlistItems'):
                return {'items': [{'contentDetails': {'videoId': row['id']}} for row in resources]}
            if path.endswith('/videos'):
                assert 'statistics' in query['part'][0]
                return {'items': [row for row in resources if row['id'] in query['id'][0].split(',')]}
            raise AssertionError(url)

        yield s, channel, drama, resources, calls, requester
    engine.dispose()


def remote(external_id, views, *, days=5, privacy='public', channel_id='UC-owned', duration='PT1H'):
    return {'id': external_id, 'snippet': {'title': external_id, 'channelId': channel_id,
            'publishedAt': (NOW - timedelta(days=days)).isoformat()},
            'status': {'privacyStatus': privacy, 'uploadStatus': 'processed'},
            'contentDetails': {'duration': duration}, 'statistics': {'viewCount': str(views)}}


def preview(data):
    s, channel, _, _, _, requester = data
    return service.preview_cleanup(s, TokenStore(), channel_id=channel.id, requester=requester, now=NOW)


def test_preview_refreshes_api_and_uses_whole_channel_median(data):
    result = preview(data)
    assert len(data[4]) == 3
    assert [(v['youtube_video_id'], v['views'], v['baseline_views'], v['threshold_views'])
            for v in result['candidates']] == [('video000000', 99, 1000, 200)]
    assert result['candidates'][0]['sample_count'] == 6
    assert result['sample_count'] == 6
    assert result['baseline_views'] == 1000
    assert result['threshold_views'] == 200
    assert data[0].scalar(select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == 'video000000')) is not None


@pytest.mark.parametrize('change', ['young', 'missing_views', 'private', 'boundary', 'short'])
def test_preview_keeps_ineligible_or_insufficiently_evidenced_videos(data, change):
    row = data[3][0]
    if change == 'young':
        row['snippet']['publishedAt'] = (NOW - timedelta(days=5) + timedelta(seconds=1)).isoformat()
    elif change == 'missing_views':
        row['statistics'] = {}
    elif change == 'private':
        row['status']['privacyStatus'] = 'private'
    elif change == 'boundary':
        row['statistics']['viewCount'] = '200'
    elif change == 'short':
        row['contentDetails']['duration'] = 'PT30S'
    assert preview(data)['candidates'] == []


@pytest.mark.parametrize('published_days', [1, 60])
def test_channel_baseline_includes_recent_and_old_public_drama(data, published_days):
    for peer in data[3][1:]:
        peer['snippet']['publishedAt'] = (NOW - timedelta(days=published_days)).isoformat()
    result = preview(data)
    assert result['sample_count'] == 6
    assert result['baseline_views'] == 1000
    assert [row['youtube_video_id'] for row in result['candidates']] == ['video000000']


def test_channel_baseline_includes_all_published_drama_without_twenty_video_limit(data):
    # These older public dramas have not yet been linked locally. Their actual
    # channel views still contribute to the baseline, but they cannot be deleted.
    for index in range(25):
        data[3].append(remote(f'older{index:06d}', 9000, days=60))
    result = preview(data)
    assert result['sample_count'] == 31
    assert result['baseline_views'] == 9000
    assert result['threshold_views'] == 1800
    assert {row['baseline_views'] for row in result['candidates']} == {9000}
    assert {row['sample_count'] for row in result['candidates']} == {31}
    assert all(not row['youtube_video_id'].startswith('older') for row in result['candidates'])


def test_private_and_short_videos_do_not_change_published_drama_baseline(data):
    for index in range(10):
        data[3].append(remote(f'privt{index:06d}', 100000, privacy='private'))
        data[3].append(remote(f'short{index:06d}', 100000, duration='PT30S'))
    assert preview(data)['baseline_views'] == 1000


def release(data):
    from datetime import time
    from zhiju.models import ChannelPublishSlot, ChannelScheduleEntry, DramaProductionState, OperationTask, WorkOrder, OperationPackage
    s, channel, drama, *_ = data
    slot = ChannelPublishSlot(channel_id=channel.id, slot_type='main', slot_number=1, local_time=time(18),
                              timezone=channel.timezone, status='active')
    s.add(slot); s.flush()
    schedule = ChannelScheduleEntry(channel_id=channel.id, drama_id=drama.id, publish_slot_id=slot.id,
                                    publish_date=NOW.date(), planned_local_time=NOW, planned_beijing_time=NOW,
                                    planned_utc_time=NOW, idempotency_key='original-schedule', source_video_id='video000000')
    s.add(schedule); s.flush()
    task = OperationTask(channel_id=channel.id, drama_id=drama.id, schedule_id=schedule.id,
                         task_date=NOW.date(), target_publish_date=NOW.date(), source='schedule',
                         status='completed', idempotency_key='original-task', source_video_id='video000000')
    s.add(task); s.flush()
    order = WorkOrder(task_id=task.id, channel_id=channel.id, drama_id=drama.id, schedule_id=schedule.id,
                      production_date=NOW.date(), target_publish_date=NOW.date(), status='completed')
    s.add(order); s.flush()
    package = OperationPackage(work_order_id=order.id, channel_id=channel.id, drama_id=drama.id,
                               schedule_id=schedule.id, status='delivered')
    s.add(package); s.flush()
    video = s.scalar(select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == 'video000000'))
    video.schedule_id, video.operation_package_id = schedule.id, package.id
    s.add(DramaProductionState(drama_id=drama.id, production_completion_status='completed',
                               finished_languages=['en'], total_duration_seconds=3600))
    s.commit()
    return video, schedule, task, order, package


def execute(data, ids, deleter):
    return service.execute_cleanup(data[0], TokenStore(), channel_id=data[1].id, video_ids=ids,
                                   requester=data[5], deleter=deleter, now=NOW)


def test_success_removes_release_and_frees_candidate_but_preserves_other_channel(data):
    from zhiju.models import ChannelScheduleEntry, OperationTask, WorkOrder, OperationPackage
    from zhiju.services.schedule_planning import candidate_pool
    video, schedule, task, order, package = release(data)
    s, channel, drama, *_ = data
    other = Channel(original_name='其他频道', youtube_channel_id='UC-other', default_language='en',
                    timezone='Asia/Shanghai', status='active', daily_publish_count=1)
    s.add(other); s.flush()
    other_video = YoutubeVideo(youtube_video_id='other000001', channel_id=other.id, drama_id=drama.id,
                               title='其他频道同剧', url='https://youtu.be/other000001', privacy_status='public',
                               publish_status='published', source='youtube_sync')
    s.add(other_video); s.commit()
    assert candidate_pool(s, channel)[0] == []
    calls = []
    result = execute(data, [video.id], lambda token, external_id: calls.append(external_id))
    assert result['deleted_count'] == 1 and result['failed'] == []
    assert calls == ['video000000']
    for model, row in [(YoutubeVideo, video), (ChannelScheduleEntry, schedule), (OperationTask, task),
                       (WorkOrder, order), (OperationPackage, package)]:
        assert s.get(model, row.id) is None
    assert s.get(YoutubeVideo, other_video.id) is not None
    assert s.get(Drama, drama.id) is not None
    assert [row['id'] for row in candidate_pool(s, channel)[0]] == [drama.id]


def test_remote_failure_preserves_local_release(data):
    video, schedule, task, order, package = release(data)
    def denied(*args):
        raise ValueError('YouTube API请求失败：HTTP 403')
    result = execute(data, [video.id], denied)
    assert result['deleted_count'] == 0 and len(result['failed']) == 1
    assert data[0].get(YoutubeVideo, video.id).deleted_at is None
    assert data[0].get(type(schedule), schedule.id) is not None
    assert data[0].get(type(package), package.id) is not None


def test_resolves_original_schedule_through_task_when_video_binding_is_partial(data):
    video, schedule, task, *_ = release(data)
    schedule_id = schedule.id
    video.schedule_id = video.operation_package_id = None
    schedule.source_video_id = None
    data[0].commit()
    result = execute(data, [video.id], lambda *args: None)
    assert result['failed'] == []
    assert data[0].get(type(schedule), schedule_id) is None


def test_execute_refreshes_and_does_not_delete_video_that_recovered_since_preview(data):
    candidate = preview(data)['candidates'][0]
    data[3][0]['statistics']['viewCount'] = '900'
    def forbidden(*args):
        raise AssertionError('Recovered video must not be deleted')
    result = execute(data, [candidate['video_id']], forbidden)
    assert result['deleted_count'] == 0 and len(result['skipped']) == 1


def test_local_failure_is_retriable_without_deleting_youtube_twice(data):
    video, schedule, *_ = release(data)
    video_id, schedule_id = video.id, schedule.id
    calls = []
    def fail_delete(mapper, connection, target):
        raise RuntimeError('模拟本地数据库故障')
    event.listen(YoutubeVideo, 'before_delete', fail_delete)
    try:
        first = execute(data, [video_id], lambda token, external: calls.append(external))
    finally:
        event.remove(YoutubeVideo, 'before_delete', fail_delete)
    assert first['deleted_count'] == 1 and first['cleaned_count'] == 0
    assert first['failed'][0]['remote_deleted'] is True
    assert data[0].get(type(schedule), schedule_id) is not None
    data[3].pop(0)
    assert preview(data)['pending_cleanup'][0]['video_id'] == video_id
    second = execute(data, [video_id], lambda *args: pytest.fail('必须沿用已成功删除的结果'))
    assert second['deleted_count'] == 0 and second['cleaned_count'] == 1
    assert calls == ['video000000']


@pytest.mark.parametrize('failure', ['commit_after_delete', 'timeout_after_delete'])
def test_retry_recovers_remote_deletion_even_when_first_confirmation_was_lost(data, failure):
    video, schedule, *_ = release(data)
    video_id, schedule_id = video.id, schedule.id
    deleted = []
    def first_delete(token, key):
        deleted.append(key)
        data[3].pop(0)
        if failure == 'timeout_after_delete':
            raise ValueError('无法确认 YouTube 视频删除结果')
    once = [False]
    def fail_once(s):
        if deleted and not once[0]:
            once[0] = True
            raise RuntimeError('模拟删除成功后首次提交失败')
    if failure == 'commit_after_delete':
        event.listen(data[0], 'before_commit', fail_once)
    try:
        first = execute(data, [video_id], first_delete)
    finally:
        if failure == 'commit_after_delete':
            event.remove(data[0], 'before_commit', fail_once)
    assert first['cleaned_count'] == 0
    refreshed = preview(data)
    assert [row['video_id'] for row in refreshed['pending_cleanup']] == [video_id]
    second = execute(data, [video_id], lambda *args: pytest.fail('不得重复删除已确认不存在的视频'))
    assert second['cleaned_count'] == 1 and second['failed'] == []
    assert data[0].get(type(schedule), schedule_id) is None
    assert deleted == ['video000000']


def test_cleanup_removes_runtime_and_package_children_with_real_foreign_keys(data):
    from zhiju.models import MediaAsset, PackageTitle, YoutubeVideoDailyMetric
    from zhiju.models.v14 import V14Attempt, V14Run
    from zhiju.models.settings import ImageProcessingRun, ImageProcessingItem
    from zhiju.models import ProductionBatch
    video, schedule, task, order, package = release(data)
    s = data[0]
    title = PackageTitle(package_id=package.id, variant_number=1, localized_title='原始标题',
                         chinese_translation='中文对照')
    # Use existing production state and a real V14 run, rather than removing FKs in tests.
    run = V14Run(work_order_id=order.id, package_id=package.id, host_id='old-host', account_profile='old-account',
                 model='fixture-model', status='text_ready', input_snapshot={}, rules_snapshot={})
    asset = MediaAsset(operation_package_id=package.id, channel_id=data[1].id, storage_provider='local',
                       storage_key='preserved-image.png', asset_type='image', asset_role='thumbnail',
                       sha256='existing-asset-value', file_size_bytes=10, status='ready')
    metric = YoutubeVideoDailyMetric(video_id=video.id, metric_date=NOW.date(), views=99, synced_at=NOW)
    batch = ProductionBatch(batch_number='batch-original', production_date=NOW.date(), source='native')
    s.add_all([run, asset, metric, batch, title]); s.flush()
    image_run = ImageProcessingRun(batch_id=batch.id, status='classified')
    s.add(image_run); s.flush()
    item = ImageProcessingItem(run_id=image_run.id, original_filename='original.png', stored_path='original.png',
                               match_status='matched', package_id=package.id, schedule_id=schedule.id)
    attempt = V14Attempt(run_id=run.id, claim_id='old-claim', node_type='merge', sequence=1, outcome='accepted')
    s.add_all([item, attempt]); s.commit()
    ids = run.id, attempt.id, item.id, metric.id, asset.id, title.id
    result = execute(data, [video.id], lambda *args: None)
    assert result['failed'] == []
    for model, key in zip((V14Run, V14Attempt, ImageProcessingItem, YoutubeVideoDailyMetric), ids[:4]):
        s.expire_all()
        assert s.get(model, key) is None
    preserved = s.get(MediaAsset, ids[4])
    assert preserved.operation_package_id is None and preserved.storage_key == 'preserved-image.png'
    assert s.get(PackageTitle, ids[5]) is None


def test_rejects_foreign_channel_api_data_before_any_deletion(data):
    data[3][0]['snippet']['channelId'] = 'UC-someone-else'
    with pytest.raises(service.ConflictError, match='其他频道'):
        execute(data, ['anything'], lambda *args: pytest.fail('不得跨频道删除'))


def test_does_not_force_a_bottom_percentage_when_all_views_are_equal(data):
    for row in data[3]:
        row['statistics']['viewCount'] = '100'
    assert preview(data)['candidates'] == []


def test_cannot_delete_arbitrary_or_other_channel_ids(data):
    result = execute(data, ['unlisted-video-id'], lambda *args: pytest.fail('只可处理重新判断后仍命中的视频'))
    assert result['deleted_count'] == 0 and len(result['skipped']) == 1


def test_cleanup_routes_refresh_and_execute_with_channel_management_permission(data, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from zhiju.api import youtube_oauth as api
    from zhiju.auth_context import Principal, get_current_principal, get_tenant_db
    app = FastAPI()
    app.include_router(api.router, prefix='/api')
    app.dependency_overrides[get_tenant_db] = lambda: data[0]
    permissions = set()
    def principal():
        return Principal(user_id='user-a', tenant_id='test-tenant', membership_role='owner', platform_role=None,
                         device_id='builder', device_trust_level='normal', permissions=frozenset(permissions))
    app.dependency_overrides[get_current_principal] = principal
    monkeypatch.setattr(api, 'get_settings', lambda: SimpleNamespace(deployment='local', device_role='builder'))
    monkeypatch.setattr(api, 'MacOSKeychainSecretStore', TokenStore)
    real_preview, real_execute = service.preview_cleanup, service.execute_cleanup
    monkeypatch.setattr(service, 'preview_cleanup', lambda *args, **kwargs: real_preview(
        *args, **kwargs, requester=data[5], now=NOW))
    deleted = []
    monkeypatch.setattr(service, 'execute_cleanup', lambda *args, **kwargs: real_execute(
        *args, **kwargs, requester=data[5], now=NOW, deleter=lambda token, key: deleted.append(key)))
    url = f'/api/v3/channels/{data[1].id}/low-view-cleanup'
    with TestClient(app) as client:
        assert client.post(url + '/preview').status_code == 403
        assert client.post(url + '/execute', json={'video_ids': ['anything']}).status_code == 403
        assert data[4] == []
        permissions.add('channel.manage')
        response = client.post(url + '/preview')
        assert response.status_code == 200, response.text
        video_id = response.json()['candidates'][0]['video_id']
        result = client.post(url + '/execute', json={'video_ids': [video_id]})
        assert result.status_code == 200, result.text
        assert result.json()['deleted_count'] == 1
        assert deleted == ['video000000']


def test_preview_hides_channels_from_other_tenants(data):
    s = data[0]
    with TenantSession(s.get_bind(), info={'tenant_id': 'different-tenant'}) as other:
        with pytest.raises(service.NotFoundError, match='频道不存在'):
            service.preview_cleanup(other, TokenStore(), channel_id=data[1].id,
                                    requester=lambda *args: pytest.fail('不能读取其他租户频道'), now=NOW)
