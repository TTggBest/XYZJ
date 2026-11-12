"""Bounded story assessment, AI planning and cached result delivery."""
import json
from datetime import date, timedelta
from pathlib import Path
from threading import Event, Thread, Lock
from time import monotonic
from types import SimpleNamespace
from .client import CloudConflict, EXECUTOR_PROTOCOL


def array_schema(properties):
    return {'type':'object','additionalProperties':False,'properties':{'rows':{'type':'array','items':{
        'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}}},'required':['rows']}


ASSESSMENT_SCHEMA=array_schema({'drama_id':{'type':'string'},'eligible':{'type':'boolean'},
    'main_theme':{'type':'boolean'},'reason':{'type':'string'},'plot_evidence':{'type':'string'}})
TOPIC_ASSESSMENT_FIELDS = {'drama_id': {'type': 'string'}, 'eligible': {'type': 'boolean'},
    'theme': {'type': 'string', 'enum': ['primary', 'secondary', 'neither']},
    'reason': {'type': 'string'}, 'plot_evidence': {'type': 'string'}}
TOPIC_ASSESSMENT_SCHEMA = array_schema(TOPIC_ASSESSMENT_FIELDS)
ANALYSIS_TOPIC_ASSESSMENT_SCHEMA = array_schema({**TOPIC_ASSESSMENT_FIELDS, 'theme_basis': {'type': 'string'}})
PLAN_SCHEMA=array_schema({'publish_date':{'type':'string'},'publish_slot_id':{'type':'string'},
    'drama_id':{'type':['string','null']},'reason':{'type':'string'},'plot_evidence':{'type':'string'},
    'pairing_reason':{'type':'string'}})


def stage(prompt,schema):
    if len(prompt.encode('utf-8'))>800_000:
        raise ValueError('本次频道资料或单部剧情过大，超过排期单次输入范围；请精简资料后重建规划')
    return SimpleNamespace(prompt=prompt,schema=schema,skill_bundle=None,node_type='channel_scheduling',
        rules={'execution':{'reasoning_effort':'high'}})


def encode(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


REFERENCE_ASSESSMENT_SCHEMA = array_schema({
    'drama_id': {'type': 'string'},
    'actual_theme': {'type': 'string', 'enum': ['primary', 'secondary', 'neither']},
    'actual_direction': {'type': 'string'},
    'strong_direction_ids': {'type': 'array', 'items': {'type': 'string'}},
    'playlist_id': {'type': 'string'},
    'reason': {'type': 'string'},
    'plot_evidence': {'type': 'string'},
})

CONTINUITY_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'viewer_promises': {'type': 'object', 'additionalProperties': False,
            'properties': {'primary': {'type': 'string'}, 'secondary': {'type': 'string'}},
            'required': ['primary', 'secondary']},
        'evidence_review': {'type': 'string'}, 'feedback_review': {'type': 'string'},
        'packaging_review': {'type': 'string'},
        'tiers': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'}}},
        'comparisons': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'drama_id': {'type': 'string'}, 'focus_match': {'type': 'boolean'},
                           'reason': {'type': 'string'}},
            'required': ['drama_id', 'focus_match', 'reason']}},
    },
    'required': ['viewer_promises', 'evidence_review', 'feedback_review', 'packaging_review', 'tiers', 'comparisons'],
}


