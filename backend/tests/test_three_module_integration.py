"""Regression coverage for the applied-reference, schedule and package handoff."""
from copy import deepcopy
from datetime import date, datetime, time
from io import BytesIO
import json
from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from sqlalchemy import select
import yaml

from test_channel_analysis_runs import valid_result
from test_schedule_planning_api import seed
from test_v14_api import client
from test_v14_runs import store
from zhiju.database import TenantSession
from zhiju.models import (Channel, ChannelPlaylist, ChannelProfile, ChannelScheduleEntry,
                          ChannelPublishSlot, Drama, DramaProductionState)
from zhiju.models.v14 import V14Run, V14Setting, WorkflowSkillVersion
from zhiju.services import channel_analysis, schedule_batch, skill_catalog
from zhiju.services.identity import ConflictError
from zhiju.v14_executor.schedule_planning import generate
from zhiju.v14_runtime.market import reconcile_revision6_evidence


def zip_rule(path, body, *, analysis=False):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('SKILL.md', '# QA')
        archive.writestr(path, body)
        if analysis:
            for name in ('authorization', 'asset-contract', 'analysis-rules', 'generation-spec-contract'):
                archive.writestr(f'references/{name}.md', '# QA')
            archive.writestr('scripts/validate_generation_spec.py', '# QA')
    return buffer.getvalue()


def install_rule(session, category, label, content, revision):
    version = None
    for _ in range(revision - 1):
        version = skill_catalog.upload(session, category, label, 'isolated QA', content)
    assert version['revision'] == revision
    skill_catalog.publish(session, category, version['id'])
    skill_catalog.select_default(session, category, version['id'])


def applied_sample(session, *, handoff=None):
    analysis_zip = (handoff / '频道分析-r3/xy-yt-report-v2-r3.zip').read_bytes() if handoff else zip_rule(
        'references/output-contract.md', 'channel_strategy.operating_reference', analysis=True)
    install_rule(session, skill_catalog.ANALYSIS, 'xy-yt-report-v2', analysis_zip, 3)
    from zhiju.channel_analysis_rules.operating_reference import SECTIONS
    if handoff:
        sections = json.loads((handoff / '频道分析-r3/Elle_运营参考字段样例.json').read_text())['operating_reference']
    else:
        sections = {key: {'conclusion': '女主反击', 'evidence': ['定位确认'], 'status': 'retest'} for key in SECTIONS}
        sections['topics'].update(primary=['关系背叛'], secondary=['职场反击'], boundary='女主主动改变处境', counterexamples=['甜宠'])
        sections['scheduling_playlist'] = {
            **sections.pop('selection_guidance'), 'playlist_reference': ['legacy playlist suggestion'],
        }
    # Replay the editorial reference as an explicit cold-start hypothesis.
    for section in sections.values():
        section['status'] = 'cold_start_hypothesis'
    run = channel_analysis.create_run(session, 'channel-a', mode='initial', positioning='女主反击')
    sample = valid_result(run)
    diagnosis = sample['diagnosis'].split('```yaml\n')[1].split('```')[0]
    strategy = yaml.safe_load(diagnosis)['channel_strategy']
    strategy.update(channel_id='UC-a', operating_reference=sections,
                    content_priority=sections['topics']['primary'], content_secondary=sections['topics']['secondary'])
    sample['diagnosis'] = sample['diagnosis'].split('```yaml')[0] + '```yaml\n' + yaml.safe_dump(
        {'channel_strategy': strategy}, allow_unicode=True) + '```'
    sample['normalized_snapshot']['channel']['youtube_channel_id'] = 'UC-a'
    sample['operating_reference'] = {'untrusted': True}
    channel_analysis.start_run(session, run.id)
    claim = channel_analysis.claim_run(session, 'device-a')
    ready = channel_analysis.submit_result(session, run.id, claim['claim_id'], result=sample)
    assert ready.status == 'ready'
    applied = channel_analysis.apply_result(session, run.id)
    assert applied.result['diagnosis'] == sample['diagnosis']
    assert 'scheduling_playlist' in sections
    expected = {key: value for key, value in sections.items() if key != 'scheduling_playlist'}
    topics = sections['topics']
    expected['selection_guidance'] = {
        'status': topics['status'], 'evidence': topics['evidence'],
        'conclusion': topics['boundary'], 'boundary_only': True,
    }
    return applied.dna_id, applied.report_id, expected


