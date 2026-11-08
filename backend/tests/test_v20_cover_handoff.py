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


def test_native_thumbnail_retries_then_renders_only_the_locked_concepts(monkeypatch):
    from contextlib import contextmanager
    from zhiju.v14_executor.thumbnail_creator import ThumbnailCreator
    from zhiju.v14_executor.runner import apply_content_recovery

    current = stage()
    current.prompt = 'Write both prompts from the locked concept and exact overlay.'
    current.rules['cover_concepts']['native_plugin'] = True
    apply_content_recovery(current, {'retry_state': [
        {'node_type': 'cover', 'outcome': 'content_error', 'result': {'source_anchor': 'private retry data'},
         'error': 'private validation context'},
    ]}, 'cover')
    threads, calls = [], []
    words = ('No Deal', 'You Lied', 'Fired')

    class Native:
        skills = [{'type': 'skill', 'name': 'youtube-thumbnail-creator:concepts', 'path': '/installed/concepts/SKILL.md'}]

        def new_thread(self, model, *, use_plugin):
            threads.append(use_plugin)
            return len(threads)

        def run(self, thread, prompt, schema, *, use_plugin):
            calls.append((thread, prompt, use_plugin))
            assert 'private' not in prompt
            if use_plugin:
                assert 'rationale' in schema['required']
                return {'concept': f'Concept {thread}', 'core_words': words[thread - 1],
                        'rationale': f'Why {thread}', 'score': 8.8 if len(calls) == 1 else 9.5}
            return {'section': 'cover', 'results': [{'titles': [
                {'title_index': i, 'prompt_4_5': f'4:5 overlay "{word}"', 'prompt_16_9': f'16:9 overlay "{word}"'}
                for i, word in enumerate(words, 1)
            ]}]}

    @contextmanager
    def open_native(*_args):
        yield Native()

    monkeypatch.setattr(ThumbnailCreator, 'open', open_native)
    decisions = iter([['cover_1_prompt_16_9_core_words_diegetic_placement'], []])
    monkeypatch.setattr('zhiju.v14_executor.codex.validate_result', lambda *_: next(decisions))
    client = CodexClient()
    result = client.generate(current, 'model')
    assert threads == [True, True, True, False]
    assert [thread for thread, _, _ in calls] == [1, 1, 2, 3, 4, 4]
    assert '8.8' in calls[1][1]
    for pos, title in zip((0, 2, 3), current.rules['cover_concepts']['titles']):
        assert json.loads(calls[pos][1].split('\n\n')[-1]) == {'title': title, 'language': 'English'}
    handed_off = json.loads(calls[-2][1].splitlines()[-1])
    assert 'diegetic_placement' in calls[-1][1]
    assert [item['score'] for item in handed_off] == [9.5, 9.5, 9.5]
    assert [row['thumbnail_creator']['rationale'] for row in result['results'][0]['titles']] == ['Why 1', 'Why 2', 'Why 3']
    assert client.phase_trace[0]['raw']['score'] == 8.8


def test_native_thumbnail_keeps_low_score_out_of_renderer_when_time_expires(monkeypatch):
    from contextlib import contextmanager
    from zhiju.v14_executor.thumbnail_creator import ThumbnailCreator

    current = stage()
    current.rules['cover_concepts']['native_plugin'] = True
    calls = []

    class Native:
        skills = []

        def new_thread(self, model, *, use_plugin):
            assert use_plugin
            return 'title'

        def run(self, thread, prompt, schema, *, use_plugin):
            calls.append(use_plugin)
            if len(calls) == 2:
                raise TimeoutError('deadline')
            return {'concept': 'Weak', 'core_words': 'No Deal', 'rationale': 'Honest review', 'score': 8.8}

    @contextmanager
    def open_native(*_args):
        yield Native()

    monkeypatch.setattr(ThumbnailCreator, 'open', open_native)
    with pytest.raises(CoverContentError, match='8.8'):
        CodexClient().generate(current, 'model')
    assert calls == [True, True]