def compare_audience(model, snapshot, judgments, root):
    """Relative editorial comparison of the whole assessed pool, before length ties."""
    evidence = snapshot.get('selection_evidence')
    if not isinstance(evidence, dict) or not evidence.get('collected_at'):
        raise ValueError('修订4尚未冻结本频道逐视频表现，请先读取证据')
    plots = {row['id']: row for row in snapshot['candidates']}
    compact = [{**row, **{key: plots[row['drama_id']].get(key) for key in (
        'chinese_title', 'content_summary', 'plot_pattern', 'core_personas', 'duration_seconds')}}
        for row in judgments]
    prompt = (
        '这是修订4的全候选相对比较，不是重新按宽泛标签选片。前阶段已经逐部阅读全文。'
        '先结合本频道已应用定位、逐视频真实表现、上次承接假设及目前结果，确定细分观看承诺：'
        '谁伤害谁→主角采取什么行动→最终兑现什么回报。primary与secondary分别解释；'
        '不能只写豪门、逆袭、打脸或总裁，也不能凭语言或标题套用别的频道赢家。'
        '有观测才称已验证；冷启动、缺失、过旧数据只形成待验证假设，不承诺推荐或播放增长。'
        '比较近期7天、前7天、28天时考虑曝光/发布时间、样本量、观看时长/APV与增粉，'
        '窗口互相重叠不能相加，未成熟视频不能同成熟视频直接排名，缺行不等于0。'
        'evidence_review说明哪些实际样本支持或反对方向；feedback_review审视上次假设是否被结果支持。'
        '没有逐视频展示或流量来源时不能断言下跌是选片造成。'
        'packaging_review区分已读标题、封面实图、开场留存和正片；没取得就明确未验证，不能编造核验。'
        '逐部作对照，说明为什么更适合或不如最接近的另一部，冲突/情绪/结局回报是否相近。'
        'focus_match仅表示实际持续主线吻合本次细分承诺；并不改变原来的题材归类与准入规则。'
        'tiers从最佳到较弱排列，适配质量相近的候选放同一层；系统只在同层比较原语种和时长。'
        '每个已评估ID在tiers和comparisons中都必须恰好出现一次，包括未推荐的。'
        '不用凑固定部数、不为跨频道去重牺牲适配、不照搬别的频道整表。'
        '本次逐档题材是硬约束；同一题材的两档强化同一细分观看期待；播放列表只是归档不能代替剧情匹配。'
        '\n已应用运营参考：' + encode(snapshot['operating_reference']) +
        '\n逐档题材：' + encode(snapshot['slot_topics']) +
        '\n本频道表现与上次复盘：' + encode(evidence) +
        '\n全部已评估候选：' + encode(compact))
    path = root / 'audience-comparison.json'
    expected = {row['drama_id'] for row in judgments}
    error = ''
    for attempt in range(3):
        result = json.loads(path.read_text()) if attempt == 0 and path.exists() else model.generate(
            stage(prompt + ('\n上次比较未通过：' + error if error else ''), CONTINUITY_SCHEMA), snapshot['model'])
        try:
            ordered = [key for tier in result['tiers'] for key in tier]
            compared = result['comparisons']
            ids = [row['drama_id'] for row in compared]
            if (len(ordered) != len(expected) or set(ordered) != expected
                    or len(ids) != len(expected) or set(ids) != expected):
                raise ValueError('全候选相对比较遗漏、重复或夹入了其他剧目')
            for row in compared:
                if not isinstance(row['focus_match'], bool) or not row['reason'].strip():
                    raise ValueError('逐部比较缺少细分适配判定或相对理由')
            for theme in set(snapshot['slot_topics'].values()):
                if not result['viewer_promises'][theme].strip():
                    raise ValueError('缺少该档细分观看承诺')
            if not all(result[key].strip() for key in ('evidence_review', 'feedback_review', 'packaging_review')):
                raise ValueError('缺少表现复核、上次反馈或包装证据说明')
        except (KeyError, TypeError, ValueError) as exc:
            error = str(exc)
            continue
        temporary = path.with_suffix('.tmp')
        temporary.write_text(encode(result)); temporary.replace(path)
        priorities = {key: -index for index, tier in enumerate(result['tiers']) for key in tier}
        comparisons = {row['drama_id']: row for row in compared}
        updated = [{**row, **comparisons[row['drama_id']],
                    'comparison_priority': priorities[row['drama_id']]} for row in judgments]
        review = {key: result[key] for key in (
            'viewer_promises', 'evidence_review', 'feedback_review', 'packaging_review')}
        review.update(compared_candidates=len(expected), total_candidates=len(plots),
            unassessed_candidate_ids=sorted(plots.keys() - expected),
            evidence_collected_at=evidence['collected_at'], missing_evidence=evidence.get('missing', []))
        return updated, review
    raise ValueError('修订4全候选对比未通过，未回退到按时长选片：' + error)


