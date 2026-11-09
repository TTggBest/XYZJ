import os
from pathlib import Path
from copy import deepcopy

import pytest
from sqlalchemy import select

from test_v14_api import client, store
from test_v14_contract import envelope
from test_v18_title_two_phase import RecordingClient, creation, metadata
from zhiju.database import TenantSession
from zhiju.models import Drama, DramaAlias, PackageTitle
from zhiju.models.v14 import WorkflowSkillVersion
from zhiju.v14_runtime.contract import build_stage_input, validate_result
from zhiju.v14_runtime import canonical, market
from zhiju.workflow_bundles import executor_protocol, snapshot


EVENTS = ('他赶走了女主，董事会随即撤走了公司的资金。', '丈夫拒绝签字，女主当庭签了离婚协议。',
          '家宴上父亲给妹妹股份，给女主空信封。')


@pytest.fixture
def archive():
    default = (Path(__file__).resolve().parents[4] / 'outputs/交接/运营包-V20-r7'
               / 'V20-修订7-Skill草稿.zip')
    path = Path(os.environ.get('ZHJ_V20_R7_ARCHIVE', default))
    if not path.is_file():
        pytest.skip('需要 V20 修订 7 归档，可通过 ZHJ_V20_R7_ARCHIVE 指定')
    return path.read_bytes()


@pytest.fixture
def archive_r8():
    default = (Path(__file__).resolve().parents[4] / 'outputs/交接/运营包-V20-r8'
               / 'V20-修订8-Skill草稿.zip')
    path = Path(os.environ.get('ZHJ_V20_R8_ARCHIVE', default))
    if not path.is_file():
        pytest.skip('需要 V20 修订 8 归档，可通过 ZHJ_V20_R8_ARCHIVE 指定')
    return path.read_bytes()


def story_hooks():
    return [{'candidate_id': f'C{i}', 'core_conflict': event, 'hook_a_fact': event,
             'hook_b_fact': event, 'visual_moment': event, 'plot_evidence': event}
            for i, event in enumerate(EVENTS, 1)]


@pytest.mark.parametrize('titles', [[], ['An actual reference title']])
def test_find_hands_raw_titles_and_independent_story_facts_to_title(titles, archive):
    run = envelope(count=0)
    run['rules_snapshot']['skill_bundle'] = snapshot(
        archive, version_id='r7', label='V20', revision=7)
    run['input_snapshot']['channel']['title_template'] = '🔥 A! B!'
    run['input_snapshot']['drama']['plot_archive'] = ''.join(EVENTS)
    run['external_evidence'] = {'titles': titles}
    assert executor_protocol(run['rules_snapshot']) == 11
    find = build_stage_input(run, 'search')
    assert set(find.schema['properties']) == {'story_hooks'}
    assert not any(title in find.prompt for title in titles)
    hooks = story_hooks()
    result = {'plot_payload': find.context['plot_payload'], 'market_payload': {'story_hooks': hooks},
              'external_evidence': {'titles': titles}}
    bad = {**result, 'external_evidence': {'titles': titles, 'views': 123}}
    assert validate_result(find, bad)
    invented = {**result, 'market_payload': {'story_hooks': [
        {**hooks[0], 'plot_evidence': '剧情里没有这一句'}, *hooks[1:]]}}
    assert validate_result(find, invented)
    duplicate = {**result, 'market_payload': {'story_hooks': [
        hooks[0], {**hooks[0], 'candidate_id': 'C2'}, hooks[2]]}}
    assert validate_result(find, duplicate)
    assert not validate_result(find, result)
    run['accepted_results']['search'] = result
    title = build_stage_input(run, 'title')
    assert title.context['market_packaging']['external_titles'] == titles
    prompt = title.rules['title_creation']['prompt']
    assert all(event in prompt for event in EVENTS)
    assert all(title in prompt for title in titles)
    assert '由 Title 比较原标题并提炼' in prompt
    assert 'market_videos' not in prompt

    filled = metadata()
    for row in filled['results'][0]['directions']:
        row.update(index=1, recommendation_score=99)
    directions = RecordingClient([creation(), filled]).generate(title, 'same-model')['results'][0]['directions']
    assert [(r['selected_candidate_id'], r['index'], r['recommendation_score']) for r in directions] == [
        ('C1', 1, 3), ('C2', 2, 2), ('C3', 3, 1)]


