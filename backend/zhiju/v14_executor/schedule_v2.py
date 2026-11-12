"""Independent V2 profile comparison and model-authored sequence planning."""
from copy import deepcopy
import json

from zhiju.scheduling_v2_rules.contract import validate_profile, validate_result


def generate_sequence(model, snapshot, judgments, root, progress=None):
    from zhiju.v14_executor.schedule_planning import CONTINUITY_SCHEMA, PLAN_SCHEMA, encode, stage

    expected = {row['id'] for row in snapshot['candidates']}
    ids = [row['drama_id'] for row in judgments]
    if len(ids) != len(expected) or set(ids) != expected:
        raise ValueError('v2未完整评估全部候选；请修复原剧情评估，未回退常用名单')
    rules = '\n'.join(value for name, value in snapshot['skill_version']['files'].items()
                      if name.endswith('.md') and value)
    plots = {row['id']: row for row in snapshot['candidates']}
    compact = [{**row, **{field: plots[row['drama_id']].get(field) for field in
                ('chinese_title', 'duration_seconds', 'expires_at')}} for row in judgments]
    profile_schema = deepcopy(CONTINUITY_SCHEMA)
    properties = profile_schema['properties']
    properties['promise_status'] = {'type': 'object', 'additionalProperties': False,
        'properties': {theme: {'type': 'string', 'enum': ['hypothesis', 'supported', 'contradicted', 'insufficient']}
                       for theme in ('primary', 'secondary')}, 'required': ['primary', 'secondary']}
    properties['next_actions'] = {'type': 'array', 'items': {'type': 'string'}}
    comparison = properties['comparisons']['items']
    comparison['properties'].update(
        performance_state={'type': 'string', 'enum': ['untested', 'insufficient_exposure', 'supported',
            'weak_with_evidence', 'packaging_issue', 'unknown']}, evidence_basis={'type': 'string'})
    comparison['required'] += ['performance_state', 'evidence_basis']
    profile_schema['required'] += ['promise_status', 'next_actions']
    prompt = (rules + '\n当前阶段：全库相对比较。使用schema中的tiers表示接近的适配层级，不是预测播放分。'
        '每个候选都必须出现；逐部解释最接近候选的区别。未发布不等于差，曝光不足不等于失败。'
        '本频道数据以实际窗口和发布年龄解释，已应用历史分析不冒称本次实时观测。'
        '\n频道：' + encode(snapshot['channel']) + '\n已应用运营参考：' + encode(snapshot['operating_reference']) +
        '\n逐档要求：' + encode(snapshot['slot_topics']) +
        '\n本频道表现与上次复盘：' + encode(snapshot.get('selection_evidence')) +
        '\n全部候选的全文评估与原文引用：' + encode(compact))
    path = root / 'v2-audience-profile.json'
    error = ''
    for attempt in range(3):
        if progress:
            progress('planning', len(judgments), len(expected), 'v2全库比较：细分需求与本频道证据')
        review = json.loads(path.read_text()) if attempt == 0 and path.exists() else model.generate(
            stage(prompt + ('\n请修复结果：' + error if error else ''), profile_schema), snapshot['model'])
        try:
            validate_profile(snapshot, review)
        except ValueError as exc:
            error = str(exc); continue
        path.write_text(encode(review))
        break
    else:
        raise ValueError('v2全库比较未通过：' + error)
    review = {**review, 'assessments': judgments, 'compared_candidates': len(expected),
        'total_candidates': len(expected), 'unassessed_candidate_ids': [],
        'evidence_collected_at': snapshot['selection_evidence']['collected_at'],
        'missing_evidence': snapshot['selection_evidence'].get('missing', []),
        'contract_version': 'audience-sequence-v2'}
    schema = deepcopy(PLAN_SCHEMA)
    fields = schema['properties']['rows']['items']
    fields['properties'].update(
        predecessor_drama_id={'type': ['string', 'null']}, alternative_drama_id={'type': ['string', 'null']},
        comparison_reason={'type': 'string'}, packaging_promise={'type': 'string'}, opening_check={'type': 'string'})
    fields['required'] = list(fields['properties'])
    prompt = (rules + '\n当前阶段：序列编排。按实际发布时间逐档选择，不能按tiers或时长直接填表。'
        '可以在接近层级内为更好的前后承接改变顺序，必须解释。'
        '使用同一细分观看承诺，强主题不足留空；不返回偏题补位。'
        'predecessor_drama_id为本次前一非空档，首档null；alternative_drama_id从该档尚未使用、'
        '同目标细分且有效的候选选，只有没有其他候选才为null。'
        '每档输出真实包装承诺及开场待查点，不声称已看媒体或可保证增长。'
        '\n全库比较：' + encode(review) + '\n全部候选的全文评估与原文引用：' + encode(compact) +
        '\n频道历史：' + encode(snapshot.get('history', [])) +
        '\n逐档要求：' + encode(snapshot['slot_topics']) + '\n档位：' + encode(snapshot['slots']) +
        '\n日期定义：' + encode(snapshot.get('date_basis')) + '\n全部待排目标：' + encode(snapshot['targets']))
    assessments = {row['drama_id']: row for row in judgments}
    error = ''
    for attempt in range(3):
        if progress:
            progress('planning', len(judgments), len(expected), f'v2逐档承接编排，第{attempt + 1}次')
        path = root / f'v2-sequence-{attempt}.json'
        result = json.loads(path.read_text()) if path.exists() else model.generate(
            stage(prompt + ('\n上次结果未通过，请修复：' + error if error else ''), schema), snapshot['model'])
        path.write_text(encode(result))
        result = deepcopy(result)
        try:
            for row in result['rows']:
                if row['drama_id'] is None:
                    continue
                judgment = assessments[row['drama_id']]
                topic = snapshot['slot_topics'][row['publish_slot_id']]
                basis = next(iter(judgment['strong_directions']), None)
                row.update(target_theme=topic, target_direction=basis,
                    actual_theme=judgment['actual_theme'], actual_direction=judgment['actual_direction'],
                    theme_basis=basis, match_level='strong', deviates_from_target=False, fallback_reason=None,
                    playlist_id=judgment['playlist_id'], operating_reference_version_id=snapshot['operating_reference']['dna_id'],
                    selection_focus=review['viewer_promises'][topic], media_verification='unverified')
            result['planning_review'] = review
            return validate_result(snapshot, result)
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
    raise ValueError('v2序列编排未通过，未回退旧版选片：' + error)