def reference_rows(snapshot, assessments):
    """Reserve strong candidates first, then fill remaining slots from real stock."""
    from datetime import datetime, timezone
    from zhiju.scheduling_rules.contract import BEIJING, slot_local_datetime, utc

    candidates = {row['id']: row for row in snapshot['candidates']}
    playlists = {row['id'] for row in snapshot['playlists']}
    topics = snapshot['analysis_topics']
    slots = {row['id']: row for row in snapshot['slots']}
    blocked = {(r['drama_id'], r['beijing_date']) for r in snapshot['batch_blocked']}
    reference_id = snapshot['operating_reference']['dna_id']
    targets = []
    for target in snapshot['targets']:
        slot = slots[target['publish_slot_id']]
        local = slot_local_datetime(date.fromisoformat(target['publish_date']), slot, snapshot.get('date_basis'))
        instant = local.astimezone(timezone.utc)
        beijing_day = instant.astimezone(BEIJING).date().isoformat()
        targets.append((instant, beijing_day, target))
    targets.sort(key=lambda row: (row[0], row[2]['publish_slot_id']))

    def ranked(target, beijing_day, instant):
        category = snapshot['slot_topics'][target['publish_slot_id']]
        choices = []
        for assessment in assessments:
            drama = candidates[assessment['drama_id']]
            drama_id = drama['id']
            duration = drama['duration_seconds']
            if (drama_id, beijing_day) in blocked:
                continue
            if duration is not None and duration < 1800:
                continue
            if drama['expires_at'] and utc(datetime.fromisoformat(drama['expires_at'])) <= instant:
                continue
            actual = assessment['actual_theme']
            strong = actual == category and bool(assessment['strong_directions']) and assessment.get('focus_match', True)
            preference = 2 if strong else 1 if actual == category else 0
            chinese_original = drama.get('source_language') == 'zh'
            editorial = (assessment.get('comparison_priority', 0), chinese_original)
            choices.append((preference, editorial, duration if duration is not None else -1, drama_id, assessment))
        return sorted(choices, key=lambda item: item[:-1], reverse=True)

    # Reserve strong and ordinary matches for their own slot category.
    # Reassign only if expiry or same-day exclusions still leave a gap.
    target_keys = [(target['publish_date'], target['publish_slot_id']) for _, _, target in targets]
    choices_by_slot = {key: ranked(target, day, instant)
                       for key, (instant, day, target) in zip(target_keys, targets)}
    assignments = {}
    owners = {}

    def assign(key, pick):
        assignments[key] = pick
        owners[pick[3]] = key

    def fill_gap(key, visited):
        for pick in choices_by_slot[key]:
            drama_id = pick[3]
            if drama_id in visited:
                continue
            visited.add(drama_id)
            owner = owners.get(drama_id)
            if owner is None or fill_gap(owner, visited):
                assign(key, pick)
                return True
        return False

    for level in (2, 1, 0):
        for key in target_keys:
            if key in assignments:
                continue
            pick = next((item for item in choices_by_slot[key] if item[0] == level and item[3] not in owners), None)
            if pick:
                assign(key, pick)
    for key in target_keys:
        if key not in assignments:
            fill_gap(key, set())

    rows = []
    for key, (_, _, target) in zip(target_keys, targets):
        pick = assignments.get(key)
        if not pick:
            rows.append({**target, 'drama_id': None, 'reason': '符合语种、有效期和同日去重的剩余库存已用尽'})
            continue
        category = snapshot['slot_topics'][key[1]]
        *_, drama_id, judgment = pick
        actual = judgment['actual_theme']
        basis = next(iter(judgment['strong_directions']), None)
        strong = actual == category and bool(basis) and judgment.get('focus_match', True)
        direction = basis if strong else next(iter(topics[category]), None)
        if judgment['playlist_id'] not in playlists:
            raise ValueError('剧情评估未选择当前频道的可用播放列表')
        rows.append({**target, 'drama_id': drama_id, 'reason': judgment['reason'],
                     'plot_evidence': judgment['plot_evidence'],
                     'pairing_reason': f"按该档的目标与可用候选编排，实际主线为{judgment['actual_direction']}。",
                     'target_theme': category, 'target_direction': direction, 'actual_theme': actual,
                     'actual_direction': judgment['actual_direction'], 'theme_basis': basis,
                     'match_level': 'strong' if strong else 'fallback', 'deviates_from_target': not strong,
                     'fallback_reason': None if strong else (
                         '该剧未吻合本次细分观看承诺：' + judgment['reason'] if judgment.get('focus_match') is False
                         else '该档没有剩余的强匹配候选，按真实主线补位'),
                     'playlist_id': judgment['playlist_id'], 'operating_reference_version_id': reference_id})
    return {'rows': rows}


