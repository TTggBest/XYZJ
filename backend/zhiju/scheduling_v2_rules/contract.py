"""V2-only decision contract, shared by cloud and local executor."""
from datetime import date, datetime, timezone

from zhiju.scheduling_rules.contract import slot_local_datetime, utc

METHOD = 'audience-sequence-v2'
PROTOCOL = 16
PROMISE_STATES = {'hypothesis', 'supported', 'contradicted', 'insufficient'}
PERFORMANCE_STATES = {'untested', 'insufficient_exposure', 'supported',
                      'weak_with_evidence', 'packaging_issue', 'unknown'}


def validate_result(snapshot, result):
    from zhiju.scheduling_rules.contract import validate_result as validate_common
    saved = validate_common(snapshot, result)
    saved['planning_review'] = result.get('planning_review')
    validate_sequence(snapshot, saved)
    return saved


def validate_profile(snapshot, review):
    expected = {row['id'] for row in snapshot['candidates']}
    try:
        ordered = [key for tier in review['tiers'] for key in tier]
        ids = [row['drama_id'] for row in review['comparisons']]
        if len(ordered) != len(expected) or set(ordered) != expected or len(ids) != len(expected) or set(ids) != expected:
            raise ValueError('v2全库比较须完整覆盖每部候选，不能遗漏、重复或使用池外ID')
        for row in review['comparisons']:
            if (not isinstance(row['focus_match'], bool) or row['performance_state'] not in PERFORMANCE_STATES
                    or not row['evidence_basis'].strip() or not row['reason'].strip()):
                raise ValueError('v2候选须区分细分匹配与本频道市场证据，并说明依据')
        for theme in set(snapshot['slot_topics'].values()):
            if not review['viewer_promises'][theme].strip() or review['promise_status'][theme] not in PROMISE_STATES:
                raise ValueError('v2缺少逐题材细分观看承诺及证据状态')
        if not all(review[key].strip() for key in ('evidence_review', 'feedback_review', 'packaging_review')):
            raise ValueError('v2缺少表现、反馈或媒体核验边界说明')
        if not review['next_actions'] or not all(isinstance(action, str) and action.strip() for action in review['next_actions']):
            raise ValueError('v2缺少下一轮验证动作')
        if not snapshot.get('selection_evidence', {}).get('collected_at'):
            raise ValueError('v2尚未冻结本频道表现，不能假装已读取')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('v2全库比较结果格式不完整') from exc


def ordered_targets(snapshot):
    slots = {row['id']: row for row in snapshot['slots']}
    return sorted(snapshot['targets'], key=lambda target: slot_local_datetime(
        date.fromisoformat(target['publish_date']), slots[target['publish_slot_id']],
        snapshot.get('date_basis')).astimezone(timezone.utc))


def choices(snapshot, review, target, used):
    """Only strong candidates in the user's chosen topic, valid at this slot."""
    assessments = {row['drama_id']: row for row in review['assessments']}
    comparisons = {row['drama_id']: row for row in review['comparisons']}
    slots = {row['id']: row for row in snapshot['slots']}
    topic = snapshot['slot_topics'][target['publish_slot_id']]
    instant = slot_local_datetime(date.fromisoformat(target['publish_date']),
        slots[target['publish_slot_id']], snapshot.get('date_basis')).astimezone(timezone.utc)
    result = set()
    for drama in snapshot['candidates']:
        key = drama['id']; judgment = assessments[key]
        if key in used or judgment['actual_theme'] != topic or not comparisons[key]['focus_match']:
            continue
        if not any(direction in snapshot['analysis_topics'][topic] for direction in judgment['strong_directions']):
            continue
        duration = drama['duration_seconds']
        if duration is not None and duration < 1800:
            continue
        if drama['expires_at'] and utc(datetime.fromisoformat(drama['expires_at'])) <= instant:
            continue
        result.add(key)
    return result


def validate_sequence(snapshot, result):
    review = result.get('planning_review')
    if not isinstance(review, dict):
        raise ValueError('v2缺少全库比较与反馈复盘')
    validate_profile(snapshot, review)
    expected = {row['id'] for row in snapshot['candidates']}
    try:
        ids = [row['drama_id'] for row in review['assessments']]
        if len(ids) != len(expected) or set(ids) != expected:
            raise ValueError('v2原剧情评估没有覆盖全部候选')
        used = set(); previous = None
        all_selected = {row['drama_id'] for row in result['rows'] if row['drama_id']}
        rows = {(row['publish_date'], row['publish_slot_id']): row for row in result['rows']}
        for target in ordered_targets(snapshot):
            row = rows[(target['publish_date'], target['publish_slot_id'])]
            available = choices(snapshot, review, target, used)
            key = row['drama_id']
            if key is None:
                if available - all_selected:
                    raise ValueError('v2仍有未使用的有效强主题候选，不能无依据留空')
                continue
            if key not in available or row['match_level'] != 'strong':
                raise ValueError('v2强主题不足须留缺口，不能用宽泛相关或副题材补位')
            if row['predecessor_drama_id'] != previous:
                raise ValueError('v2前后承接关系必须指向实际前一个非空档位')
            others = available - {key}
            alternative = row['alternative_drama_id']
            if (others and alternative not in others) or (not others and alternative is not None):
                raise ValueError('v2须比较本档尚可用的同方向替代候选；没有时才留空')
            topic = snapshot['slot_topics'][target['publish_slot_id']]
            if row['selection_focus'] != review['viewer_promises'][topic]:
                raise ValueError('v2同一题材档位须强化本次同一细分观看需求')
            if row['media_verification'] != 'unverified':
                raise ValueError('v2没有媒体实物审阅结果，不能标记已验证')
            if not all(row[field].strip() for field in ('comparison_reason', 'packaging_promise', 'opening_check')):
                raise ValueError('v2缺少逐档取舍、真实包装承诺或开场待查点')
            used.add(key); previous = key
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('v2序列结果格式不完整') from exc
