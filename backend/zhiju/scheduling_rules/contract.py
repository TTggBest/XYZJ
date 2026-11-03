"""Pure scheduling result contract shared by cloud and database-free executors."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

PLOT_FIELDS=('content_summary','plot_archive','plot_pattern','core_personas')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_result(snapshot,result):
    from datetime import time
    if not isinstance(result,dict) or not isinstance(result.get('rows'),list):raise ValueError('排期输出缺少 rows')
    targets={(r['publish_date'],r['publish_slot_id']) for r in snapshot['targets']}
    candidates={d['id']:d for d in snapshot['candidates']}
    slots={r['id']:r for r in snapshot['slots']}
    seen=set();used=set();rows=[]
    for row in result['rows']:
        if not isinstance(row,dict):raise ValueError('排期行格式错误')
        key=(row.get('publish_date'),row.get('publish_slot_id'))
        if key not in targets or key in seen:raise ValueError('排期日期档位缺失、重复或超出本次范围')
        seen.add(key)
        if not str(row.get('reason') or '').strip():raise ValueError('每个排期或缺口须说明原因')
        drama_id=row.get('drama_id')
        if drama_id is None:
            rows.append({'publish_date':key[0],'publish_slot_id':key[1],'drama_id':None,'reason':row['reason'],'status':'blocked'});continue
        if drama_id not in candidates or drama_id in used:raise ValueError('选剧不在候选池或同频道重复')
        used.add(drama_id);drama=candidates[drama_id];slot=slots[key[1]]
        evidence=str(row.get('plot_evidence') or '').strip()
        if len(evidence)<4 or not any(evidence in (drama.get(k) or '') for k in PLOT_FIELDS):
            raise ValueError('选剧须引用真实剧情原文，不能仅凭剧名或编造剧情')
        if not str(row.get('pairing_reason') or '').strip():raise ValueError('缺少同日搭配或编排理由')
        duration=drama['duration_seconds']
        if slot['slot_type']=='main' and (duration is None or duration<6000):
            raise ValueError('主档不足100分钟或时长未知，请标记缺口而非静默替代')
        local=datetime.combine(date.fromisoformat(key[0]),time.fromisoformat(slot['local_time']),ZoneInfo(slot['timezone']))
        instant=local.astimezone(timezone.utc)
        # A nonexistent DST clock time has no matching round trip.
        if instant.astimezone(ZoneInfo(slot['timezone'])).replace(tzinfo=None)!=local.replace(tzinfo=None):
            raise ValueError('档位落在夏令时跳过的当地时间，请调整档位后重新规划')
        if drama['expires_at'] and utc(datetime.fromisoformat(drama['expires_at']))<=instant:
            raise ValueError('剧目在计划发布时间已到期')
        rows.append({**row,'chinese_title':drama['chinese_title'],'duration_seconds':duration,
            'finished_languages':drama['finished_languages'],'status':'planned','slot_type':slot['slot_type'],
            'planned_local_time':local.replace(tzinfo=None).isoformat(),
            'planned_utc_time':instant.replace(tzinfo=None).isoformat(),
            'planned_beijing_time':instant.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None).isoformat(),
            'warnings':['辅档时长未验证'] if duration is None else []})
    if seen!=targets:raise ValueError('输出没有覆盖所有空档位；无合格剧目时也须逐档说明缺口')
    return {'rows':sorted(rows,key=lambda r:(r['publish_date'],slots[r['publish_slot_id']]['local_time'])),
            'schedule_ids':[]}