@pytest.mark.parametrize('real_archives', [False, True])
def test_analysis_to_schedule_to_new_work_order(client, store, monkeypatch, tmp_path, real_archives):
    handoff_path = os.getenv('ZHJ_R3_HANDOFF')
    if real_archives and not handoff_path:
        pytest.skip('set ZHJ_R3_HANDOFF to the folder containing the three reviewed Skills archives')
    handoff = Path(handoff_path) if real_archives else None
    seed(store, 2)
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        channel = s.get(Channel, 'channel-a')
        channel.original_name = 'Elle prend sa revanche'
        channel.default_language = 'fr'
        channel.created_at = datetime(2026, 10, 31, 19)
        setting = s.scalar(select(V14Setting))
        payload = deepcopy(setting.payload)
        payload['channel_inputs']['channel-a']['language'] = 'fr'
        setting.payload = payload
        s.add(ChannelPlaylist(id='chosen', channel_id=channel.id, local_name='Trahison et revanche',
            youtube_playlist_id='PLChosen', url='https://www.youtube.com/playlist?list=PLChosen',
            local_description='Dramas de revanche', status='active'))
        s.add(Drama(id='weak', drama_number=9, drama_code='DR-weak', chinese_title='另一部剧',
                    normalized_title='另一部剧', content_summary='女主参加了亲戚聚会。'))
        s.add(DramaProductionState(drama_id='weak', production_completion_status='completed',
            finished_languages=['fr'], total_duration_seconds=7200))
        s.get(Drama, 'drama-a').source_language = 'zh'
        for state in s.scalars(select(DramaProductionState)):
            state.finished_languages = ['fr']
        s.get(DramaProductionState, s.scalar(select(DramaProductionState.id).where(
            DramaProductionState.drama_id == 'drama-a'))).total_duration_seconds = 5100
        from zhiju.models import ChannelPinnedCommentTemplate
        s.add(ChannelPinnedCommentTemplate(channel_id=channel.id, language='fr', version_number=1, body='reply', status='active'))
        s.commit()
        dna_id, report_id, sections = applied_sample(s, handoff=handoff)
        schedule_zip = (handoff / '2026-11-09_B_频道排期r3/channel-scheduling-r3-release-candidate.zip').read_bytes() if handoff else zip_rule(
            'references/qa.md', '按实际题材选择列表')
        install_rule(s, skill_catalog.SCHEDULING, 'channel-scheduling', schedule_zip, 3)
        if real_archives:
            s.add(WorkflowSkillVersion(id='v20-r6', label='V20', revision=6, status='published', change_summary='isolated',
                archive=(handoff / '运营包-V20-r6/V20-修订6-Skill草稿.zip').read_bytes()))
            s.commit()
    base = '/api/v3/channels/channel-a'
    detail = client.get(base).raise_for_status().json()
    assert detail['operating_reference']['report_id'] == report_id
    assert detail['operating_reference']['sections'] == sections
    assert detail['operating_reference']['skill_version']['revision'] == 3
    body = {'start_date': '2026-11-03', 'end_date': '2026-11-03', 'daily_count': 2,
            'slot_topics': {'slot-plan': 'primary', 'slot-plan-secondary': 'secondary'}}
    assert client.post(base + '/schedule-plans', json={**body, 'executor_protocol': 9}).status_code == 409
    plan = client.post(base + '/schedule-plans', json={**body, 'executor_protocol': 10}).raise_for_status().json()
    snapshot = plan['input_snapshot']
    assert snapshot['batch']['registered_on'] == '2026-11-01'
    assert snapshot['operating_reference']['dna_id'] == dna_id
    assert {row['id']: row['source_language'] for row in snapshot['candidates']}['drama-a'] == 'zh'
    assert client.post('/api/v3/schedule-planning/claims', json={'host_id': 'device-a', 'executor_protocol': 9}).status_code == 204
    claim = client.post('/api/v3/schedule-planning/claims', json={'host_id': 'device-a', 'executor_protocol': 10}).raise_for_status().json()

    def judge(stage, model):
        assert sections['topics']['boundary'] in stage.prompt
        assert 'legacy playlist suggestion' not in stage.prompt
        assert 'selection_guidance' in stage.prompt
        return {'rows': [
            {'drama_id': row['id'], 'actual_theme': kind,
             'strong_direction_ids': [f'{kind}:1'] if kind != 'neither' else [],
             'actual_direction': '女主主动反击', 'playlist_id': 'chosen',
             'reason': '逐部判断', 'plot_evidence': row['content_summary']}
            for row in snapshot['candidates']
            for kind in [{'drama-a': 'primary', 'drama-second': 'secondary', 'weak': 'neither'}[row['id']]]
        ]}

    result = generate(SimpleNamespace(generate=judge), claim, tmp_path)
    assert next(row for row in result['rows'] if row['publish_slot_id'] == 'slot-plan')['drama_id'] == 'drama-a'
    plan_path = f"/api/v3/schedule-plans/{plan['id']}"
    client.put(plan_path + '/result', json={'claim_id': claim['claim_id'], 'result': result}).raise_for_status()
    saved = client.post(plan_path + '/apply').raise_for_status().json()
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        schedule = s.scalar(select(ChannelScheduleEntry).where(ChannelScheduleEntry.drama_id == 'drama-a'))
        assert schedule.id in saved['result']['schedule_ids']
        assert schedule.playlist_id == 'chosen' and schedule.channel_dna_version_id == dna_id
        schedule_id = schedule.id
    task = client.post('/api/v3/tasks', json={'schedule_id': schedule_id, 'task_date': '2026-11-03',
        'idempotency_key': 'r3-qa-task'}).raise_for_status().json()
    run_data = client.post(f"/api/v3/tasks/{task['id']}/start-v14",
        json={'workflow_version_id': 'v20-r6'} if real_archives else {}).raise_for_status().json()
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        run = s.get(V14Run, run_data['run_id'])
        assert run.input_snapshot['channel']['analysis_version']['report_id'] == report_id
        assert run.input_snapshot['schedule_assignment']['operating_reference_version_id'] == dna_id
        assert run.input_snapshot['schedule_assignment']['playlist']['id'] == 'chosen'
        if real_archives:
            assert run.input_snapshot['channel']['operating_reference']['sections'] == sections
            assert run.input_snapshot['channel']['title_template'] == s.scalar(select(ChannelProfile.title_template))
            assert run.input_snapshot['workflow_version']['revision'] == 6
            from zhiju.workflow_bundles import executor_protocol
            assert executor_protocol(run.rules_snapshot) == 10
            exercise_v20_stages(run, sections, monkeypatch)


