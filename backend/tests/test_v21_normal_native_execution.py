"""Normal new-task execution must not depend on sample-script corrections."""
from contextlib import contextmanager
import os
from pathlib import Path

import pytest

from test_v14_contract import envelope
from zhiju.v14_executor.codex import CodexClient
from zhiju.v14_executor.thumbnail_creator import PLUGIN_ID, SKILL_NAMES, ThumbnailCreator
from zhiju.v14_runtime.contract import build_stage_input, validate_result
from zhiju.workflow_bundles import snapshot


def test_native_v21_r3_accepts_french_words_with_spaced_punctuation(monkeypatch):
    archive = Path(os.environ.get('ZHJ_V21_R3_ARCHIVE',
        Path(__file__).resolve().parents[4] / 'outputs/交接/运营包-V21-r3/V21-修订3-封面场景-Skill草稿.zip'))
    if not archive.is_file():
        pytest.skip('Set ZHJ_V21_R3_ARCHIVE to the V21 r3 package')
    run = envelope(count=0)
    run['rules_snapshot']['skill_bundle'] = snapshot(
        archive.read_bytes(), version_id='new-r3', label='V21', revision=3)
    run['input_snapshot']['drama']['source_language'] = 'zh'
    run['accepted_results']['title'] = {'results': [{'directions': [
        {'title': t, 'index': i} for i, t in enumerate(('First', 'Second', 'Third'), 1)]}]}
    stage = build_stage_input(run, 'cover')
    words = ('SANS TALENT ?', 'PAS MOI !', 'JE PARS !')
    proposals = []

    class Native:
        skills = []

        def new_thread(self, model, *, use_plugin):
            return len(proposals) + 1

        def run(self, thread, prompt, schema, *, use_plugin):
            if use_plugin and schema['required'] == ['score']:
                return {'score': 9.8}
            if use_plugin:
                if len(proposals) == 3:
                    pytest.fail('Punctuation triggered unnecessary concept regeneration')
                proposals.append(thread)
                return {'concept': 'A concrete title conflict', 'core_words': words[thread - 1]}
            return {'section': 'cover', 'results': [{'titles': [
                {'title_index': i, 'prompt_16_9': (
                    f'16:9. {stage.context["casting"]} Overlay text: "{word}". '
                    f'{stage.context["overlay_position"]} {stage.context["exclusion_sentence"]}')}
                for i, word in enumerate(words, 1)]}]}

    @contextmanager
    def open_native(*args):
        yield Native()

    monkeypatch.setattr(ThumbnailCreator, 'open', open_native)
    result = CodexClient().generate(stage, 'configured-model')
    assert proposals == [1, 2, 3]
    assert [r['core_words'] for r in result['results'][0]['titles']] == list(words)
    assert validate_result(stage, result) == []


def test_enabled_plugin_can_read_ready_skills_after_a_reload_gap(tmp_path):
    root = tmp_path / 'youtube-thumbnail-creator' / '1.0.1'
    skills = []
    for name in SKILL_NAMES:
        path = root / 'skills' / name.split(':')[1] / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text('# Installed original plugin')
        skills.append({'name': name, 'path': str(path), 'enabled': True})
    calls = []

    class Discovery(ThumbnailCreator):
        def __init__(self):
            self.root = str(tmp_path)

        def _send(self, value):
            pass

        def _request(self, method, params):
            if method == 'initialize':
                return {}
            if method == 'plugin/list':
                return {'marketplaces': [{'plugins': [{'id': PLUGIN_ID, 'installed': True,
                    'enabled': True, 'version': '1.0.1', 'name': 'youtube-thumbnail-creator'}]}]}
            assert method == 'skills/list'
            calls.append(params['forceReload'])
            return {'data': [{'skills': [] if params['forceReload'] else skills}]}

    creator = Discovery()
    creator._initialize()
    assert calls == [True, False]
    assert {s['name'] for s in creator.skills} == set(SKILL_NAMES)
