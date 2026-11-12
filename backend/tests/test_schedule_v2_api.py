"""V2 can be selected and called through the existing system API, without v1 migration."""
from copy import deepcopy

from test_v14_api import client
from test_v14_runs import store
from test_schedule_planning_api import seed
from test_three_module_integration import applied_sample
from test_schedule_v2 import profile
from zhiju.database import TenantSession
from zhiju.models import ChannelPlaylist
from zhiju.services import skill_catalog, schedule_batch, schedule_evidence
from zhiju.v14_executor.schedule_planning import generate
from types import SimpleNamespace


def test_v2_http_select_preview_confirm_preserves_legacy_and_allows_cross_channel_reuse(client, store, monkeypatch, tmp_path):
    seed(store, 2)
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        old = skill_catalog.scheduling_snapshot(s)
        s.add(ChannelPlaylist(id='chosen', channel_id='channel-a', local_name='主动反击', status='active',
            youtube_playlist_id='PLChosen', url='https://www.youtube.com/playlist?list=PLChosen'))
        s.commit()
        applied_sample(s)
    base = '/api/v3/skill-categories/channel-scheduling'
    versions = next(item for item in client.get('/api/v3/skill-categories').raise_for_status().json()
                    if item['id'] == 'channel-scheduling')
    assert versions['default_id'] == old['id']
    assert client.get(base + '/versions/builtin-channel-scheduling-v2/download').raise_for_status().content
    client.post(base + '/default', json={'version_id': 'builtin-channel-scheduling-v2'}).raise_for_status()
    detail = client.get(base + '/versions/builtin-channel-scheduling-v2', params={'path': 'SKILL.md'}).raise_for_status().json()
    assert 'name: channel-scheduling-v2' in detail['content']
    body = {'start_date': '2026-11-13', 'end_date': '2026-11-13', 'daily_count': 2,
            'slot_topics': {'slot-plan': 'primary', 'slot-plan-secondary': 'primary'}}
    assert client.post('/api/v3/channels/channel-a/schedule-plans', json={**body, 'executor_protocol': 15}).status_code == 409
    # Simulate a same-language peer reservation. V2 does not impose cross-channel deduplication.
    blocked = [{'drama_id': 'drama-a', 'beijing_date': '2026-11-13'}]
    from datetime import date
    monkeypatch.setattr(schedule_batch, 'reservations', lambda *args: (date(2026, 11, 13), date(2026, 12, 2), blocked))
    plan = client.post('/api/v3/channels/channel-a/schedule-plans', json={**body, 'executor_protocol': 16}).raise_for_status().json()
    assert plan['input_snapshot']['selection_method'] == 'audience-sequence-v2'
    assert plan['input_snapshot']['batch_blocked'] == []
    assert plan['input_snapshot']['skill_version']['label'] == 'channel-scheduling-v2'
    assert client.get('/api/v3/schedules').json() == []
    assert client.post('/api/v3/schedule-planning/claims', json={'host_id': 'device-a', 'executor_protocol': 15}).status_code == 204
    assert client.post('/api/v3/executor/claims',json={'host_id':'device-a','claim_id':'991dd7c9-2001-4bae-96d7-010101010101','executor_protocol':15}).status_code==204
    claim = client.post('/api/v3/schedule-planning/claims', json={'host_id': 'device-a', 'executor_protocol': 16}).raise_for_status().json()
    monkeypatch.setattr(schedule_evidence, 'collect', lambda *args: {
        'collected_at': '2026-11-12T00:00:00Z', 'missing': ['封面和开场未取得'],
        'analytics': {}, 'videos': [], 'previous_review': None})
    claim = client.post(f"/api/v3/schedule-plans/{plan['id']}/evidence", json={'claim_id': claim['claim_id']}).raise_for_status().json()
    snap = claim['input_snapshot']
    def respond(stage, model):
        if 'viewer_promises' in stage.schema['properties']:
            result = deepcopy(profile())
            result['tiers'] = [['drama-a', 'drama-second']]
            result['comparisons'] = [{**result['comparisons'][0], 'drama_id': key, 'focus_match': True}
                                     for key in ('drama-a', 'drama-second')]
            return result
        if 'predecessor_drama_id' in stage.schema['properties']['rows']['items']['properties']:
            return {'rows': [
                {'publish_date': '2026-11-13', 'publish_slot_id': slot, 'drama_id': key,
                 'reason': '持续主动反击，符合本频道关系背叛定位', 'plot_evidence': '女主遭到背叛后夺回公司。',
                 'pairing_reason': '同日围绕遭背叛后主动夺回的位置与回报', 'predecessor_drama_id': previous,
                 'alternative_drama_id': other, 'comparison_reason': '与另一候选相比，先建立背叛冲突再承接主动夺回。',
                 'packaging_promise': '背叛她的人失去公司，她亲手夺回。', 'opening_check': '尚未读开场，需检查能否兑现背叛冲突。'}
                for slot, key, previous, other in [
                    ('slot-plan-secondary', 'drama-a', None, 'drama-second'),
                    ('slot-plan', 'drama-second', 'drama-a', None)]]}
        return {'rows': [{'drama_id': row['id'], 'actual_theme': 'primary', 'actual_direction': '关系背叛后女主夺回公司',
            'strong_direction_ids': ['primary:1'], 'playlist_id': 'chosen', 'reason': '女主主动反击的持续主线',
            'plot_evidence': row['content_summary']} for row in snap['candidates']]}
    result = generate(SimpleNamespace(generate=respond), claim, tmp_path)
    ready = client.put(f"/api/v3/schedule-plans/{plan['id']}/result", json={
        'claim_id': claim['claim_id'], 'result': result}).raise_for_status().json()
    assert ready['status'] == 'ready'
    assert client.get('/api/v3/schedules').json() == []
    saved = client.post(f"/api/v3/schedule-plans/{plan['id']}/apply").raise_for_status().json()
    assert saved['status'] == 'applied'
    assert len(client.get('/api/v3/schedules').json()) == 2
    reread = client.get(f"/api/v3/schedule-plans/{plan['id']}").raise_for_status().json()
    assert reread['result']['rows'][1]['predecessor_drama_id'] == 'drama-a'
    assert reread['result']['planning_review']['next_actions']
    client.post(base + '/default', json={'version_id': old['id']}).raise_for_status()
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        assert skill_catalog.scheduling_snapshot(s) == old
    assert reread['input_snapshot']['skill_version']['label'] == 'channel-scheduling-v2'