def exercise_v20_stages(run, sections, monkeypatch):
    from zhiju.v14_executor.codex import CodexClient
    from zhiju.v14_executor.thumbnail_creator import ThumbnailCreator
    from zhiju.v14_runtime.contract import build_stage_input, validate_result, _scheduled_playlist_issues

    envelope = {'run_id': run.id, 'rules_snapshot': run.rules_snapshot, 'input_snapshot': deepcopy(run.input_snapshot),
                'accepted_results': {'search': {'market_payload': {'angle_candidates': [
                    {'candidate_id': f'candidate-{i}'} for i in (1, 2, 3)]}},
                    'title': {'results': [{'packaging_brief': {}, 'directions': [
                    {'title': f'Locked title {i}', 'translation': '样例', 'selected_candidate_id': str(i)}
                    for i in (1, 2, 3)]}]}, 'cover': {'results': [{'titles': []}]}}}
    title = build_stage_input(envelope, 'title')
    assert sections['title']['conclusion'] in title.rules['title_creation']['prompt']
    assert sections['empathy']['conclusion'] in title.rules['title_creation']['prompt']
    assert sections['cover']['conclusion'] not in title.rules['title_creation']['prompt']
    cover = build_stage_input(envelope, 'cover')
    assert 'Chinese' in cover.context['casting'] and sections['cover']['conclusion'] in cover.prompt
    assert sections['cover']['conclusion'] not in str(cover.rules['cover_concepts'])
    description = build_stage_input(envelope, 'description')
    chosen = description.context['scheduled_playlist']
    output = {'results': [{'url': chosen['url'], 'playlist': chosen['name'],
                           'description': '正文\n' + chosen['url']}]}
    assert not _scheduled_playlist_issues(description, output)
    output['results'][0]['description'] = 'https://www.youtube.com/playlist?list=PLOther\n' + chosen['url']
    assert _scheduled_playlist_issues(description, output)
    envelope['input_snapshot']['community_count'] = 2
    community = build_stage_input(envelope, 'community_scene')
    source = envelope['input_snapshot']['drama']['content_summary']
    calls = []
    class Creator:
        skills = [{'name': 'youtube-thumbnail-creator:concepts'}]
        def new_thread(self, model, *, use_plugin):
            assert use_plugin
            return 'community'
        def run(self, thread, prompt, schema, *, use_plugin):
            assert thread == 'community' and use_plugin
            calls.append(json.loads(prompt.split('\n\n')[1]))
            fields = schema['properties']['plans']['items']['required']
            rows = [{key: ('说明' if key not in ('index', 'history_reference') else '')
                     for key in fields} for _ in range(2)]
            for i, row in enumerate(rows, 1):
                row.update(index=i, source_anchor=source, main_action=f'第 {i} 种可见动作')
            return {'section': 'community_scene', 'plans': rows}
    @contextmanager
    def open_creator(*args):
        yield Creator()
    monkeypatch.setattr(ThumbnailCreator, 'open', open_creator)
    executor = CodexClient()
    plans = executor.generate(community, 'test-model')
    assert calls[0]['aspect_ratio'] == '1:1' and calls[0]['count'] == 2
    assert calls[0]['plot_summary'] == source and calls[0]['characters']
    assert executor.phase_trace[0]['phase'] == 'community_thumbnail_creator'
    assert not validate_result(community, plans)
    duplicate = deepcopy(plans)
    duplicate['plans'][1]['main_action'] = duplicate['plans'][0]['main_action']
    assert validate_result(community, duplicate)


