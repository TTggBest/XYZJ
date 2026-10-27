"""V14 Skills' Zhiju data adapter, shipped INSIDE the versioned archive.

Original Skill files are not edited. Paths point to this archive's sibling
Skills. Only prepare/validate/evidence are called, never Feishu batch entrypoints.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'xy-pack-v14/scripts'),
                str(ROOT / 'xy-batch-v14/scripts')]
import deterministic_batch as batch
import canonical_outputs as c
import market_packaging as market

batch.SKILLS_ROOT = ROOT
batch.SIMULATED_SKILLS = {k: ROOT / p.relative_to(p.parents[2]) for k, p in batch.SIMULATED_SKILLS.items()}
batch.MACHINE_RULE_PATHS = {k: ROOT / p.relative_to(p.parents[2]) for k, p in batch.MACHINE_RULE_PATHS.items()}
batch.CHANNEL_HASHTAG_WHITELISTS_PATH = ROOT / 'xy-place-v14/rules/channel_hashtag_whitelists.json'

NODES = {'search': 'xy-find', 'title': 'xy-title', 'cover': 'xy-cover',
         'description': 'xy-place', 'community': 'xy-post'}
PLOT = {'内容概述': 'content_summary', '剧情档案': 'plot_archive',
        '剧情套路': 'plot_pattern', '核心人设': 'core_personas'}


def prepare(envelope, node):
    data, accepted = envelope['input_snapshot'], envelope.get('accepted_results', {})
    channel = data['channel']
    batch.title_channel_context(channel.get('generation_spec', ''))
    if not channel.get('description_fixed_assets', {}).get('subscribe_line'):
        raise ValueError('description_fixed_assets 缺少 subscribe_line')
    if not channel.get('playlists') or any(not p.get('name') or not p.get('url') for p in channel['playlists']):
        raise ValueError('缺少完整 playlist 材料')
    whitelist = channel.get('channel_hashtag_whitelist', {})
    if not whitelist.get('additional_candidates') or not whitelist.get('target_language_tags'):
        raise ValueError('缺少 channel_hashtag_whitelist 材料')
    if data['community_count']:
        for key in ('full_video_cta', 'subscribe_cta', 'share_cta', 'layout_style'):
            if not channel.get('community_footer_cta', {}).get(key):
                raise ValueError('community_footer_cta 缺少 ' + key)
    for key in PLOT.values():
        if not data['drama'].get(key):
            raise ValueError('缺少剧情字段: ' + key)
    item = {'drama_name': data['drama_name'], 'video_id': data.get('video_id') or 'pending_' + envelope['run_id'],
        'url': data.get('video_url') or '', 'channel': data['channel_name'],
        'language': channel['language'], 'gender': channel['gender'], 'direction': channel['direction'],
        'slot': data['target_publish_date'], 'workflow_contract_version': 2, 'community_output_version': 2,
        'community_count': data['community_count'], 'need_community': data['community_count'] > 0}
    plot = {'section': 'search', 'results': [{'plot_fields': {k: data['drama'][v] for k, v in PLOT.items()}}]}
    c.normalize_identity(plot, item)
    contracts = {n: json.loads(p.read_text()) for n, p in batch.MACHINE_RULE_PATHS.items()}
    context = {'task': item, 'identity': {k: c.first_result(plot)[k] for k in c.IDENTITY_PROPERTIES},
        'plot_payload': plot, 'source_language': data['drama'].get('source_language'),
        'semantic_contract': {'version': 11, 'dynamic_channel_theme_grounding_required': True, 'fixed_localized_title_candidates': False},
        'channel_snapshot': channel['generation_spec'], 'channel_theme_contract': batch.channel_theme_contract(item, plot),
        'playlists': channel.get('playlists', []), 'creative_slot': {'creative_slot_id': envelope['run_id']},
        'description_fixed_assets': channel['description_fixed_assets'], 'description_assets_frozen': True,
        'community_footer_cta': channel.get('community_footer_cta', {}),
        'title_rule_contract': contracts['xy-title'].get('title_contract', {}),
        'cover_rule_contract': contracts['xy-cover'],
        'description_rule_contract': contracts['xy-place'].get('description_contract', {}),
        'community_rule_contract': contracts['xy-post'],
        'title_payload': accepted.get('title', {}), 'cover_payload': accepted.get('cover', {}),
        'place_payload': accepted.get('description', {}),
        'market_packaging': market.market_context_for_title(accepted.get('search', {}).get('market_payload', {})),
        'channel_hashtag_whitelist': channel.get('channel_hashtag_whitelist', {}),
        'creative_history': [], 'visual_history': []}
    grouped = {}
    for row in envelope.get('creative_history', []):
        previous = row['input_snapshot']
        h = grouped.setdefault(row['run_id'], {'channel': previous['channel_name'], 'language': previous['channel']['language'],
            'drama_name': previous['drama_name'], 'video_id': previous.get('video_id', '')})
        key = {'title': 'title_payload', 'cover': 'cover_payload', 'description': 'place_payload', 'community': 'post_payload'}.get(row['node_type'])
        if key:
            h[key] = row['payload']
        if row['node_type'] == 'cover':
            for index, cover in enumerate(c.cover_rows(row['payload']), 1):
                context['visual_history'].append({**cover, 'source_group_index': str(index),
                    'channel': previous['channel_name'], 'drama_name': previous['drama_name'], 'video_id': previous.get('video_id', '')})
    context['creative_history'] = [h for h in grouped.values() if h['drama_name'] == data['drama_name']]
    if node == 'merge':
        return {'node_type': node, 'prompt': '', 'schema': {}, 'item': item, 'context': context, 'rules': {}}
    native = NODES[node]
    schema = deepcopy(market.MARKET_PACKAGING_SCHEMA if node == 'search' else c.schema_for(native, item))
    context['output_schema'] = schema
    rules = batch.SIMULATED_SKILLS[native].read_text()
    if node == 'search':
        prompt = market.build_market_packaging_prompt(item, plot, rules, envelope.get('external_evidence'))
    else:
        issues = [] if node == 'community' and not item['community_count'] else batch.stage_preflight_issues(native, context, contracts[native])
        if issues:
            raise ValueError('; '.join(issues))
        feedback = [r['error'] for r in envelope.get('retry_state', []) if r['node_type'] == node and r.get('error')]
        prompt = batch.build_prompt(native, rules, {**context, 'visual_history': context['visual_history'][-32:]}, feedback, batch.STAGE_DIRECTIVES[native])
    instructions = '\n\n'.join((ROOT / name / 'SKILL.md').read_text() for name in ('xy-workflow-v14', 'xy-batch-v14', 'xy-pack-v14', native + '-v14'))
    return {'node_type': node, 'prompt': instructions + '\n\n' + prompt, 'schema': schema,
        'item': item, 'context': context, 'rules': {}}


def validate(stage, result):
    node, context, item = stage['node_type'], stage['context'], stage['item']
    if node == 'merge':
        return {'issues': [] if result.get('text_complete') is True else ['缺少合成完成标记'], 'result': result}
    if node == 'search':
        if result.get('plot_payload') != context['plot_payload']:
            return {'issues': ['剧情事实与智矩输入不一致'], 'result': result}
        schema_issues = c._schema_issues(result.get('market_payload', {}), stage['schema'])
        if schema_issues:
            raise ValueError('模型结构错误: ' + '; '.join(schema_issues))
        issues = market.validate_market_packaging_evidence(result.get('market_payload', {}), {
            'drama_id': item['video_id'], 'drama_title': item['drama_name'], 'channel_name': item['channel'],
            'channel_language': item['language'], 'channel_type': item['direction']})
        return {'issues': issues, 'result': result}
    native = NODES[node]
    issues = c.validate_model_output_schema(native, result, item, context)
    if issues:
        raise ValueError('模型结构错误: ' + '; '.join(issues))
    if node == 'community' and not item['community_count']:
        return {'issues': [], 'result': result}
    c.normalize_identity(result, item)
    if node == 'title':
        c.normalize_title_recommendation_order(result, context)
        c.normalize_title_translation_format(result, context)
    elif node == 'cover':
        c.normalize_cover_prompt_contract(result, context['cover_rule_contract'])
    elif node == 'description':
        c.normalize_place_fixed_footer(result, context, item)
    return {'issues': c.validate_payload(native, result, item, context, validate_schema=False), 'result': result}


if __name__ == '__main__':
    request = json.load(sys.stdin)
    if request['action'] == 'prepare':
        response = prepare(request['envelope'], request['node'])
    elif request['action'] == 'validate':
        response = validate(request['stage'], request['result'])
    elif request['action'] == 'evidence':
        response = market.collect_agent_reach_evidence(request['item'])
    else:
        raise ValueError('未知操作')
    print(json.dumps(response, ensure_ascii=False))