def complete_assessment_batch(model, model_name, prompt, batch, playlist_ids, path):
    from zhiju.scheduling_rules.contract import PLOT_FIELDS

    plots = {
        drama['id']: [(drama.get(field) or '').strip() for field in PLOT_FIELDS]
        for drama in batch
    }

    def group(rows, expected):
        grouped = {drama_id: [] for drama_id in expected}
        for row in rows:
            drama_id = row.get('drama_id')
            if drama_id in grouped and row not in grouped[drama_id]:
                grouped[drama_id].append(row)
        return grouped

    def valid_row(drama_id, rows):
        valid = []
        for row in rows:
            evidence = row['plot_evidence'].strip()
            if (row['playlist_id'] in playlist_ids and len(evidence) >= 4
                    and any(evidence in text for text in plots[drama_id])
                    and row['actual_direction'].strip() and row['reason'].strip()):
                valid.append(row)
        return valid[0] if len(valid) == 1 else None

    def assess(candidates, instructions=''):
        return model.generate(stage(prompt + instructions + '\n候选：' + encode(candidates),
                                    REFERENCE_ASSESSMENT_SCHEMA), model_name)['rows']

    checkpoint = json.loads(path.read_text()) if path.exists() else {'rows': assess(batch)}
    grouped = group(checkpoint['rows'], plots)
    excluded = set(checkpoint.get('excluded_ids', [])) & plots.keys()

    def save():
        temporary = path.with_suffix('.tmp')
        temporary.write_text(encode({'rows': [row for rows in grouped.values() for row in rows],
                                     'excluded_ids': sorted(excluded)}))
        temporary.replace(path)

    pending = [drama for drama in batch if drama['id'] not in excluded
               and valid_row(drama['id'], grouped[drama['id']]) is None]
    if pending and not path.exists():
        save()
    for offset in range(0, len(pending), 4):
        candidates = pending[offset:offset + 4]
        try:
            retried = assess(candidates, '\n仅补评下列候选，每个 ID 恰好返回一条。不要返回其他剧。')
        except TimeoutError:
            retried = []
        repaired = group(retried, (drama['id'] for drama in candidates))
        for drama in candidates:
            drama_id = drama['id']
            replacement = valid_row(drama_id, repaired[drama_id])
            if replacement:
                grouped[drama_id] = [replacement]
                continue
            # A fallback needs both a real excerpt and an unambiguous playlist.
            assignments = {row['playlist_id'] for row in grouped[drama_id] + repaired[drama_id]
                           if row['playlist_id'] in playlist_ids}
            quote = next((text[:160].rstrip() for text in plots[drama_id] if len(text[:160].rstrip()) >= 4), '')
            if len(assignments) == 1 and quote:
                grouped[drama_id] = [{
                    'drama_id': drama_id, 'plot_evidence': quote, 'actual_theme': 'neither',
                    'strong_direction_ids': [], 'playlist_id': assignments.pop(),
                    'actual_direction': '实际主线待核对，见剧情原文',
                    'reason': '原评估未通过复核，依据库内原文保留为补位候选',
                }]
            else:
                excluded.add(drama_id)
                grouped[drama_id] = []
        save()

    if not path.exists():
        save()
    return [row for drama_id, rows in grouped.items() if drama_id not in excluded
            and (row := valid_row(drama_id, rows)) is not None]


