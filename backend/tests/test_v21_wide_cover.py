from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from test_v14_contract import envelope
from zhiju.v14_executor.codex import CodexClient
from zhiju.v14_executor.thumbnail_creator import ThumbnailCreator
from zhiju.v14_runtime.contract import build_stage_input, validate_result
from zhiju.workflow_bundles import executor_protocol, snapshot


def test_v21_keeps_only_qualified_hooks_and_one_landscape_per_title(monkeypatch):
    archive = Path(__file__).resolve().parents[4] / 'outputs/交接/运营包-V21/V21-Skill草稿.zip'
    run = envelope(count=0)
    run['rules_snapshot']['skill_bundle'] = snapshot(archive.read_bytes(), version_id='v21', label='V21', revision=1)
    assert executor_protocol(run['rules_snapshot']) == 13
    run['input_snapshot']['drama']['source_language'] = 'zh'
    run['accepted_results']['title'] = {'results': [{'directions': [
        {'title': title, 'index': i} for i, title in enumerate(('First', 'Second', 'Third'), 1)]}]}
    stage = build_stage_input(run, 'cover')
    words = ('First hook', 'Second hook', 'Third hook')
    scores = iter((9.5, 9.6, 9.7, 9.8))
    threads, proposals = [], []

    class Native:
        skills = []

        def new_thread(self, model, *, use_plugin):
            threads.append((model, use_plugin))
            return len(threads)

        def run(self, thread, prompt, schema, *, use_plugin):
            if use_plugin and schema['required'] == ['score']:
                return {'score': next(scores)}
            if use_plugin:
                assert set(schema['required']) == {'concept', 'core_words'}
                proposals.append(thread)
                return {'concept': 'Specific title conflict', 'core_words': words[thread - 1]}
            assert 'Thumbnail Creator handoff:' in prompt and '"score"' not in prompt
            return {'section': 'cover', 'results': [{'titles': [
                {'title_index': i, 'prompt_16_9': (
                    f'16:9. {stage.context["casting"]} Overlay text: "{word}". '
                    f'{stage.context["exclusion_sentence"]} {stage.context["overlay_position"]}')}
                for i, word in enumerate(words, 1)]}]}

    @contextmanager
    def open_native(*_args):
        yield Native()

    monkeypatch.setattr(ThumbnailCreator, 'open', open_native)
    result = CodexClient().generate(stage, 'configured-model')
    assert proposals == [1, 1, 2, 3]
    assert threads[-1] == ('gpt-6.1-sol', False)
    rows = result['results'][0]['titles']
    assert [row['thumbnail_creator']['score'] for row in rows] == [9.6, 9.7, 9.8]
    assert all('prompt_4_5' not in row for row in rows)
    invalid = deepcopy(result)
    invalid['results'][0]['titles'][0]['prompt_16_9'] = rows[0]['prompt_16_9'].replace(
        stage.context['overlay_position'], '')
    assert 'cover_1_overlay_position_missing' in validate_result(stage, invalid)