def test_batch_reads_legacy_rows_and_day_20_boundary(store):
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as s:
        channel = s.get(Channel, 'channel-a')
        channel.default_language = 'en'
        channel.created_at = datetime(2026, 10, 31, 18)
        peer = Channel(id='peer', youtube_channel_id='UC-peer', original_name='Legacy', default_language='en', created_at=datetime(2026, 11, 1, 3), status='active')
        other = Channel(id='other', youtube_channel_id='UC-other', original_name='Different batch', default_language='en', created_at=datetime(2026, 10, 31, 1), status='active')
        other_language = Channel(id='other-language', youtube_channel_id='UC-other-language', original_name='另一语种',
                                 default_language='fr', created_at=datetime(2026, 11, 1, 3), status='active')
        s.add_all([peer, other, other_language])
        for ch, day in ((peer, 1), (peer, 20), (peer, 21), (other, 19), (other_language, 18)):
            stamp = datetime(2026, 11, day, 10)
            s.add(ChannelScheduleEntry(channel_id=ch.id, drama_id='drama-a', publish_slot_id=f'legacy-{day}',
                publish_date=stamp.date(), planned_local_time=stamp, planned_utc_time=stamp,
                planned_beijing_time=stamp, source_type='manual', idempotency_key=f'legacy-{day}', status='planned'))
        s.commit()
        first, last, conflicts = schedule_batch.reservations(s, channel.id,
            {'language': 'en', 'registered_on': '2026-11-01', 'first_publish_on': '2026-11-20'})
        assert (first, last) == (date(2026, 11, 1), date(2026, 11, 20))
        assert {row['beijing_date'] for row in conflicts} == {'2026-11-01', '2026-11-20'}
        with pytest.raises(ConflictError, match='同批同语'):
            schedule_batch.guard_manual(s, channel, 'drama-a', datetime(2026, 11, 20, 23))
        schedule_batch.guard_manual(s, channel, 'drama-a', datetime(2026, 11, 21, 1))