def reference_assessment(model, run, root, progress):
    from zhiju.scheduling_rules.contract import validate_result
    snapshot = run['input_snapshot']
    from zhiju.channel_analysis_rules.operating_reference import selection_reference
    sections = selection_reference(snapshot['operating_reference']['sections'])
    rules = '\n'.join(v for k, v in snapshot['skill_version']['files'].items() if k.endswith('.md') and v)
    context = {key: sections[key] for key in ('topics', 'empathy', 'selection_guidance')}
    if snapshot.get('selection_method') == 'audience-continuity-v1':
        if not snapshot.get('selection_evidence'):
            raise ValueError('修订4尚未冻结本频道逐视频表现，请先读取证据')
        context['feedback_stage'] = '本阶段只阅读全文、提取真实主线；逐视频表现统一在全候选相对比较阶段提供。'
    playlist_ids = {p['id'] for p in snapshot['playlists']}
    directions = {
        theme: {f'{theme}:{index}': text for index, text in enumerate(topics, start=1)}
        for theme, topics in snapshot['analysis_topics'].items()
    }
    prompt = (rules + '\n本阶段只判断每部候选的实际主线，排片由系统完成。'
              '同批由系统按频道录入时间的北京时间日期和运营语言判定。'
              'strong_direction_ids 只返回下方 actual_theme 对应方向的编号。实际核心冲突必须兑现该方向。'
              '没有充分依据填空数组。包装监测、支线或偶然关键词不算。编号由系统换回报告原文。'
              'plot_evidence 必须逐字引用该剧剧情字段中的一段连续原文，说明实际主线和理由。'
              '不匹配的库存也要选最贴近的现有列表 ID，供缺片时补位。每部恰好一行。'
              '\n运营参考：' + encode(context) + '\n方向编号：' + encode(directions) +
              '\n现有列表：' + encode(snapshot['playlists']))
    judgments = []
    processed = 0
    for index, batch in enumerate(assessment_batches(snapshot['candidates'])):
        if progress:
            progress('assessing', processed, len(snapshot['candidates']), f'评估第 {index + 1} 批剧情')
        path = root / f'reference-assessment-{index}.json'
        for row in complete_assessment_batch(model, snapshot['model'], prompt, batch, playlist_ids, path):
            options = directions.get(row['actual_theme'], {})
            if 'strong_direction_ids' in row:
                strong = [options[code] for code in row['strong_direction_ids'] if code in options]
            else:
                # Previous executor checkpoints carry the original report text.
                strong = [text for text in row['strong_directions'] if text in options.values()]
            judgments.append({**row, 'strong_directions': strong})
        processed += len(batch)
    review = None
    if snapshot.get('selection_method') == 'audience-continuity-v1':
        if progress:
            progress('planning', processed, len(snapshot['candidates']), '全候选对照：细分观众期待与已发布表现')
        judgments, review = compare_audience(model, snapshot, judgments, root)
    if progress:
        progress('planning', processed, len(snapshot['candidates']), '按剧情承接优先编排，同档适配相近时再比较时长')
    result = reference_rows(snapshot, judgments)
    if review:
        result['planning_review'] = review
        comparisons = {row['drama_id']: row for row in judgments}
        for row in result['rows']:
            if row['drama_id']:
                row['selection_focus'] = review['viewer_promises'][row['target_theme']]
                row['comparison_reason'] = comparisons[row['drama_id']]['reason']
                row['pairing_reason'] = '本档观看承诺：' + row['selection_focus'] + '；' + row['comparison_reason']
    validate_result(snapshot, result)
    return result


