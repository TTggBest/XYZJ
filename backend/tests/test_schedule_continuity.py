"""R4 must compare viewer promises, not equate all broad strong matches."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest

from test_schedule_planning import data


def snapshot():
    plot = '丈夫偷走股权，女主收集合同证据，公开夺回公司并让丈夫入狱。'
    return {
        'model': 'test', 'selection_method': 'audience-continuity-v1',
        'skill_version': {'files': {'SKILL.md': '按真实观众需求选择。'}},
        'operating_reference': {'dna_id': 'dna', 'sections': {
            'topics': {'primary': ['亲密关系背叛后的主动反击'], 'secondary': []},
            'empathy': {}, 'selection_guidance': {}}},
        'analysis_topics': {'primary': ['亲密关系背叛后的主动反击'], 'secondary': []},
        'selection_evidence': {'collected_at': '2026-11-12T00:00:00+00:00',
            'analytics': {'recent_7d': {'status': 'available', 'rows': [
                {'video': 'winner', 'views': 5000, 'averageViewDuration': 900}]}},
            'videos': [{'youtube_video_id': 'winner', 'plot': '丈夫夺产，妻子拿证据夺回公司。'}],
            'missing': ['封面实图、开场留存未取得'], 'previous_review': {'viewer_promise': '旧假设'}},
        'playlists': [{'id': 'playlist'}],
        'slots': [{'id': 'main', 'timezone': 'Asia/Shanghai', 'local_time': '10:00', 'slot_type': 'main'}],
        'slot_topics': {'main': 'primary'}, 'batch_blocked': [], 'date_basis': 'beijing',
        'targets': [{'publish_date': '2026-11-13', 'publish_slot_id': 'main'}],
        'candidates': [{'id': key, 'chinese_title': key, 'duration_seconds': length,
            'source_language': 'zh', 'expires_at': None, 'finished_languages': ['en'],
            'content_summary': plot} for key, length in [('broad', 10000), ('exact', 3600), ('peer', 4500)]]}


def comparison():
    return {'viewer_promises': {'primary': '丈夫夺产→妻子取证→夺回公司、丈夫失位', 'secondary': ''},
        'evidence_review': '本频道 winner 的夺产反击线已有消费，仍需区分发布时间与样本量。',
        'feedback_review': '重新核对旧假设，不凭旧排期继续复制。',
        'packaging_review': '标题已登记；封面实图和前30秒未读取，不能认定已兑现。',
        'tiers': [['peer', 'exact'], ['broad']],
        'comparisons': [{'drama_id': key, 'focus_match': key != 'broad',
            'reason': '对比 broad：以丈夫夺产和女主取证为持续主线，结局公开夺回公司。' if key != 'broad'
                      else '相对 exact 只符合较宽的逆袭方向，不能优先当作同一种观众回报。'}
                       for key in ('broad', 'exact', 'peer')]}


def model_for(snap, result, prompts):
    def generate(stage, model):
        prompts.append(stage.prompt)
        if 'viewer_promises' in stage.schema['properties']:
            return result
        return {'rows': [{'drama_id': row['id'], 'actual_theme': 'primary',
            'actual_direction': '妻子取证夺产', 'strong_direction_ids': ['primary:1'],
            'playlist_id': 'playlist', 'reason': '按原文核对', 'plot_evidence': row['content_summary']}
                        for row in snap['candidates']]}
    return SimpleNamespace(generate=generate)


def test_r4_compares_complete_pool_before_duration_and_preserves_review(tmp_path):
    from zhiju.v14_executor.schedule_planning import generate
    from zhiju.scheduling_rules.contract import validate_result
    snap = snapshot(); prompts = []
    result = generate(model_for(snap, comparison(), prompts), {'input_snapshot': snap}, tmp_path)
    # Same-quality narrow matches retain the duration tie-break; the long broad one loses.
    assert result['rows'][0]['drama_id'] == 'peer'
    assert '对比 broad' in result['rows'][0]['pairing_reason']
    assert 'winner' in prompts[-1] and '旧假设' in prompts[-1]
    assert sum('本频道表现与上次复盘' in text for text in prompts) == 1
    saved = validate_result(snap, result)
    assert saved['planning_review']['viewer_promises']['primary'].startswith('丈夫夺产')
    assert saved['planning_review']['compared_candidates'] == 3
    assert saved['planning_review']['evidence_collected_at'] == snap['selection_evidence']['collected_at']
    assert saved['planning_review']['missing_evidence'] == snap['selection_evidence']['missing']
    assert saved['rows'][0]['selection_focus'] == saved['planning_review']['viewer_promises']['primary']


@pytest.mark.parametrize('bad', ['duplicate', 'missing', 'foreign', 'missing_evidence'])
def test_r4_rejects_unreviewed_pool_or_missing_feedback_instead_of_silent_longest(tmp_path, bad):
    from zhiju.v14_executor.schedule_planning import generate
    snap = snapshot(); compared = comparison()
    if bad == 'duplicate': compared['tiers'][1].append('peer')
    if bad == 'missing': compared['comparisons'].pop()
    if bad == 'foreign': compared['tiers'][1].append('foreign')
    if bad == 'missing_evidence': snap.pop('selection_evidence')
    with pytest.raises(ValueError):
        generate(model_for(snap, compared, []), {'input_snapshot': snap}, tmp_path)


def test_r4_comparison_cache_reused_but_old_r3_path_unchanged(tmp_path):
    from zhiju.v14_executor.schedule_planning import generate
    snap = snapshot(); prompts = []
    result = generate(model_for(snap, comparison(), prompts), {'input_snapshot': snap}, tmp_path)
    again = generate(SimpleNamespace(generate=lambda *args: pytest.fail('must reuse frozen evidence and judgments')),
                     {'input_snapshot': snap}, tmp_path)
    assert again == result
    old = deepcopy(snap); old.pop('selection_method'); old.pop('selection_evidence')
    assert generate(model_for(old, comparison(), []), {'input_snapshot': old}, tmp_path)['rows'][0]['drama_id'] == 'broad'


def test_r4_broad_fill_is_marked_as_deviation_even_if_it_shares_the_playlist(tmp_path):
    from zhiju.v14_executor.schedule_planning import generate
    snap = snapshot()
    snap['targets'] *= 3
    snap['targets'] = [{**row, 'publish_date': f'2026-11-{day}'}
                       for day, row in zip((13, 14, 15), snap['targets'])]
    rows = generate(model_for(snap, comparison(), []), {'input_snapshot': snap}, tmp_path)['rows']
    assert [row['drama_id'] for row in rows] == ['peer', 'exact', 'broad']
    assert rows[-1]['match_level'] == 'fallback'
    assert rows[-1]['deviates_from_target'] is True
    assert '细分观看承诺' in rows[-1]['fallback_reason']


def test_feedback_collects_current_channel_windows_and_preserves_unavailable(data):
    from zhiju.models import YoutubeVideo, ChannelSchedulePlan
    from zhiju.services.schedule_evidence import collect
    s, channel, drama, *_ = data
    s.add(YoutubeVideo(youtube_video_id='mapped', channel_id=channel.id, drama_id=drama.id,
        title='真实标题', url='https://www.youtube.com/watch?v=mapped',
        privacy_status='public', publish_status='published', source='youtube_sync',
        published_at=datetime(2026, 11, 10, tzinfo=timezone.utc), duration_seconds=3600))
    s.add(ChannelSchedulePlan(channel_id=channel.id, host_id='host', status='applied',
        input_snapshot={}, result={'planning_review': {'viewer_promises': {'primary': '旧承接假设'}}}))
    s.commit(); calls = []
    def fetch(url, token):
        calls.append(url)
        assert token == 'test-token' and 'ids=channel%3D%3DMINE' in url
        return {'columnHeaders': [{'name': key} for key in
            ['video', 'views', 'averageViewDuration', 'averageViewPercentage', 'subscribersGained']],
            'rows': [['mapped', 0, 0, 0, 0], ['unmapped', 50, 100, 10, 1]]}
    result = collect(s, {'channel': {'id': channel.id, 'youtube_channel_id': channel.youtube_channel_id,
        'original_name': channel.original_name}, 'guidance': {'normalized_snapshot': {
            'source_manifest': [{'source': 'studio/export', 'window': {'end': '2026-11-07'}}],
            'retention_intro_30s_pct': {'status': 'available', 'value': 48}}}},
        now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
        fetcher=fetch, authorize=lambda *args: ('test-token', {}, {}))
    assert len(calls) == 3
    assert result['analytics']['recent_7d']['window'] == {
        'start': '2026-11-05', 'end': '2026-11-11', 'timezone': 'America/Los_Angeles'}
    assert result['analytics']['recent_7d']['rows'][0]['views'] == 0
    assert result['videos'][0]['drama_id'] == drama.id
    assert result['videos'][0]['plot'] == drama.content_summary
    assert result['previous_review']['viewer_promises']['primary'] == '旧承接假设'
    assert result['missing'] and 'retention_30s' not in result['analytics']['recent_7d']['rows'][0]
    assert len(result['videos']) == 1  # Never invent a drama mapping from the title.
    assert result['unmapped_performance_video_ids'] == ['unmapped']
    assert any('1个有表现的视频' in value for value in result['missing'])
    assert result['applied_studio']['windows']['studio/export']['end'] == '2026-11-07'
    assert result['applied_studio']['retention_observations']['value'] == 48
    unavailable = collect(s, {'channel': {'id': channel.id}},
        authorize=lambda *args: (_ for _ in ()).throw(ValueError('无法连接YouTube API')))
    assert unavailable['analytics']['recent_7d']['status'] == 'unavailable'
    assert unavailable['analytics']['recent_7d']['rows'] == []


def test_new_method_needs_new_executor_claim_without_affecting_old_tasks(data):
    from sqlalchemy import select
    from zhiju.models import ChannelSchedulePlan
    from zhiju.services.schedule_planning import claimable_plans
    s, channel, *_ = data
    s.add_all([ChannelSchedulePlan(id=key, channel_id=channel.id, host_id='host',
        input_snapshot=body) for key, body in [('old', {}), ('new', {'selection_method': 'audience-continuity-v1'})]])
    s.commit()
    query = select(ChannelSchedulePlan.id)
    assert list(s.scalars(claimable_plans(query, 13))) == ['old']
    assert set(s.scalars(claimable_plans(query, 14))) == {'old', 'new'}


def test_evidence_freeze_is_claim_bound_and_idempotent(data, monkeypatch):
    from zhiju.models import ChannelSchedulePlan
    from zhiju.services import schedule_planning as service, schedule_evidence
    from zhiju.services.identity import ConflictError
    s, channel, *_ = data
    plan = ChannelSchedulePlan(channel_id=channel.id, host_id='host', status='running', claim_id='claim',
        input_snapshot={'channel': {'id': channel.id}, 'selection_method': 'audience-continuity-v1'})
    s.add(plan); s.commit(); calls = []
    def collect(*args):
        calls.append(True)
        return {'collected_at': '2026-11-12T00:00:00+00:00', 'missing': ['CTR unavailable']}
    monkeypatch.setattr(schedule_evidence, 'collect', collect)
    with pytest.raises(ConflictError): service.freeze_evidence(s, plan.id, 'foreign-claim')
    first = deepcopy(service.freeze_evidence(s, plan.id, 'claim')['input_snapshot'])
    second = service.freeze_evidence(s, plan.id, 'claim')['input_snapshot']
    assert first == second and len(calls) == 1
    plan.status = 'cancelled'; s.commit()
    with pytest.raises(ConflictError): service.freeze_evidence(s, plan.id, 'claim')