@pytest.mark.parametrize('revision,external_titles', [(7, ['Raw overseas title']), (8, []), (8, ['Raw overseas title'])])
def test_work_order_accepts_find_and_persists_fixed_titles(client, store, request, revision, external_titles):
    archive = request.getfixturevalue('archive_r8' if revision == 8 else 'archive')
    protocol = 12 if revision == 8 else 11
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        drama = session.get(Drama, 'drama-a')
        drama.source_language = 'zh'
        drama.plot_archive = ''.join(EVENTS)
        session.add(DramaAlias(tenant_id='tenant-a', drama_id=drama.id, alias='旧名', normalized_alias='旧名'))
        session.add(WorkflowSkillVersion(id=f'v20-r{revision}', tenant_id='tenant-a', label='V20',
                                        revision=revision, status='published', archive=archive))
        session.commit()
    client.post('/api/v3/work-orders/work-a/v14-runs',
                json={'workflow_version_id': f'v20-r{revision}'}).raise_for_status()
    outdated = client.post('/api/v3/v14/claims', json={'host_id': 'device-a', 'executor_protocol': protocol - 1})
    assert outdated.status_code == 409 and '请更新本机执行器' in outdated.json()['detail']
    claim = client.post('/api/v3/v14/claims', json={
        'host_id': 'device-a', 'executor_protocol': protocol}).raise_for_status().json()
    url = f"/api/v3/v14/runs/{claim['run_id']}/attempts"
    claim_body = {'claim_id': claim['claim_id']}

    def begin(node):
        attempt = client.post(url, json={**claim_body, 'node_type': node,
                                         'executor_protocol': protocol}).raise_for_status().json()['attempt_id']
        path = f'{url}/{attempt}'
        stage = client.post(path + '/input', json=claim_body).raise_for_status().json()
        return path, stage

    path, find = begin('search')
    assert find['item']['drama_aliases'] == ['旧名']
    found = {'plot_payload': find['context']['plot_payload'], 'external_evidence': {'titles': external_titles}}
    if revision == 7:
        found['market_payload'] = {'story_hooks': story_hooks()}
    client.put(path, json={**claim_body, 'outcome': 'accepted', 'result': found}).raise_for_status()

    path, title = begin('title')
    prompt = title['rules']['title_creation']['prompt']
    assert all(t in prompt for t in external_titles)
    if revision == 8:
        assert 'packaging_candidates' not in prompt
        assert all(event in prompt for event in EVENTS)
    identity = {key: found['plot_payload']['results'][0][key] for key in canonical.IDENTITY_PROPERTIES}
    brief = dict.fromkeys(('core_story_promise', 'audience_emotion', 'information_gap', 'title_role',
                           'thumbnail_role', 'truth_constraints', 'avoid_repetition'), '女主反击争取公平待遇')
    brief.update(creative_slot_id=claim['run_id'], channel_direction='复仇')
    public = ('🔥 They dismissed me... The board withdrew its funding!',
              '🔥 He refused to sign... I signed the divorce in court!',
              '🔥 My sister got shares... I got an empty envelope!')
    translations = ('🔥 他赶走我... 董事会撤资了！', '🔥 他拒绝签字... 我当庭签字离婚！',
                    '🔥 妹妹拿到股份... 我收到空信封！')
    payoff = ('董事会撤资', '当庭签字离婚', '我收到空信封')
    directions = []
    for index, (hook, public_title, translation, ending) in enumerate(zip(story_hooks(), public, translations, payoff), 1):
        event = hook['plot_evidence']
        directions.append({
            'index': index, 'recommendation_score': 4 - index, 'direction': '复仇反击',
            'title': public_title, 'translation': translation, 'char_count': len(public_title),
            'hook_a_type': 'betrayal', 'hook_b_type': 'power_reversal',
            'hook_a_fact': event, 'hook_b_fact': event, 'hook_a_evidence': event, 'hook_b_evidence': event,
            'specificity_anchor': event, 'public_payoff_anchor': ending, 'visual_thesis': f'画面显示这一真实事件：{event}',
            'child_angle': False, 'safe_cover_scene': '', 'child_role': '',
            'selected_candidate_id': hook['candidate_id'], 'selected_variant_id': 'independent',
            'selection_reason': '已比较开场事实与观看理由', 'title_detail_realization': [],
            'conflict_promise': dict.fromkeys(('relationship', 'emotional_opposition', 'decisive_interaction'), event),
            'cover_core_words': 'My Choice', 'cover_core_words_translation': '我的选择',
            'visual_conflict': dict.fromkeys(('opponent_action', 'protagonist_action', 'emotional_contrast',
                                             'visual_focus'), event),
            'cover_options': [{'option_id': str(i), 'visible_moment': event, 'relational_cue': '成人明确对峙',
                               'core_words': 'My Choice', 'core_words_translation': '我的选择'} for i in (1, 2)]})
    result = {'section': 'titles', 'results': [{
        **identity, 'packaging_brief': brief,
        'direct_titles': list(public), 'directions': directions, 'rejected_candidates': []}]}
    repeated = deepcopy(result)
    opening_copy = '🔥 They dismissed me... I signed the divorce in court!'
    repeated['results'][0]['directions'][1]['title'] = opening_copy
    repeated['results'][0]['direct_titles'][1] = opening_copy
    rejected = client.put(path, json={**claim_body, 'outcome': 'accepted', 'result': repeated})
    assert rejected.status_code == 409 and 'opening_repeats_title_1' in rejected.json()['detail']
    response = client.put(path, json={**claim_body, 'outcome': 'accepted', 'result': result})
    assert response.status_code == 200, response.text
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        saved = session.scalars(select(PackageTitle).where(PackageTitle.package_id == claim['package_id'])
                                .order_by(PackageTitle.variant_number)).all()
        assert [(row.variant_number, row.localized_title) for row in saved] == list(enumerate(public, 1))