def test_market_reconciliation_removes_ghosts_keeps_mainland_and_downgrades_grounded_angles():
    youtube = 'https://www.youtube.com/watch?v=abcdefghijk'
    mainland = 'https://www.douyin.com/video/123'
    excerpt = '她决定离开并亲自拿回公司'
    def cited(ref, url, title):
        return {'market_video_id': ref, 'video_url': url, 'video_title': title,
            'fact_verification': {'status': 'passed'}, 'eligible_for_angles': True,
            'source_type': 'external_youtube'}
    def angle(*refs):
        return {'source_type': 'external_market_verified', 'market_evidence_refs': list(refs),
                'plot_evidence': excerpt}
    result = {'external_evidence': {'status': 'partial', 'videos': [
        {'video_url': youtube, 'video_title': '真实题名', 'views': 9},
        {'video_url': mainland, 'video_title': '已搜到大陆原题'},
    ]}, 'market_payload': {
        'market_videos': [cited('real', 'https://youtu.be/abcdefghijk', '被改写的题名'),
                          cited('mainland', mainland, '已搜到大陆原题'),
                          cited('fake', mainland, '不存在的标题')],
        'angle_candidates': [angle('real', 'fake'), angle('mainland'), angle('fake')],
        'final_angles': [angle('fake')],
    }}
    assert not reconcile_revision6_evidence(result, {'results': [{'plot_fields': {'剧情档案': excerpt + '。'}}]})
    market = result['market_payload']
    assert market['verified_market_angle_count'] == 2
    assert market['market_videos'][0]['video_title'] == '真实题名'
    assert market['market_videos'][1]['source_type'] == 'external_mainland'
    assert market['angle_candidates'][0]['market_evidence_refs'] == ['real']
    assert market['final_angles'][0]['source_type'] == 'story_derived'
    assert result['market_evidence_audit']['discarded_market_video_ids'] == ['fake']


