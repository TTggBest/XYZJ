"""Pure scheduling result contract shared by cloud and database-free executors."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

SLOT_TOPICS_PROTOCOL = 9
REFERENCE_PROTOCOL = 10

PLOT_FIELDS=('content_summary','plot_archive','plot_pattern','core_personas')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_result(snapshot,result):
    from datetime import time
    if not isinstance(result,dict) or not isinstance(result.get('rows'),list):raise ValueError('排期输出缺少 rows')
    targets={(r['publish_date'],r['publish_slot_id']) for r in snapshot['targets']}
    candidates={d['id']:d for d in snapshot['candidates']}
    slots={r['id']:r for r in snapshot['slots']}
    slot_topics=snapshot.get('slot_topics', {})
    analysis_topics = snapshot.get('analysis_topics')
    reference = snapshot.get('operating_reference')
    playlists = {p['id']: p for p in snapshot.get('playlists', [])}
    blocked = {(p['drama_id'], p['beijing_date']) for p in snapshot.get('batch_blocked', [])}
    seen=set();used=set();rows=[]
    for row in result['rows']:
        if not isinstance(row,dict):raise ValueError('排期行格式错误')
        key=(row.get('publish_date'),row.get('publish_slot_id'))
        if key not in targets or key in seen:raise ValueError('排期日期档位缺失、重复或超出本次范围')
        seen.add(key)
        if not str(row.get('reason') or '').strip():raise ValueError('每个排期或缺口须说明原因')
        drama_id=row.get('drama_id')
        if drama_id is None:
            gap = {'publish_date':key[0],'publish_slot_id':key[1],'drama_id':None,'reason':row['reason'],'status':'blocked'}
            if reference:
                kind = slot_topics[key[1]]
                gap.update(target_theme=kind, target_direction=next(iter(analysis_topics[kind]), None),
                           actual_theme=None, actual_direction=None, playlist_id=None,
                           operating_reference_version_id=reference['dna_id'])
            rows.append(gap)
            continue
        if drama_id not in candidates or drama_id in used:raise ValueError('选剧不在候选池或同频道重复')
        if not reference and key[1] in slot_topics and row.get('drama_theme') != slot_topics[key[1]]:
            raise ValueError('所选剧目题材与档位要求不符，请改选匹配的候选剧或标记缺口')
        if not reference and analysis_topics is not None and row.get('theme_basis') not in analysis_topics[slot_topics[key[1]]]:
            raise ValueError('所选剧目须引用该档题材在生效分析中的具体方向')
        if reference:
            target = slot_topics[key[1]]
            level = row.get('match_level')
            actual = row.get('actual_theme')
            basis = row.get('theme_basis')
            direction = row.get('target_direction')
            if row.get('target_theme') != target or (direction not in analysis_topics[target]
                    and (direction is not None or analysis_topics[target])):
                raise ValueError('目标方向必须来自所选类别的已应用运营参考')
            if row.get('operating_reference_version_id') != reference['dna_id']:
                raise ValueError('排期运营参考版本与本次快照不一致')
            if actual not in {'primary', 'secondary', 'neither'} or not str(row.get('actual_direction') or '').strip():
                raise ValueError('入选剧须说明实际主线及题材')
            if basis and basis not in analysis_topics.get(actual, []):
                raise ValueError('实际题材依据必须来自对应的运营参考')
            if level == 'strong':
                if actual != target or not basis or basis != direction or row.get('deviates_from_target') is not False or row.get('fallback_reason'):
                    raise ValueError('强匹配须以实际主线支持目标方向')
            elif level != 'fallback' or row.get('deviates_from_target') is not True or not str(row.get('fallback_reason') or '').strip():
                raise ValueError('补位须标记偏离并说明原因')
            if row.get('playlist_id') not in playlists:
                raise ValueError('排期须选择当前频道的可用播放列表')
        used.add(drama_id);drama=candidates[drama_id];slot=slots[key[1]]
        evidence=str(row.get('plot_evidence') or '').strip()
        if len(evidence)<4 or not any(evidence in (drama.get(k) or '') for k in PLOT_FIELDS):
            raise ValueError('选剧须引用真实剧情原文，不能仅凭剧名或编造剧情')
        if not str(row.get('pairing_reason') or '').strip():raise ValueError('缺少同日搭配或编排理由')
        duration=drama['duration_seconds']
        if not reference and slot['slot_type']=='main' and (duration is None or duration<6000):
            raise ValueError('主档不足100分钟或时长未知，请标记缺口而非静默替代')
        local=datetime.combine(date.fromisoformat(key[0]),time.fromisoformat(slot['local_time']),ZoneInfo(slot['timezone']))
        instant=local.astimezone(timezone.utc)
        # A nonexistent DST clock time has no matching round trip.
        if instant.astimezone(ZoneInfo(slot['timezone'])).replace(tzinfo=None)!=local.replace(tzinfo=None):
            raise ValueError('档位落在夏令时跳过的当地时间，请调整档位后重新规划')
        if drama['expires_at'] and utc(datetime.fromisoformat(drama['expires_at']))<=instant:
            raise ValueError('剧目在计划发布时间已到期')
        beijing = instant.astimezone(ZoneInfo('Asia/Shanghai'))
        if (drama_id, beijing.date().isoformat()) in blocked:
            raise ValueError('同批同语频道已在同一北京时间日期使用该剧')
        if reference and duration is not None and duration < 1800:
            raise ValueError('已知不足30分钟的剧不能排期')
        rows.append({**row,'chinese_title':drama['chinese_title'],'duration_seconds':duration,
            'finished_languages':drama['finished_languages'],'status':'planned','slot_type':slot['slot_type'],
            'planned_local_time':local.replace(tzinfo=None).isoformat(),
            'planned_utc_time':instant.replace(tzinfo=None).isoformat(),
            'planned_beijing_time':beijing.replace(tzinfo=None).isoformat(),
            'warnings':['时长未验证' if reference else '辅档时长未验证'] if duration is None else []})
    if seen!=targets:raise ValueError('输出没有覆盖所有空档位；无合格剧目时也须逐档说明缺口')
    return {'rows':sorted(rows,key=lambda r:(r['publish_date'],slots[r['publish_slot_id']]['local_time'])),
            'schedule_ids':[]}

