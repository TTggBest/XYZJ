"""Bounded story assessment, AI planning and cached result delivery."""
import json
from datetime import date, timedelta
from pathlib import Path
from threading import Event, Thread, Lock
from time import monotonic
from types import SimpleNamespace
from .client import CloudConflict


def array_schema(properties):
    return {'type':'object','additionalProperties':False,'properties':{'rows':{'type':'array','items':{
        'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}}},'required':['rows']}


ASSESSMENT_SCHEMA=array_schema({'drama_id':{'type':'string'},'eligible':{'type':'boolean'},
    'main_theme':{'type':'boolean'},'reason':{'type':'string'},'plot_evidence':{'type':'string'}})
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


def generate(model,run,root,progress=None):
    snapshot=run['input_snapshot'];model_name=snapshot['model']
    rules='\n'.join(v for k,v in snapshot['skill_version']['files'].items() if k.endswith('.md') and v)
    guidance={k:v for k,v in snapshot['guidance'].items() if k != 'normalized_snapshot'}
    context='按本次选定排期Skill执行：\n'+rules+'\n频道与生效资料：'+encode({'channel':snapshot['channel'],'guidance':guidance})
    # Read every complete plot once; only compact, evidenced judgments enter final planning.
    batches=[];batch=[];size=0
    for drama in snapshot['candidates']:
        count=len(encode(drama).encode('utf-8'))
        if batch and size+count>100_000:batches.append(batch);batch=[];size=0
        batch.append(drama);size+=count
    if batch:batches.append(batch)
    assessments=[];processed=0
    for index,batch in enumerate(batches):
        if progress:progress('assessing',processed,len(snapshot['candidates']),f'评估第 {index+1} / {len(batches)} 批剧情')
        path=root/f'assessment-{index}.json'
        if path.exists():result=json.loads(path.read_text())
        else:
            result=model.generate(stage(context+'\n逐部判断候选是否适配频道、是否主主题并解释；plot_evidence必须逐字引用该剧四个剧情字段中的一段连续原文。每个候选恰好一行，包含不适配者。\n候选：'+encode(batch),ASSESSMENT_SCHEMA),model_name)
            ids={d['id'] for d in batch};rows=result.get('rows',[])
            if len(rows)!=len(ids) or {r['drama_id'] for r in rows}!=ids:raise ValueError('候选剧情评估未完整覆盖本批剧目')
            plots={d['id']:d for d in batch}
            for row in rows:
                if row['eligible'] and (len(row['plot_evidence'].strip())<4 or not any(row['plot_evidence'] in (plots[row['drama_id']].get(k) or '') for k in ('content_summary','plot_archive','plot_pattern','core_personas'))):
                    raise ValueError('候选评估缺少可核对的剧情原文')
            path.write_text(encode(result))
        processed+=len(batch)
        if progress:progress('assessing',processed,len(snapshot['candidates']),'本批剧情评估完成')
        assessments.extend(r for r in result['rows'] if r['eligible'])
    candidates={d['id']:d for d in snapshot['candidates']}
    compact=[{**r,'chinese_title':candidates[r['drama_id']]['chinese_title'],
        'duration_seconds':candidates[r['drama_id']]['duration_seconds'],'expires_at':candidates[r['drama_id']]['expires_at']}
        for r in assessments]
    prompt=(context+'\n依据以下已阅读剧情的判断为每个空档位选择剧目，同频道去重，逐日说明配对和多日变化。'
        'main_theme=false不能进入主档；本系统首个排期日起14天内辅档也须主主题，此后可选其他适配方向。主档在适配主主题中优先较长且不少于100分钟。时长或库存不足则drama_id=null，并说明缺口。'
        'plot_evidence复制该候选的原文引用。空档位必须全部覆盖。\n档位：'+encode(snapshot['slots'])+
        '\n本系统首个排期日：'+snapshot['first_scheduled_date']+'\n空档位：'+encode(snapshot['targets'])+'\n候选判断：'+encode(compact))
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
                    first_fortnight=date.fromisoformat(row['publish_date']) < date.fromisoformat(snapshot['first_scheduled_date'])+timedelta(days=14)
                    if not judgment or ((slots[row['publish_slot_id']]['slot_type']=='main' or first_fortnight) and not judgment['main_theme']):
                        raise ValueError('选剧不符合前序剧情评估或主档主主题要求')
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
        run=client.request('POST','/schedule-planning/claims',{'host_id':client.host_id,'executor_protocol':5})
        if not run:return
        if run['tenant_id']!=client.tenant_id:raise PermissionError('排期任务公司不匹配')
        process_claimed(client,model,config,cache_root,run)
        if once:return
