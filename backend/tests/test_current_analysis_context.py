from copy import deepcopy
import yaml
import pytest
from sqlalchemy import select
from zhiju.database import TenantSession
from zhiju.models import Channel
from zhiju.models.v14 import V14Setting
from zhiju.services import channel_analysis, v14_runs
from test_v14_runs import store, configure
from test_channel_analysis_runs import valid_result
from test_three_module_integration import zip_rule, install_rule
from zhiju.services import skill_catalog


def analysis(s, direction, *, apply=True):
    run = channel_analysis.create_run(s, 'channel-a', mode='initial', positioning=direction)
    sample = valid_result(run)
    strategy = yaml.safe_load(sample['diagnosis'].split('```yaml\n')[1].split('```')[0])['channel_strategy']
    strategy['channel_id'] = 'UC-a'
    sections = {key: {'status': 'cold_start_hypothesis', 'evidence': ['用户确认的初始假设'], 'conclusion': direction + '-' + key}
                for key in ('positioning','topics','empathy','reusable_patterns','title','cover','selection_guidance','validation')}
    sections['topics'].update(primary=[direction], secondary=[], boundary=direction+'真实主线', counterexamples=[])
    strategy.update(operating_reference=sections, content_priority=[direction], content_secondary=[])
    sample['diagnosis'] = sample['diagnosis'].split('```yaml')[0] + '```yaml\n'+yaml.safe_dump({'channel_strategy':strategy},allow_unicode=True)+'```'
    sample['normalized_snapshot']['channel']['youtube_channel_id'] = 'UC-a'
    channel_analysis.start_run(s, run.id)
    claim = channel_analysis.claim_run(s, 'device-a')
    channel_analysis.submit_result(s, run.id, claim['claim_id'], result=sample)
    return channel_analysis.apply_result(s, run.id) if apply else run


def setup(s):
    configure(s)
    install_rule(s, skill_catalog.ANALYSIS, 'xy-yt-report-v2', zip_rule('references/output-contract.md', 'channel_strategy.operating_reference', analysis=True), 4)
    channel = s.get(Channel, 'channel-a')
    channel.default_genre = '复仇逆袭'
    channel.default_language = 'ar'
    config = s.scalar(select(V14Setting))
    payload = deepcopy(config.payload)
    payload['channel_inputs']['channel-a']['direction'] = '复仇逆袭'
    config.payload = payload
    s.commit()


def test_new_run_uses_applied_reference_instead_of_legacy_direction(store):
    with TenantSession(store, info={'tenant_id':'tenant-a'}) as s:
        setup(s)
        a = analysis(s, '关系反击')
        b = analysis(s, '亲子家庭')
        draft = analysis(s, '未应用草稿方向', apply=False)
        run = v14_runs.create_run(s, 'work-a')
        channel = run.input_snapshot['channel']
        assert channel['direction'] == '亲子家庭-positioning'
        assert channel['analysis_version']['run_id'] == b.id
        assert channel['operating_reference']['run_id'] == b.id
        assert channel['operating_reference']['sections']['topics']['primary'] == ['亲子家庭']
        assert '复仇逆袭' not in str(channel)
        assert draft.status == 'ready'
        assert a.status == 'superseded'
        assert channel['language'] == '阿拉伯语'
        assert channel['description_fixed_assets']['subscribe_line']
        frozen = deepcopy(run.input_snapshot)
        analysis(s, '下一份已应用')
        assert v14_runs.create_run(s, 'work-a').input_snapshot == frozen


def test_legacy_missing_positioning_never_uses_old_strategy(store):
    with TenantSession(store, info={'tenant_id':'tenant-a'}) as s:
        setup(s)
        setting=s.scalar(select(V14Setting))
        setting.payload={**setting.payload,'analysis_skill_version_id':'builtin-xy-yt-report-v2'}
        s.commit()
        current = analysis(s, '家庭假设')
        assert 'operating_reference' not in current.result
        run = v14_runs.create_run(s, 'work-a')
        assert run.input_snapshot['channel']['direction'] == '未知，待验证'
        assert run.input_snapshot['channel']['operating_reference']['run_id'] == current.id


def test_first_v3_import_freezes_question_led_contract_and_blocks_old_executor(store,monkeypatch):
    from zhiju.models import ChannelAnalysisRun
    from zhiju.services import channel_analysis_sources
    from zhiju.channel_analysis_rules.operating_reference import is_reference_revision,uses_selection_guidance
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        setup(s)
        content=zip_rule('references/output-contract.md','channel_strategy.operating_reference',analysis=True)
        version=skill_catalog.upload(s,skill_catalog.ANALYSIS,'xy-yt-report-v3','candidate',content)
        skill_catalog.publish(s,skill_catalog.ANALYSIS,version['id'])
        skill_catalog.select_default(s,skill_catalog.ANALYSIS,version['id'])
        assert version['revision']==1
        monkeypatch.setattr(channel_analysis_sources,'verify_authorization',lambda *args:('token',{},{}))
        run=channel_analysis.create_run(s,'channel-a',mode='periodic')
        assert run.input_snapshot['package_inquiry_contract']=='question-led-v1'
        assert run.input_snapshot['studio_input_contract']=='dual-window-v1'
        assert run.input_snapshot['studio_required_periods']==[28,7]
        skill=run.input_snapshot['operating_reference_skill']
        assert is_reference_revision(skill) and uses_selection_guidance(skill)
        query=select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.id==run.id)
        assert s.scalar(channel_analysis.claimable_runs(query,16)) is None
        assert s.scalar(channel_analysis.claimable_runs(query,17))==run.id


def test_v3_spec_derivation_does_not_refill_old_strategy():
    from zhiju.v14_executor.channel_analysis import generation_spec_stage
    run={'input_snapshot':{'channel':{'id':'c','youtube_channel_id':'UC','default_language':'fr','default_genre':'old-genre-secret'},
        'profile':{'positioning':'old-profile-position','title_template':'🔥 A! B!','fixed_symbol':'🔥'},
        'previous_analysis':{'generation_spec':'old-spec-secret'},'operating_reference_skill':{'label':'xy-yt-report-v3'}}}
    stage=generation_spec_stage(run,{'profile':'current unknown age; family hypothesis','diagnosis':'current evidence only'})
    assert 'old-genre-secret' not in stage.prompt and 'old-spec-secret' not in stage.prompt
    assert 'old-profile-position' not in stage.prompt
    assert '🔥 A! B!' in stage.prompt
