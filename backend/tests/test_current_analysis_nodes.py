"""Exercise actual archived V21 node preparation plus the host's final prompt wiring."""
from copy import deepcopy
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import json
import os
import pytest
from test_v14_contract import envelope
from test_v14_api import client, store
from zhiju.v14_runtime.contract import build_stage_input
from zhiju.workflow_bundles import snapshot, executor_protocol

CASES = [
    ('en','孩子主动寻找生父的亲缘归位','母亲保留了亲缘证据，孩子主动找到父亲，一家人在法庭相认。','zh'),
    ('fr','女性取证夺回职业成果','同事冒领设计奖，女主公开原始草稿，主办方纠正署名并取消冒领者资格。','en'),
    # Held out from the two conflict examples used to derive the fix.
    ('id','兄弟照护中的责任重建','哥哥把家产交给弟弟照顾父亲，弟弟将父亲送走，哥哥回来亲自承担照护。','zh'),
]


def candidate():
    project = Path(__file__).resolve().parents[4]
    source = Path(os.getenv('ZHJ_CONTEXT_SOURCE_ARCHIVE',project/'outputs/交接/运营包-V21-r4/V21-修订4-女主封面服装遮盖-Skill草稿.zip'))
    if not source.is_file(): pytest.skip('Provide the reviewed V21 r4 archive')
    spec=spec_from_file_location('current_bundle_builder',Path(__file__).resolve().parents[2]/'scripts/build_current_analysis_bundle.py')
    module=module_from_spec(spec);spec.loader.exec_module(module)
    return module.build(source.read_bytes())


def sample(case):
    language,direction,plot,source_language=case
    data=envelope()
    data['run_id']='9f438d86-a9d4-4ce6-9b7e-6318b0afe53f'
    sections={key:{'status':'cold_start_hypothesis','evidence':['confirmed initial hypothesis'], 'conclusion':direction+' '+key}
              for key in ('positioning','topics','empathy','reusable_patterns','title','cover','selection_guidance','validation')}
    sections['positioning']['conclusion']=direction
    sections['topics'].update(primary=[direction],secondary=[],boundary='only when the actual plot supports this relationship',counterexamples=['unrelated billionaire rescue'])
    data['input_snapshot']['channel'].update(language=language,direction=direction,
        title_template='🔥 A! B!',guidance_contract='current-analysis-v1',operating_reference={
            'channel_id':'c1','run_id':'applied-b','report_id':'report-b','dna_id':'dna-b','mode':'initial','sections':sections})
    data['input_snapshot']['drama'].update(content_summary=plot,plot_archive=plot,plot_pattern='真实人物主动行动',core_personas='剧情中的人物',source_language=source_language)
    data['accepted_results']['search']={'market_payload':{'external_titles':[],'story_hooks':[]}}
    data['accepted_results']['title']={'results':[{'packaging_brief':{},'directions':[
        {'title':f'Locked distinct reason {i}','translation':f'不同的事实{i}','selected_candidate_id':f'C{i}'} for i in (1,2,3)]}]}
    data['accepted_results']['cover']={'results':[{'titles':[]}]}
    data['accepted_results']['community_scene']={'section':'community_scene','plans':[{'source_anchor':plot,'main_action':'真实人物行动'}]}
    return data,sections


@pytest.mark.parametrize('case',CASES,ids=['family-en','career-fr','heldout-care-id'])
def test_actual_nodes_receive_same_current_source_and_appropriate_sections(case):
    data,sections=sample(case)
    data['rules_snapshot']={'skill_bundle':snapshot(candidate(),version_id='candidate',label='V21',revision=5)}
    first=build_stage_input(data,'search')
    data['accepted_results']['search']['plot_payload'] = first.context['plot_payload']
    original=deepcopy(data)
    stages={node:build_stage_input(data,node) for node in ('search','title','cover','description','community_scene','community')}
    assert data==original
    assert executor_protocol(data['rules_snapshot'])==17
    for node,stage in stages.items():
        guidance=stage.context['applied_channel_guidance']
        assert guidance['run_id']=='applied-b'
        for key in ('positioning','topics','empathy','selection_guidance','validation'):
            assert guidance['sections'][key]==sections[key]
        assert sections['topics']['boundary'] in stage.prompt
    title=stages['title']
    creation=title.rules['title_creation']['prompt']
    assert sections['topics']['primary'][0] in creation
    assert sections['empathy']['conclusion'] in creation
    assert sections['cover']['conclusion'] not in creation
    assert 'must contain at least one accepted_theme_signal' not in title.prompt
    assert '封面专用秘密' not in creation
    assert '封面专用秘密' in stages['cover'].prompt
    assert '封面专用秘密' not in str(stages['cover'].rules['cover_concepts'])
    assert 'opaque' in stages['cover'].prompt.lower()
    assert stages['community_scene'].rules['native_community']['emotion']==sections['empathy']['conclusion']
    for node in ('description','community'):
        assert stages[node].context['channel_theme_contract']['source']=='current_applied_analysis'
        assert stages[node].context['channel_theme_contract']['required_output_signals']==[]
    if directory:=os.getenv('ZHJ_CONTEXT_EVIDENCE'):
        target=Path(directory);target.mkdir(parents=True,exist_ok=True)
        (target/(case[0]+'-nodes.json')).write_text(json.dumps({'case':case,'reference':data['input_snapshot']['channel']['operating_reference'],
            'stages':{key:{'prompt':stage.prompt,'rules':stage.rules,'context':stage.context} for key,stage in stages.items()}},ensure_ascii=False,indent=2))


def test_public_new_package_freezes_current_analysis_and_requires_capable_executor(client,store):
    from sqlalchemy import select
    from zhiju.database import TenantSession
    from zhiju.models import Drama
    from zhiju.models.v14 import WorkflowSkillVersion,V14Run
    from test_current_analysis_context import setup,analysis
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        setup(s)
        current=analysis(s,'与旧复仇无关的照护责任')
        current_id=current.id
        s.get(Drama,'drama-a').source_language='zh'
        s.add(WorkflowSkillVersion(id='context-candidate',label='V21',revision=5,status='published',
            change_summary='isolated candidate',archive=candidate()))
        s.commit()
    response=client.post('/api/v3/tasks/task-a/start-v14',json={'workflow_version_id':'context-candidate'})
    assert response.status_code==200,response.text
    run_id=response.json()['run_id']
    old=client.post('/api/v3/v14/claims',json={'host_id':'device-a','executor_protocol':16})
    assert old.status_code==409
    response=client.post('/api/v3/v14/claims',json={'host_id':'device-a','executor_protocol':17})
    assert response.status_code==200,response.text
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        run=s.get(V14Run,run_id)
        assert run.input_snapshot['channel']['operating_reference']['run_id']==current_id
        assert run.input_snapshot['channel']['direction']=='与旧复仇无关的照护责任-positioning'
        stage=build_stage_input({'run_id':run.id,'rules_snapshot':run.rules_snapshot,'input_snapshot':run.input_snapshot},'search')
        assert stage.context['applied_channel_guidance']['run_id']==current_id