def test_concurrent_confirmations_against_mysql():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine, event
    from zhiju.models import ChannelAnalysisReport, ChannelAnalysisRun, ChannelDnaVersion, ChannelSchedulePlan
    from zhiju.services import schedule_planning

    url = os.getenv('ZHJ_R3_TEST_MYSQL')
    if not url:
        pytest.skip('set ZHJ_R3_TEST_MYSQL to an empty, migrated disposable MySQL database')
    engine = create_engine(url)
    # This scratch database uses fixture IDs. The production transaction and row
    # lock still run against real InnoDB tables and separate connections.
    @event.listens_for(engine, 'connect')
    def fixture_foreign_keys(connection, record):
        with connection.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
    tenant = 'test-concurrent'
    def session():
        return TenantSession(engine, info={'tenant_id': tenant})
    with session() as s:
        s.add(V14Setting(payload={'host_id': 'device-a', 'default_model': 'model', 'account_profile': 'current'}))
        s.add(Drama(id='drama-race', drama_number=15, drama_code='DR-race', chinese_title='反击',
                    normalized_title='反击', content_summary='女主遭到背叛后夺回公司。'))
        s.add(DramaProductionState(drama_id='drama-race', production_completion_status='completed',
                                   finished_languages=['en'], total_duration_seconds=5100))
        for key in ('race-a', 'race-b'):
            s.add(Channel(id=key, youtube_channel_id='UC-' + key, original_name=key, default_language='en',
                          created_at=datetime(2026, 11, 1), timezone='Asia/Shanghai', status='active'))
            s.add(ChannelPublishSlot(id='slot-' + key, channel_id=key, slot_type='main', slot_number=1,
                                     local_time=time(9), timezone='Asia/Shanghai', status='active'))
            s.add(ChannelAnalysisReport(id='report-' + key, channel_id=key, version_number=1,
                                        report_type='initial', status='completed'))
            s.add(ChannelDnaVersion(id='dna-' + key, channel_id=key, version_number=1, language='en',
                                   status='active', primary_genre='复仇', analysis_report_id='report-' + key))
            s.add(ChannelAnalysisRun(id='analysis-' + key, channel_id=key, host_id='device-a', mode='initial',
                status='applied', dna_id='dna-' + key, report_id='report-' + key, input_snapshot={},
                result={'operating_reference': {'topics': {'primary': ['夺回公司'], 'secondary': ['重建生活']}}}))
            s.add(ChannelPlaylist(id='playlist-' + key, channel_id=key, local_name='列表', status='active',
                youtube_playlist_id='PL' + key, url='https://www.youtube.com/playlist?list=PL' + key))
        s.commit()
        install_rule(s, skill_catalog.SCHEDULING, 'channel-scheduling', zip_rule('references/qa.md', 'QA'), 3)
        ids = []
        for key in ('race-a', 'race-b'):
            slot = schedule_planning.cadence_slots(s, key, 1)[0]['id']
            day = date(2026, 11, 9)
            plan = schedule_planning.create_plan(s, key, day, day, 1, {slot: 'primary'})
            assert not plan.input_snapshot['batch_blocked']
            plan.result = {'rows': [{'publish_date': day.isoformat(), 'publish_slot_id': slot, 'drama_id': 'drama-race',
                'reason': '实际主线', 'pairing_reason': '符合主档', 'plot_evidence': '女主遭到背叛后夺回公司。',
                'target_theme': 'primary', 'target_direction': '夺回公司', 'actual_theme': 'primary',
                'actual_direction': '夺回公司', 'theme_basis': '夺回公司', 'match_level': 'strong',
                'deviates_from_target': False, 'fallback_reason': None, 'playlist_id': 'playlist-' + key,
                'operating_reference_version_id': 'dna-' + key}]}
            plan.status = 'ready'
            ids.append(plan.id)
            s.commit()
    gate = Barrier(2)
    def confirm(plan_id):
        with session() as s:
            gate.wait(timeout=10)
            try:
                return schedule_planning.apply_plan(s, plan_id).status
            except ConflictError as exc:
                assert '同批同语' in str(exc)
                return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(confirm, ids)) == ['applied', 'blocked']
    with session() as s:
        assert len(s.scalars(select(ChannelScheduleEntry)).all()) == 1
        assert sorted(s.scalars(select(ChannelSchedulePlan.status)).all()) == ['applied', 'ready']
    engine.dispose()


