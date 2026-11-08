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
    'strong_directions': {'type': 'array', 'items': {'type': 'string'}},
    'playlist_id': {'type': 'string'},
    'reason': {'type': 'string'},
    'plot_evidence': {'type': 'string'},
})


def reference_rows(snapshot, assessments):
    """Reserve strong candidates first, then fill remaining slots from real stock."""
    from datetime import datetime, time, timezone
    from zoneinfo import ZoneInfo
    from zhiju.scheduling_rules.contract import utc

    candidates = {row['id']: row for row in snapshot['candidates']}
    playlists = {row['id'] for row in snapshot['playlists']}
    topics = snapshot['analysis_topics']
    slots = {row['id']: row for row in snapshot['slots']}
    blocked = {(r['drama_id'], r['beijing_date']) for r in snapshot['batch_blocked']}
    reference_id = snapshot['operating_reference']['dna_id']
    used = set()
    rows = {}
    targets = []
    for target in snapshot['targets']:
        slot = slots[target['publish_slot_id']]
        zone = ZoneInfo(slot['timezone'])
        local = datetime.combine(date.fromisoformat(target['publish_date']), time.fromisoformat(slot['local_time']), zone)
        instant = local.astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
            raise ValueError('档位落在夏令时跳过的当地时间，请调整档位后重新规划')
        beijing_day = instant.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        targets.append((instant, beijing_day, target))
    targets.sort(key=lambda row: (row[0], row[2]['publish_slot_id']))

    def ranked(target, beijing_day, instant, *, strong_only):
        category = snapshot['slot_topics'][target['publish_slot_id']]
        choices = []
        for assessment in assessments:
            drama = candidates[assessment['drama_id']]
            drama_id = drama['id']
            duration = drama['duration_seconds']
            if drama_id in used or (drama_id, beijing_day) in blocked:
                continue
            if duration is not None and duration < 1800:
                continue
            if drama['expires_at'] and utc(datetime.fromisoformat(drama['expires_at'])) <= instant:
                continue
            actual = assessment['actual_theme']
            strong = actual == category and bool(assessment['strong_directions'])
            if strong_only and not strong:
                continue
            preference = 2 if strong else 1 if actual == category else 0
            choices.append((preference, duration if duration is not None else -1, drama_id, assessment))
        return max(choices, key=lambda item: item[:3]) if choices else None

    for strong_only in (True, False):
        for instant, beijing_day, target in targets:
            key = (target['publish_date'], target['publish_slot_id'])
            if key in rows:
                continue
            category = snapshot['slot_topics'][key[1]]
            pick = ranked(target, beijing_day, instant, strong_only=strong_only)
            if not pick:
                if not strong_only:
                    rows[key] = {**target, 'drama_id': None, 'reason': '符合语种、有效期和同日去重的剩余库存已用尽'}
                continue
            _, _, drama_id, judgment = pick
            used.add(drama_id)
            actual = judgment['actual_theme']
            basis = next(iter(judgment['strong_directions']), None)
            strong = actual == category and bool(basis)
            direction = basis if strong else next(iter(topics[category]), None)
            if judgment['playlist_id'] not in playlists:
                raise ValueError('剧情评估未选择当前频道的可用播放列表')
            rows[key] = {**target, 'drama_id': drama_id, 'reason': judgment['reason'],
                         'plot_evidence': judgment['plot_evidence'],
                         'pairing_reason': f"按该档的目标与可用候选编排，实际主线为{judgment['actual_direction']}。",
                         'target_theme': category, 'target_direction': direction, 'actual_theme': actual,
                         'actual_direction': judgment['actual_direction'], 'theme_basis': basis,
                         'match_level': 'strong' if strong else 'fallback', 'deviates_from_target': not strong,
                         'fallback_reason': None if strong else '该档没有剩余的强匹配候选，按真实主线补位',
                         'playlist_id': judgment['playlist_id'], 'operating_reference_version_id': reference_id}
    return {'rows': list(rows.values())}


def reference_assessment(model, run, root, progress):
    from zhiju.scheduling_rules.contract import PLOT_FIELDS, validate_result
    snapshot = run['input_snapshot']
    sections = snapshot['operating_reference']['sections']
    rules = '\n'.join(v for k, v in snapshot['skill_version']['files'].items() if k.endswith('.md') and v)
    context = {key: sections[key] for key in ('topics', 'empathy', 'scheduling_playlist')}
    playlist_ids = {p['id'] for p in snapshot['playlists']}
    prompt = (rules + '\n本阶段只判断每部候选的实际主线，排片由系统完成。'
              '同批由系统按频道录入时间的北京时间日期和运营语言判定。'
              'strong_directions 是实际核心冲突真正兑现的报告原文，可为空。包装监测、支线或偶然关键词不算。'
              '不匹配的库存也要说明真实主线并选最贴近的现有列表 ID，供缺片时补位。每部恰好一行。'
              '\n运营参考：' + encode(context) + '\n现有列表：' + encode(snapshot['playlists']))
    judgments = []
    for index, batch in enumerate(assessment_batches(snapshot['candidates'])):
        if progress:
            progress('assessing', len(judgments), len(snapshot['candidates']), f'评估第 {index + 1} 批剧情')
        path = root / f'reference-assessment-{index}.json'
        result = json.loads(path.read_text()) if path.exists() else model.generate(
            stage(prompt + '\n候选：' + encode(batch), REFERENCE_ASSESSMENT_SCHEMA), snapshot['model'])
        plots = {d['id']: d for d in batch}
        rows = result['rows']
        if len(rows) != len(plots) or {r['drama_id'] for r in rows} != set(plots):
            raise ValueError('题材评估没有逐部覆盖候选')
        for row in rows:
            drama = plots[row['drama_id']]
            evidence = row['plot_evidence'].strip()
            if (len(evidence) < 4 or not any(evidence in (drama.get(key) or '') for key in PLOT_FIELDS)
                    or not row['actual_direction'].strip() or not row['reason'].strip()):
                raise ValueError('题材评估缺少真实剧情原文、实际主线或判断理由')
            if any(direction not in snapshot['analysis_topics'].get(row['actual_theme'], [])
                   for direction in row['strong_directions']):
                raise ValueError('强匹配方向不属于实际题材的生效参考')
            if row['playlist_id'] not in playlist_ids:
                raise ValueError('剧情评估指定的播放列表无效')
        path.write_text(encode(result))
        judgments.extend(rows)
    if progress:
        progress('planning', len(judgments), len(snapshot['candidates']), '按匹配强度和时长编排并核对播放列表')
    result = reference_rows(snapshot, judgments)
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