def assessment_batches(candidates):
    batch = []
    size = 0
    for drama in candidates:
        count = len(encode(drama).encode('utf-8'))
        if batch and size + count > 100_000:
            yield batch
            batch, size = [], 0
        batch.append(drama)
        size += count
    if batch:
        yield batch


def generate(model,run,root,progress=None):
    snapshot=run['input_snapshot'];model_name=snapshot['model']
    if snapshot.get('operating_reference'):
        return reference_assessment(model, run, root, progress)
    rules='\n'.join(v for k,v in snapshot['skill_version']['files'].items() if k.endswith('.md') and v)
    guidance={k:v for k,v in snapshot['guidance'].items() if k != 'normalized_snapshot'}
    context='按本次选定排期Skill执行：\n'+rules+'\n频道与生效资料：'+encode({'channel':snapshot['channel'],'guidance':guidance})
    slot_topics=snapshot.get('slot_topics')
    analysis_topics = snapshot.get('analysis_topics')
    assessment_schema=ASSESSMENT_SCHEMA
    assessment_instruction='逐部判断候选是否适配频道、是否主主题并解释。'
    if slot_topics:
        context += (
            '\n以用户逐档指定题材为准。'
            '主题材（primary）是频道资料明确的核心方向；辅题材（secondary）是资料明确支持的辅助方向。'
            '题材以核心剧情为准，同时适配时按最主要的剧情归类；都不符合或频道资料缺少依据时选neither。'
            '辅题材不能用仅仅非主题材或同样适配频道的其他剧替代。'
        )
        assessment_schema=TOPIC_ASSESSMENT_SCHEMA
        assessment_instruction='逐部判断候选是否适配频道、属于primary、secondary还是neither，并根据频道方向和剧的核心剧情解释。'
    if analysis_topics is not None:
        context += '\n本次生效分析题材（primary=主题材，secondary=辅题材）：' + encode(analysis_topics)
        assessment_schema = ANALYSIS_TOPIC_ASSESSMENT_SCHEMA
        assessment_instruction += (
            'theme_basis 必须逐字使用对应题材清单中的一条。'
            '只用于跟踪数据或解释包装的条目不能单独作为选剧依据。'
            '无合格方向则标为neither、eligible=false、theme_basis为空。'
        )

    # Read every complete plot once; only compact, evidenced judgments enter final planning.
    batches = list(assessment_batches(snapshot['candidates']))
    assessments=[];processed=0
    for index,batch in enumerate(batches):
        if progress:progress('assessing',processed,len(snapshot['candidates']),f'评估第 {index+1} / {len(batches)} 批剧情')
        path=root/f'assessment-{index}.json'
        if path.exists():result=json.loads(path.read_text())
        else:
            result=model.generate(stage(context+'\n'+assessment_instruction+
                'plot_evidence必须逐字引用该剧四个剧情字段中的一段连续原文。每个候选恰好一行，包含不适配者。\n候选：'+encode(batch),
                assessment_schema),model_name)
            ids={d['id'] for d in batch};rows=result.get('rows',[])
            if len(rows)!=len(ids) or {r['drama_id'] for r in rows}!=ids:raise ValueError('候选剧情评估未完整覆盖本批剧目')
            plots={d['id']:d for d in batch}
            for row in rows:
                if analysis_topics is not None and row['eligible']:
                    if row.get('theme_basis') not in analysis_topics.get(row['theme'], []):
                        raise ValueError('候选评估缺少生效分析中对应的题材方向')
                if row['eligible'] and (len(row['plot_evidence'].strip())<4 or not any(row['plot_evidence'] in (plots[row['drama_id']].get(k) or '') for k in ('content_summary','plot_archive','plot_pattern','core_personas'))):
                    raise ValueError('候选评估缺少可核对的剧情原文')
            path.write_text(encode(result))
        processed+=len(batch)
        if progress:progress('assessing',processed,len(snapshot['candidates']),'本批剧情评估完成')
        assessments.extend(r for r in result['rows'] if r['eligible']
                           and (not slot_topics or r['theme'] in slot_topics.values()))
    candidates={d['id']:d for d in snapshot['candidates']}
    compact=[{**r,'chinese_title':candidates[r['drama_id']]['chinese_title'],
        'duration_seconds':candidates[r['drama_id']]['duration_seconds'],'expires_at':candidates[r['drama_id']]['expires_at']}
        for r in assessments]
    if slot_topics:
        topic_rule=('候选theme必须与该publish_slot_id的指定题材相同。主档优先较长且不少于100分钟。'
                    '没有符合指定题材和时长的剧时，将该档drama_id设为null并说明缺口。不同档位可按各自题材编排。'
                    '\n按档位ID指定题材：'+encode(slot_topics))
    else:
        topic_rule=('main_theme=false不能进入主档；本系统首个排期日起14天内辅档也须主主题，此后可选其他适配方向。'
                    '主档在适配主主题中优先较长且不少于100分钟。时长或库存不足则drama_id=null，并说明缺口。')
    prompt=(context+'\n依据以下已阅读剧情的判断为每个空档位选择剧目，同频道去重，逐日说明配对和多日变化。'
        'plot_evidence复制该候选的原文引用。空档位必须全部覆盖。'+topic_rule+
        '\n档位：'+encode(snapshot['slots'])+
        ('\n本系统首个排期日：'+snapshot['first_scheduled_date'] if not slot_topics else '')+
        ('\n空档位的 publish_date 是北京时间日期，按原值返回。' if snapshot.get('date_basis') == 'beijing' else '')+
        '\n空档位：'+encode(snapshot['targets'])+'\n候选判断：'+encode(compact))
    # Validate before upload and use concrete failure feedback to replan only this stage.
    from zhiju.scheduling_rules.contract import validate_result
    previous=None;error=''
    attempt_root=root/run['claim_id'];attempt_root.mkdir(exist_ok=True)
    for attempt in range(3):
        if progress:progress('planning',processed,len(snapshot['candidates']),f'编排第 {attempt+1} / 3 次尝试')
        path=attempt_root/f'plan-{attempt}.json'
        if path.exists():result=json.loads(path.read_text())
        else:
            suffix=('\n上次规划未通过，请根据具体原因换角度重新编排：'+error+'\n上次结果：'+encode(previous)) if previous else ''
            result=model.generate(stage(prompt+suffix,PLAN_SCHEMA),model_name);path.write_text(encode(result))
        try:
            if progress:progress('validating',processed,len(snapshot['candidates']),'校验剧情依据、时长和档位')
            judgments={r['drama_id']:r for r in assessments}
            slots={r['id']:r for r in snapshot['slots']}
            for row in result['rows']:
                if row['drama_id']:
                    judgment=judgments.get(row['drama_id'])
                    if not judgment:
                        raise ValueError('选剧不在符合频道方向的候选剧情评估中')
                    if slot_topics:
                        row['drama_theme'] = judgment['theme']
                        if analysis_topics is not None:
                            row['theme_basis'] = judgment['theme_basis']
                            row['plot_evidence'] = judgment['plot_evidence']
                    else:
                        first_fortnight=date.fromisoformat(row['publish_date']) < date.fromisoformat(snapshot['first_scheduled_date'])+timedelta(days=14)
                        if (slots[row['publish_slot_id']]['slot_type']=='main' or first_fortnight) and not judgment['main_theme']:
                            raise ValueError('选剧不符合主档或前14天的主主题要求')
            validate_result(snapshot,result)
            return result
        except (ValueError,RuntimeError,KeyError) as exc:
            previous=result;error=str(exc)
    raise ValueError('重新编排后仍无法通过：'+error)


