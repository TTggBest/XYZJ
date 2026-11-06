"""Public-title creation must survive the subsequent metadata/visual fill."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from zhiju.v14_executor.codex import CodexClient


def stage(two_phase=True):
    rules={'execution':{'reasoning_effort':'medium'}}
    if two_phase:
        rules['title_creation']={
            'prompt':'create public titles from verified facts',
            'schema':{'type':'object'},
            'execution':{'reasoning_effort':'high'},
            'placeholder':'__PUBLIC_TITLE_CREATION__',
        }
    return SimpleNamespace(node_type='title',prompt='fill metadata: __PUBLIC_TITLE_CREATION__',
        schema={'type':'object'},rules=rules,skill_bundle=None,context={},images=[])


def creation():
    return {'directions':[{'selected_candidate_id':cid,'title':'Public '+cid,
        'translation':'中文 '+cid} for cid in ('C1','C2','C3')]}


def metadata():
    return {'section':'title','results':[{'directions':[
        {'selected_candidate_id':cid,'title':'Public '+cid,'translation':'Changed',
         'char_count':999,'hook_a_fact':'source fact '+cid} for cid in ('C3','C1','C2')],
        'direct_titles':['unwanted text']} ]}


class RecordingClient(CodexClient):
    def __init__(self,responses):
        super().__init__();self.responses=iter(responses);self.calls=[]
    def _generate_once(self,current,model):
        self.calls.append(deepcopy(current))
        return deepcopy(next(self.responses))


def test_title_creation_is_separate_from_metadata_and_public_words_are_locked(monkeypatch):
    monkeypatch.setattr('zhiju.v14_executor.codex.subprocess.Popen',lambda *a,**k:pytest.fail('Unexpected real CLI call'))
    client=RecordingClient([creation(),metadata()]);current=stage();frozen=deepcopy(current)
    result=client.generate(current,'same-model')
    assert len(client.calls)==2
    assert client.calls[0].prompt=='create public titles from verified facts'
    assert client.calls[0].rules['execution']['reasoning_effort']=='high'
    assert json.dumps(creation(),ensure_ascii=False) in client.calls[1].prompt
    assert client.calls[1].rules['execution']['reasoning_effort']=='medium'
    expected={r['selected_candidate_id']:r for r in creation()['directions']}
    rows=result['results'][0]['directions']
    for row in rows:
        first=expected[row['selected_candidate_id']]
        assert (row['title'],row['translation'],row['char_count'])==(first['title'],first['translation'],len(first['title']))
        assert row['hook_a_fact']=='source fact '+row['selected_candidate_id']
    assert result['results'][0]['direct_titles']==[r['title'] for r in rows]
    assert current.__dict__==frozen.__dict__
    assert [r['phase'] for r in client.phase_trace]==['title_creation','title_metadata']


def test_old_bundles_keep_a_single_model_call(monkeypatch):
    monkeypatch.setattr('zhiju.v14_executor.codex.subprocess.Popen',lambda *a,**k:pytest.fail('Unexpected real CLI call'))
    client=RecordingClient([{'unchanged':'result'}]);current=stage(False)
    assert client.generate(current,'same-model')=={'unchanged':'result'}
    assert len(client.calls)==1
    assert client.phase_trace==[]


def test_metadata_cannot_change_the_selected_candidate_set(monkeypatch):
    monkeypatch.setattr('zhiju.v14_executor.codex.subprocess.Popen',lambda *a,**k:pytest.fail('Unexpected real CLI call'))
    altered=metadata();altered['results'][0]['directions'][0]['selected_candidate_id']='C9'
    with pytest.raises(RuntimeError,match='候选'):
        RecordingClient([creation(),altered]).generate(stage(),'same-model')


def test_record_only_retry_uses_the_existing_public_creation(monkeypatch):
    monkeypatch.setattr('zhiju.v14_executor.codex.subprocess.Popen',lambda *a,**k:pytest.fail('Unexpected real CLI call'))
    current=stage();current.rules['title_creation']['locked']=creation()
    client=RecordingClient([metadata()]);result=client.generate(current,'same-model')
    assert len(client.calls)==1
    assert {r['title'] for r in result['results'][0]['directions']}=={r['title'] for r in creation()['directions']}


def test_duplicate_creation_candidates_stop_before_metadata(monkeypatch):
    monkeypatch.setattr('zhiju.v14_executor.codex.subprocess.Popen',lambda *a,**k:pytest.fail('Unexpected real CLI call'))
    duplicate=creation();duplicate['directions'][2]['selected_candidate_id']='C1'
    client=RecordingClient([duplicate])
    with pytest.raises(RuntimeError,match='三个不同'):
        client.generate(stage(),'same-model')
    assert len(client.calls)==1
