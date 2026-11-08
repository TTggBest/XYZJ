import json

import pytest

from zhiju.v14_executor.codex import CodexClient, CoverContentError
from zhiju.v14_runtime.contract import StageInput


def stage():
    plan = {'titles': ['First title', 'Second title', 'Third title'], 'language': 'English',
            'instructions': 'Fixed creator rules', 'schema': {'type': 'object'}, 'execution': {}}
    node = StageInput('cover', 'private plot + final cover rules', {}, {'extra': 'private item'},
                      {'history': 'private history'}, {'cover_concepts': plan}, {'archive': 'private'})
    node.source_files = {'plot.txt': 'private plot'}
    return node


def test_cover_concepts_only_see_one_title_and_language_then_drive_both_descriptions(monkeypatch):
    current = stage()
    client = CodexClient()
    plans = [
        {'concept': 'Refusal', 'core_words': 'No Deal', 'score': 9.5},
        {'concept': 'Reversal', 'core_words': 'You Lied', 'score': 9.7},
        {'concept': 'Confrontation', 'core_words': 'Fired', 'score': 9.6},
    ]
    result = {'results': [{'titles': [
        {'title_index': i, 'title': title, 'core_words': plan['core_words']}
        for i, (title, plan) in enumerate(zip(current.rules['cover_concepts']['titles'], plans), 1)
    ]}]}
    calls = []

    def generate_once(request, model):
        calls.append(request)
        return plans[len(calls) - 1] if len(calls) <= 3 else result

    monkeypatch.setattr(client, '_generate_once', generate_once)
    assert client.generate(current, 'model') == result
    for call, title in zip(calls[:3], current.rules['cover_concepts']['titles']):
        assert json.loads(client.prompt_for(call).split('\n\n')[-1]) == {'title': title, 'language': 'English'}
        assert not call.skill_bundle and not call.context and not call.item and not hasattr(call, 'source_files')
    assert len(calls) == 4 and calls[3].context == current.context
    handed_off = json.loads(calls[3].prompt.splitlines()[-1])
    assert all(locked[key] == plan[key] for locked, plan in zip(handed_off, plans) for key in plan)

    result['results'][0]['titles'][1]['core_words'] = 'Changed'
    calls.clear()
    with pytest.raises(CoverContentError, match='逐组保留'):
        client.generate(current, 'model')


def test_cover_does_not_handoff_below_target(monkeypatch):
    client = CodexClient()
    calls = []

    def generate_once(request, model):
        calls.append(request)
        return {'concept': 'Weak concept', 'core_words': 'No Deal', 'score': 9}

    monkeypatch.setattr(client, '_generate_once', generate_once)
    with pytest.raises(CoverContentError, match='9.5'):
        client.generate(stage(), 'model')
    assert len(calls) == 1