def submit_cached(client,path):
    entry=json.loads(path.read_text())
    result=client.request('PUT',f"/schedule-plans/{entry['plan_id']}/result",entry['body'])
    path.replace(path.with_name('submitted.json'));return result


class SchedulingProgress:
    def __init__(self,client,run):
        self.client=client;self.run=run;self.lock=Lock();self.started=monotonic();self.changed=self.started
        self.value={'stage':'preparing','completed_items':0,'total_items':len(run['input_snapshot']['candidates']),'current_item':'准备排期资料'}
    def set(self,stage,completed,total,item):
        with self.lock:
            if stage!=self.value['stage']:self.changed=monotonic()
            self.value={'stage':stage,'completed_items':completed,'total_items':total,'current_item':item}
        self.send()
    def send(self):
        with self.lock:
            value=dict(self.value,elapsed_seconds=int(monotonic()-self.started),stage_elapsed_seconds=int(monotonic()-self.changed))
        try:self.client.request('POST',f"/schedule-plans/{self.run['id']}/heartbeat",{'claim_id':self.run['claim_id'],'progress':value})
        except ConnectionError:pass


def recover_cached(client,cache_root):
    cache_root=Path(cache_root);cache_root.mkdir(parents=True,exist_ok=True)
    for pending in cache_root.glob('*/pending.json'):
        try:submit_cached(client,pending)
        except CloudConflict:
            entry=json.loads(pending.read_text());run=client.request('GET',f"/schedule-plans/{entry['plan_id']}")
            if run['claim_id']!=entry['body']['claim_id'] or run['status']!='running':pending.replace(pending.with_name('abandoned.json'))
            else:raise