@pytest.mark.parametrize('scenario', ['fresh', 'cached', 'date-limited', 'invalid-evidence', 'invalid-playlist'])
def test_r3_uses_compliant_stock_when_direction_is_invalid_or_dates_limit_stock(tmp_path, scenario):
    from zhiju.scheduling_rules.contract import validate_result

    topics = {'primary': ['女主夺回公司'], 'secondary': ['职场重建']}
    plot = '她找到真实凭证并揭穿骗局。'
    candidates = [
        {'id': key, 'chinese_title': key, 'duration_seconds': duration,
         'expires_at': None, 'finished_languages': ['fr'], 'content_summary': plot}
        for key, duration in [('strong', 3600), ('long_fallback', 7200), ('short_fallback', 5400)]
    ]
    snapshot = {
        'model': 'test',
        'skill_version': {'files': {'SKILL.md': '按生效资料评估主线'}},
        'operating_reference': {'dna_id': 'dna', 'sections': {
            'topics': topics, 'empathy': {}, 'selection_guidance': {},
        }},
        'analysis_topics': topics,
        'playlists': [{'id': 'playlist'}],
        'slots': [{'id': 'main', 'timezone': 'Europe/Paris', 'local_time': '18:00', 'slot_type': 'main'}],
        'slot_topics': {'main': 'primary'},
        'batch_blocked': [],
        'candidates': candidates,
        'date_basis': 'beijing',
        'targets': [{'publish_date': day, 'publish_slot_id': 'main'} for day in ('2026-11-10', '2026-11-11')],
    }
    rows = [
        {'drama_id': row['id'], 'actual_theme': 'primary', 'actual_direction': '查明公司骗局',
         'reason': '依据主线', 'plot_evidence': plot, 'playlist_id': 'playlist'}
        for row in candidates
    ]
    if scenario == 'cached':
        rows[0]['strong_directions'] = ['女主夺回公司']
        rows[1]['strong_directions'] = ['职场重建', '女主反击夺回了公司']
        rows[2]['strong_directions'] = []
        (tmp_path / 'reference-assessment-0.json').write_text(json.dumps({'rows': rows}))
    else:
        rows[0]['strong_direction_ids'] = ['secondary:1', 'primary:1']
        rows[1]['strong_direction_ids'] = ['secondary:1', 'primary:99']
        rows[2]['strong_direction_ids'] = []
        if scenario in ('invalid-evidence', 'invalid-playlist'):
            rows[1].update(plot_evidence='这一段在剧库里不存在', actual_direction='', reason='',
                           strong_direction_ids=['primary:1'])
            rows[2]['actual_theme'] = 'neither'
            if scenario == 'invalid-playlist':
                rows[1]['playlist_id'] = 'foreign-playlist'
        if scenario == 'date-limited':
            rows[1]['strong_direction_ids'] = ['primary:1']
            candidates[0]['expires_at'] = '2026-11-10T12:00:00+00:00'
            snapshot['batch_blocked'] = [{'drama_id': 'short_fallback', 'beijing_date': '2026-11-11'}]

    def judge(stage, model):
        assert scenario != 'cached', 'validated cached candidates should be reused'
        assert 'primary:1' in stage.prompt and 'secondary:1' in stage.prompt
        assert 'strong_direction_ids' in stage.schema['properties']['rows']['items']['properties']
        if '仅补评下列候选' in stage.prompt:
            requested = json.loads(stage.prompt.rsplit('\n候选：', 1)[1])
            assert [row['id'] for row in requested] == ['long_fallback']
            return {'rows': [rows[1]]}
        return {'rows': rows}

    result = generate(SimpleNamespace(generate=judge), {'input_snapshot': snapshot}, tmp_path)
    planned = validate_result(snapshot, result)['rows']
    if scenario == 'invalid-evidence':
        assert planned[1]['actual_theme'] == 'neither'
    expected_level = 'strong' if scenario == 'date-limited' else 'fallback'
    assert [(row['drama_id'], row['match_level']) for row in planned] == [
        ('strong', 'strong'),
        ('short_fallback' if scenario == 'invalid-playlist' else 'long_fallback', expected_level),
    ]
    assert planned[0]['theme_basis'] == planned[0]['target_direction'] == topics['primary'][0]
    assert planned[1]['deviates_from_target'] is (expected_level == 'fallback')
    assert planned[1]['theme_basis'] == (None if expected_level == 'fallback' else topics['primary'][0])
    assert planned[1]['playlist_id'] == 'playlist' and planned[1]['plot_evidence'] == plot


def test_r3_prefers_match_then_chinese_original_then_duration():
    from zhiju.v14_executor.schedule_planning import reference_rows

    cases = [
        ('long-en-ordinary', 'en', 8400, 'primary', []),
        ('short-zh-ordinary', 'zh', 2400, 'primary', []),
        ('long-en-strong', 'en', 9000, 'primary', ['反击']),
        ('long-zh-ordinary', 'zh', 3600, 'primary', []),
        ('short-en-ordinary', 'en', 5400, 'primary', []),
        ('unknown', None, 7200, 'primary', []),
        ('zh-fallback', 'zh', 12000, 'secondary', []),
    ]
    slots = [{'id': 'main', 'timezone': 'Asia/Shanghai', 'local_time': '10:00', 'slot_type': 'main'}]
    candidates = [
        {'id': key, 'source_language': language, 'finished_languages': ['zh'],
         'duration_seconds': duration, 'expires_at': None}
        for key, language, duration, _, _ in cases
    ]
    snapshot = {
        'candidates': candidates, 'playlists': [{'id': 'playlist'}],
        'analysis_topics': {'primary': ['反击'], 'secondary': ['重建']},
        'slots': slots, 'slot_topics': {'main': 'primary'}, 'batch_blocked': [],
        'operating_reference': {'dna_id': 'dna'}, 'date_basis': 'beijing',
        'targets': [{'publish_date': f'2026-11-{day}', 'publish_slot_id': 'main'} for day in range(10, 17)],
    }
    assessments = [
        {'drama_id': key, 'actual_theme': theme, 'strong_directions': directions,
         'actual_direction': '查明公司骗局', 'reason': '依据主线',
         'plot_evidence': '她找到真实凭证并揭穿骗局。', 'playlist_id': 'playlist'}
        for key, _, _, theme, directions in cases
    ]
    result = reference_rows(snapshot, assessments)
    assert [row['drama_id'] for row in result['rows']] == [
        'long-en-strong', 'long-zh-ordinary', 'short-zh-ordinary',
        'long-en-ordinary', 'unknown', 'short-en-ordinary', 'zh-fallback',
    ]