@pytest.mark.parametrize('youtube_titles,mainland_titles', [
    (['Raw title — unchanged!'], []), ([], ['大陆页面原标题']), ([], []),
])
def test_external_find_returns_only_titles_and_uses_mainland_only_on_empty(monkeypatch, youtube_titles, mainland_titles):
    def youtube(*args, **kwargs):
        return {'videos': [{'video_title': title, 'description': 'private metadata'} for title in youtube_titles]}

    def mainland(query):
        assert not youtube_titles
        return [{'video_title': title, 'video_url': 'https://douyin.com/fixture'} for title in mainland_titles], ''

    monkeypatch.setattr(market, 'collect_agent_reach_evidence', youtube)
    monkeypatch.setattr(market, '_mainland_search', mainland)
    result = market.collect_revision7_titles({'drama_name': '剧目', 'language': '法语', 'direction': '复仇'})
    assert result == {'titles': youtube_titles or mainland_titles}


def test_revision8_search_stops_at_first_usable_query(monkeypatch):
    calls = []

    def youtube(item, *, query, include_details):
        calls.append(query)
        assert not include_details
        return {'videos': [] if len(calls) == 1 else [{'video_title': 'An original title!'}]}

    monkeypatch.setattr(market, 'collect_agent_reach_evidence', youtube)
    assert market.collect_revision8_titles({'drama_name': '剧目', 'language': '法语', 'direction': '复仇',
                                           'drama_aliases': ['剧目', '别名一', '别名二']}) == {
                                               'titles': ['An original title!']}
    assert calls == ['剧目 法语', '别名一 法语']


def test_revision8_search_retry_reuses_result_and_skips_model(tmp_path):
    from zhiju.v14_executor.client import CloudConflict
    from zhiju.v14_executor.runner import run_once

    queries, submissions = [], []

    class Cloud:
        def claim(self):
            return {'run_id': 'r', 'work_order_id': 'w', 'claim_id': 'c', 'account_profile': 'current',
                    'model': 'fixed', 'staged_inputs': True, 'node_sequence': ['search'],
                    'rules_snapshot': {'skill_bundle': {'label': 'V20', 'revision': 8}}}

        def begin(self, envelope, node):
            return node

        def stage_input(self, envelope, attempt, evidence=None):
            return {'node_type': 'search', 'prompt': '', 'schema': {}, 'item': {'drama_name': '剧名'},
                    'context': {'plot_payload': {'raw': '原文'}}, 'rules': {}}

        def submit(self, envelope, attempt, body):
            submissions.append(deepcopy(body))
            if len(submissions) == 1:
                raise CloudConflict('V14 验收失败: test retry')
            return {'status': 'running'}

    class Model:
        account_profile = 'current'

        def generate(self, stage, model):
            pytest.fail('Find should not call the model')

    def search(item):
        queries.append(item)
        return {'titles': []}

    assert run_once(Cloud(), Model(), cache_root=tmp_path, evidence_provider=search, recover=False)
    assert len(queries) == 1
    assert [b['outcome'] for b in submissions] == ['accepted', 'content_error', 'accepted']
    assert submissions[-1]['result'] == {'plot_payload': {'raw': '原文'}, 'external_evidence': {'titles': []}}


def test_revision8_cover_requires_video_interface_exclusions_on_both_aspects(archive_r8):
    run = envelope(count=0)
    run['rules_snapshot']['skill_bundle'] = snapshot(archive_r8, version_id='r8', label='V20', revision=8)
    run['input_snapshot']['drama']['source_language'] = 'zh'
    run['accepted_results']['title'] = {'results': [{'directions': [
        {'title': title, 'index': index} for index, title in enumerate(('One', 'Two', 'Three'), 1)]}]}
    cover = build_stage_input(run, 'cover')
    exclusion = cover.context['exclusion_sentence']
    assert exclusion in cover.prompt
    rows = []
    for index, (title, word) in enumerate(zip(('One', 'Two', 'Three'), ('Deal', 'Loss', 'Choice')), 1):
        row = {'title_index': index, 'title': title, 'core_words': word,
               'thumbnail_creator': {'concept': 'An adult woman confronts a business partner.',
                                     'core_words': word, 'rationale': 'Visible reaction', 'score': 9.5}}
        for field, ratio in (('prompt_4_5', '4:5'), ('prompt_16_9', '16:9')):
            row[field] = f'{ratio}. {cover.context["casting"]} Overlay text: "{word}". {exclusion}'
        rows.append(row)
    output = {'section': 'cover', 'results': [{'titles': rows}]}
    assert not validate_result(cover, deepcopy(output))
    rows[0]['prompt_4_5'] = rows[0]['prompt_4_5'].replace(exclusion, '')
    rows[2]['prompt_16_9'] = rows[2]['prompt_16_9'].replace(exclusion, '')
    assert validate_result(cover, output) == [
        'cover_1_prompt_4_5_video_interface_exclusion_missing',
        'cover_3_prompt_16_9_video_interface_exclusion_missing',
    ]