def process_claimed(client,model,config,cache_root,run,stop_event=None):
    root=Path(cache_root)/run['id'];root.mkdir(parents=True,exist_ok=True)
    finished=Event();cancelled=Event();progress=SchedulingProgress(client,run)
    def heartbeat():
        while not finished.wait(15):
            try:progress.send()
            except (PermissionError,CloudConflict):cancelled.set();return
    thread=Thread(target=heartbeat,daemon=True);thread.start()
    model.cancelled=lambda:cancelled.is_set() or bool(stop_event and stop_event.is_set())
    body={'claim_id':run['claim_id']}
    try:
        if model.account_profile!=run['input_snapshot']['account_profile']:raise ValueError('排期账号绑定不一致')
        if run['input_snapshot'].get('selection_method') == 'audience-continuity-v1':
            progress.set('preparing', 0, len(run['input_snapshot']['candidates']), '读取本频道逐视频表现及上次排期反馈')
            refreshed = client.request('POST', f"/schedule-plans/{run['id']}/evidence", {'claim_id': run['claim_id']}, timeout=300)
            run['input_snapshot'] = refreshed['input_snapshot']
        body['result']=generate(model,run,root,progress.set)
        progress.set('delivery',len(run['input_snapshot']['candidates']),len(run['input_snapshot']['candidates']),'回传预览，等待云端校验')
    except (ValueError,RuntimeError,OSError) as exc:
        if isinstance(exc,(PermissionError,ConnectionError)):raise
        body['error']=str(exc)[:4000]
    finally:
        finished.set();thread.join(timeout=1)
    pending=root/'pending.json';pending.write_text(encode({'plan_id':run['id'],'body':body}))
    submit_cached(client,pending)


def drain(client,model,config,cache_root,once=False):
    recover_cached(client,cache_root)
    while True:
        run=client.request('POST','/schedule-planning/claims',{'host_id':client.host_id,'executor_protocol':EXECUTOR_PROTOCOL})
        if not run:return
        if run['tenant_id']!=client.tenant_id:raise PermissionError('排期任务公司不匹配')
        process_claimed(client,model,config,cache_root,run)
        if once:return
