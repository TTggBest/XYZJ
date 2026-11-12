"""The V2 skill is selectable independently and plans an evidenced sequence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_schedule_continuity import snapshot
from test_schedule_planning import data


def test_v2_catalog_keeps_v1_default_and_both_archives_available(data):
    from zhiju.services import skill_catalog
    s, *_ = data
    rows = skill_catalog.versions(s, skill_catalog.SCHEDULING)
    v2 = next(row for row in rows if row['label'] == 'channel-scheduling-v2')
    assert v2['status'] == 'published'
    assert skill_catalog.default_id(s, skill_catalog.SCHEDULING) == skill_catalog.SCHEDULING_VERSION
    old = skill_catalog.files(skill_catalog.archive(s, skill_catalog.SCHEDULING, skill_catalog.SCHEDULING_VERSION))
    new = skill_catalog.files(skill_catalog.archive(s, skill_catalog.SCHEDULING, v2['id']))
    assert old != new
    assert 'SKILL.md' in new and 'references/execution-contract.md' in new
    assert 'name: channel-scheduling\n' in old['SKILL.md']


def test_v2_upload_bundle_contains_the_same_rules_as_system_catalog(data, tmp_path):
    import importlib.util
    from pathlib import Path
    from zhiju.services import skill_catalog
    script = Path(__file__).resolve().parents[2] / 'scripts/build_scheduling_v2_skill_bundle.py'
    spec = importlib.util.spec_from_file_location('build_scheduling_v2', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    exported = module.build(tmp_path / 'channel-scheduling-v2.zip').read_bytes()
    s, *_ = data
    served = skill_catalog.archive(s, skill_catalog.SCHEDULING, skill_catalog.SCHEDULING_V2_VERSION)
    assert skill_catalog.files(exported) == skill_catalog.files(served)
    assert all('__pycache__' not in name for name in skill_catalog.files(exported))


def v2_snapshot():
    snap = snapshot()
    snap['channel'] = {'id': 'channel', 'default_language': 'en', 'original_name': '测试频道'}
    snap['selection_method'] = 'audience-sequence-v2'
    snap['skill_version']['files'] = {'SKILL.md': '逐档比较，强主题不足留空，不强制跨频道去重。'}
    snap['targets'] += [{**snap['targets'][0], 'publish_date': '2026-11-14'}]
    return snap


def profile():
    return {
        'viewer_promises': {'primary': '丈夫夺产→妻子取证→公开夺回公司', 'secondary': ''},
        'promise_status': {'primary': 'hypothesis', 'secondary': 'hypothesis'},
        'evidence_review': 'winner有消费，但展示和来源缺失，尚不能断言此机制得到重复验证。',
        'feedback_review': '旧假设需用后续多部新片验证，不能由一次峰值推出成功。',
        'packaging_review': '没有封面、开场和音频实物；下面的包装建议不是已核验结果。',
        'tiers': [['exact', 'peer'], ['broad']],
        'comparisons': [
            {'drama_id': key, 'focus_match': key != 'broad',
             'performance_state': 'untested', 'evidence_basis': '本频道没有该候选的发布表现，不能当成失败。',
             'reason': 'exact和peer持续围绕妻子取证夺产；broad仅与宽泛逆袭相关。'}
            for key in ('broad', 'exact', 'peer')],
        'next_actions': ['取得展示、来源与开场数据后再判断包装或选片，不自动修改已发布视频。'],
    }


def sequence(snap):
    return {'rows': [
        {**target, 'drama_id': key, 'reason': '妻子主动取证夺产为持续主线',
         'plot_evidence': snap['candidates'][0]['content_summary'],
         'pairing_reason': '保持背叛、主动取证与公开夺回的观看期待，变化具体冲突。',
         'predecessor_drama_id': previous, 'alternative_drama_id': alternative,
         'comparison_reason': '与另一部相比，本档优先兑现取证夺回的冲突，并衔接前档。',
         'packaging_promise': '丈夫偷走公司，她带合同回来夺回所有权。',
         'opening_check': '待检查成片是否直接建立夺产冲突，不能以简介代替观看。'}
        for target, key, previous, alternative in zip(
            snap['targets'], ('exact', 'peer'), (None, 'exact'), ('peer', None))]}


def model_for_v2(snap, chosen, prompts):
    def generate(stage, model):
        prompts.append(stage.prompt)
        if 'viewer_promises' in stage.schema['properties']:
            return deepcopy(profile())
        if 'predecessor_drama_id' in stage.schema['properties']['rows']['items']['properties']:
            return deepcopy(chosen)
        return {'rows': [{'drama_id': row['id'], 'actual_theme': 'primary',
            'actual_direction': '妻子主动取证夺产', 'strong_direction_ids': ['primary:1'],
            'playlist_id': 'playlist', 'reason': '实际主线依据', 'plot_evidence': row['content_summary']}
            for row in snap['candidates']]}
    return SimpleNamespace(generate=generate)


def test_v2_generates_sequence_not_duration_sort_and_keeps_all_candidate_comparisons(tmp_path):
    from zhiju.v14_executor.schedule_planning import generate
    from zhiju.scheduling_v2_rules.contract import validate_result
    snap = v2_snapshot(); prompts = []
    result = generate(model_for_v2(snap, sequence(snap), prompts), {'input_snapshot': snap}, tmp_path)
    assert [row['drama_id'] for row in result['rows']] == ['exact', 'peer']
    assert result['rows'][1]['predecessor_drama_id'] == 'exact'
    assert all(row['media_verification'] == 'unverified' for row in result['rows'])
    assert len(result['planning_review']['comparisons']) == 3
    assert result['planning_review']['missing_evidence'] == snap['selection_evidence']['missing']
    saved = validate_result(snap, result)
    assert saved['planning_review']['next_actions']
    assert saved['rows'][0]['alternative_drama_id'] == 'peer'
    assert any('winner' in prompt for prompt in prompts)
    again = generate(SimpleNamespace(generate=lambda *args: pytest.fail('must reuse validated frozen checkpoints')),
                     {'input_snapshot': snap}, tmp_path)
    assert again == result


@pytest.mark.parametrize('problem', ['broad_fill', 'broken_sequence', 'missing_alternative', 'fake_media'])
def test_v2_cloud_rejects_wrong_focus_or_unreviewed_output(tmp_path, problem):
    from zhiju.v14_executor.schedule_planning import generate
    from zhiju.scheduling_v2_rules.contract import validate_result
    snap = v2_snapshot()
    result = generate(model_for_v2(snap, sequence(snap), []), {'input_snapshot': snap}, tmp_path)
    if problem == 'broad_fill': result['rows'][0]['drama_id'] = 'broad'
    if problem == 'broken_sequence': result['rows'][1]['predecessor_drama_id'] = None
    if problem == 'missing_alternative': result['rows'][0]['alternative_drama_id'] = None
    if problem == 'fake_media': result['rows'][0]['media_verification'] = 'verified'
    with pytest.raises(ValueError):
        validate_result(snap, result)


def test_v2_strong_shortage_stays_gap_and_does_not_use_long_broad_drama(tmp_path):
    from zhiju.v14_executor.schedule_planning import generate
    snap = v2_snapshot()
    snap['targets'].append({**snap['targets'][0], 'publish_date': '2026-11-15'})
    chosen = sequence({**snap, 'targets': snap['targets'][:2]})
    chosen['rows'].append({**snap['targets'][2], 'drama_id': None, 'reason': '强主题库存不足',
        'plot_evidence': '', 'pairing_reason': '', 'predecessor_drama_id': 'peer',
        'alternative_drama_id': None, 'comparison_reason': '', 'packaging_promise': '', 'opening_check': ''})
    result = generate(model_for_v2(snap, chosen, []), {'input_snapshot': snap}, tmp_path)
    assert result['rows'][-1]['drama_id'] is None
    assert result['rows'][-1]['status'] == 'blocked'


@pytest.mark.parametrize('duration', [None, 1800])
def test_v2_keeps_unknown_and_exactly_30_minute_strong_candidates(tmp_path, duration):
    from zhiju.v14_executor.schedule_planning import generate
    snap = v2_snapshot()
    snap['candidates'][1]['duration_seconds'] = duration
    result = generate(model_for_v2(snap, sequence(snap), []), {'input_snapshot': snap}, tmp_path)
    assert result['rows'][0]['drama_id'] == 'exact'
    assert result['rows'][0]['duration_seconds'] == duration
    if duration is None:
        assert result['rows'][0]['warnings'] == ['时长未验证']


def test_v2_does_not_silently_omit_an_unreviewed_candidate(tmp_path):
    from zhiju.v14_executor.schedule_planning import generate
    snap = v2_snapshot()
    real_model = model_for_v2(snap, sequence(snap), [])
    def incomplete(stage, model):
        value = real_model.generate(stage, model)
        if 'viewer_promises' in value:
            value['comparisons'].pop()
        return value
    with pytest.raises(ValueError, match='全库比较'):
        generate(SimpleNamespace(generate=incomplete), {'input_snapshot': snap}, tmp_path)


def test_v2_new_protocol_does_not_change_old_claims(data):
    from sqlalchemy import select
    from zhiju.models import ChannelSchedulePlan
    from zhiju.services.schedule_planning import claimable_plans
    s, channel, *_ = data
    for key, method in [('v1', None), ('r4', 'audience-continuity-v1'), ('v2', 'audience-sequence-v2')]:
        s.add(ChannelSchedulePlan(id=key, channel_id=channel.id, host_id='host',
            input_snapshot={'selection_method': method}))
    s.commit()
    query = select(ChannelSchedulePlan.id)
    assert set(s.scalars(claimable_plans(query, 14))) == {'v1', 'r4'}
    assert set(s.scalars(claimable_plans(query, 15))) == {'v1', 'r4'}
    assert set(s.scalars(claimable_plans(query, 16))) == {'v1', 'r4', 'v2'}


def test_v2_prepare_keeps_worker_idle_and_reports_required_protocol(tmp_path,monkeypatch):
    import subprocess,sys
    from zhiju.v14_executor.launcher import WorkerManager
    from zhiju.v14_executor.client import CloudClient
    from zhiju.scheduling_v2_rules.contract import PROTOCOL
    manager=WorkerManager({'origin':'https://fixture.example','host_id':'host','tenant_id':'tenant',
        'account_profile':'current','runtime_root':str(tmp_path),'python':sys.executable,
        'codex_binary':'/fixed/codex','log_path':str(tmp_path/'worker.log')})
    monkeypatch.setattr(CloudClient,'request',lambda *args,**kwargs:{'tenant_id':'tenant','device':{'id':'host'}})
    monkeypatch.setattr(subprocess,'run',lambda args,**kwargs:subprocess.CompletedProcess(args,0))
    result=manager.prepare({'base_url':'https://fixture.example','host_id':'host','tenant_id':'tenant',
        'account_profile':'current','session_token':'fixture-only','task_type':'channel_scheduling'})
    assert result['ready'] and result['executor_protocol']==PROTOCOL==16
    assert result['running'] is False and manager.process is None
    manager.close()