def test_r3_reserves_ordinary_secondary_match_before_primary_fallback():
    from zhiju.v14_executor.schedule_planning import reference_rows

    slots = [
        {'id': key, 'timezone': 'Asia/Shanghai', 'local_time': clock, 'slot_type': key}
        for key, clock in [('main', '10:00'), ('aux', '18:00')]
    ]
    snapshot = {
        'candidates': [{'id': 'secondary', 'duration_seconds': 4200, 'expires_at': None}],
        'playlists': [{'id': 'playlist'}], 'analysis_topics': {'primary': ['反击'], 'secondary': ['重建']},
        'slots': slots, 'slot_topics': {'main': 'primary', 'aux': 'secondary'}, 'batch_blocked': [],
        'operating_reference': {'dna_id': 'dna'}, 'date_basis': 'beijing',
        'targets': [{'publish_date': '2026-11-10', 'publish_slot_id': key} for key in ('main', 'aux')],
    }
    result = reference_rows(snapshot, [
        {'drama_id': 'secondary', 'actual_theme': 'secondary', 'strong_directions': [],
         'actual_direction': '职场重建', 'reason': '依据主线',
         'plot_evidence': '她重新找到一份工作。', 'playlist_id': 'playlist'},
    ])
    assert [(row['publish_slot_id'], row['drama_id']) for row in result['rows']] == [
        ('main', None), ('aux', 'secondary'),
    ]


def test_r3_repairs_only_missing_and_conflicting_rows_and_reuses_checkpoint(tmp_path):
    from zhiju.v14_executor.schedule_planning import complete_assessment_batch

    plot = '她拿到原始合同，最终夺回公司。'
    candidates = [{'id': name, 'content_summary': plot} for name in ('valid', 'missing', 'duplicate', 'bad-playlist')]

    def row(name, playlist='playlist', **kwargs):
        return {'drama_id': name, 'plot_evidence': plot, 'playlist_id': playlist,
                'actual_direction': '夺回公司', 'reason': '有合同依据', 'actual_theme': 'primary',
                'strong_direction_ids': ['primary:1']} | kwargs

    accepted = row('valid')
    calls = []

    def judge(stage, _):
        requested = [item['id'] for item in json.loads(stage.prompt.rsplit('\n候选：', 1)[1])]
        calls.append(requested)
        if len(calls) == 1:
            return {'rows': [accepted, accepted.copy(), row('foreign'), row('bad-playlist', 'other'),
                             row('duplicate'), row('duplicate', reason='不同结论')]}
        return {'rows': [row('missing'), row('duplicate', plot_evidence='无真实引文', reason=''),
                         row('bad-playlist', 'other')]}

    checkpoint = tmp_path / 'batch.json'
    model = SimpleNamespace(generate=judge)
    repaired = complete_assessment_batch(model, 'test', '规则', candidates, {'playlist'}, checkpoint)
    assert calls == [['valid', 'missing', 'duplicate', 'bad-playlist'], ['missing', 'duplicate', 'bad-playlist']]
    assert repaired[0] == accepted
    assert [item['drama_id'] for item in repaired] == ['valid', 'missing', 'duplicate']
    assert repaired[2]['actual_theme'] == 'neither'
    assert repaired[2]['strong_direction_ids'] == []
    assert repaired[2]['plot_evidence'] == plot
    assert complete_assessment_batch(model, 'test', '规则', candidates, {'playlist'}, checkpoint) == repaired
    assert len(calls) == 2
