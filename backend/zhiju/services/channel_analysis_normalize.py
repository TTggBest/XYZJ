"""Source-scoped arithmetic; absent values are never numeric zero."""
from datetime import date,datetime,timedelta
import math
import re


def number(value):
    try:return float(str(value).replace(',','').replace('%','').strip())
    except (ValueError,TypeError):return None


STUDIO_COLUMNS={
    'views':('观看次数','Views'), 'impressions':('缩略图展示次数','展示次数','Impressions'),
    'ctr_percent':('缩略图点击率 (%)','展示点击率 (%)','Impressions click-through rate (%)'),
    'watch_hours':('观看时长（小时）','观看时长 (小时)','Watch time (hours)'),
    'subscribers_net':('订阅人数','Subscribers'), 'subscribers_gained':('获得的订阅人数','Subscribers gained'),
    'average_percentage_viewed':('平均观看百分比 (%)','Average percentage viewed (%)'),
    'returning_viewers':('回访观看者人数','Returning viewers'), 'revenue':('估算收入','Estimated revenue'),
    'duration_seconds':('时长','Duration')}


def studio_metrics(row):
    metrics={key:next((number(row[name]) for name in names if name in row),'unavailable') for key,names in STUDIO_COLUMNS.items()}
    metrics={key:value if value is not None else 'unavailable' for key,value in metrics.items()}
    duration=row.get('平均观看时长',row.get('Average view duration'))
    try:
        parts=[float(part) for part in duration.split(':')]
        metrics['average_view_duration_seconds']=sum(value*60**i for i,value in enumerate(reversed(parts)))
    except (AttributeError,ValueError):metrics['average_view_duration_seconds']='unavailable'
    return metrics


def api_coverage(rows,window):
    days=sorted({str(row['day']) for row in rows if row.get('day')})
    expected=[]
    if window and window.get('start') and window.get('end'):
        start=date.fromisoformat(window['start']);end=date.fromisoformat(window['end'])
        expected=[str(start+timedelta(days=i)) for i in range(max(0,(end-start).days+1))]
    return {'requested_window':window,'returned_rows':len(rows),
        'observed_start':days[0] if days else 'unavailable',
        'observed_end':days[-1] if days else 'unavailable','returned_days':len(days),
        'requested_end_returned':bool(days and window and days[-1]==window['end']),
        'missing_dates':sorted(set(expected)-set(days)),
        'all_requested_days_returned':bool(expected and set(expected)<=set(days)),
        'interpretation':'Only returned days are observed; missing dates are not assumed zero or complete.'}


def studio_period(files):
    dates=[]
    for rows in files.values():
        for row in rows:
            value=row.get('日期') or row.get('Date') or row.get('date')
            if value:
                try:dates.append(date.fromisoformat(value.strip()[:10]))
                except ValueError:pass
    return {'start':str(min(dates)),'end':str(max(dates)),
        'complete_days':len(set(dates)), 'span_days':(max(dates)-min(dates)).days+1} if dates else None


def studio_screenshot_window(sources):
    # Screenshots remain 28d even when a 7d ZIP was uploaded first.
    return (next((period for period in sources.get('studio_windows', {}).values()
        if period and period.get('span_days', period.get('complete_days'))==28), None)
        or sources.get('windows', {}).get('28')
        or sources.get('fact_snapshot', {}).get('data_windows', {}).get('recent_28d')
        or {})


def studio_content_type(row,identity):
    value=str(row.get('内容类型') or row.get('Content type') or '').strip().lower()
    if value in {'帖子','社区帖子','post','posts','community post','community posts'} or (not value and str(identity).startswith('Ug') and len(str(identity))>11):
        return 'post'
    if not value or value in {'视频','长视频','短视频','直播','video','videos','short','shorts','live','live stream'}:
        return 'video'
    return 'unknown'


def normalize_studio_export(asset_id,files):
    totals='unavailable';weighted='unavailable';content=[]
    for filename,rows in files.items():
        if '表格' in filename or 'table' in filename.lower():
            denominator=numerator=0.0
            for row in rows:
                # Ignore the aggregate row; never count it along with individual videos.
                identity=row.get('内容') or row.get('视频 ID') or row.get('Content') or row.get('Video') or row.get('Video ID')
                if identity in {'总计','Total','Totals'}:
                    totals={'source':asset_id+'/'+filename,'scope':'studio_exported_content',
                        'filter':'ZIP does not record the UI content-type filter; do not relabel as all-content',
                        'values':dict(row),'metrics':studio_metrics(row)}
                    continue
                if not identity:continue
                kind=studio_content_type(row,identity)
                content.append({'video_id':identity,'content_type':kind,'source':asset_id+'/'+filename,
                    'scope':'exported_content_row','values':dict(row),'metrics':studio_metrics(row)})
                impressions=number(studio_metrics(row)['impressions'])
                ctr=number(studio_metrics(row)['ctr_percent'])
                if kind=='video' and impressions is not None and ctr is not None and impressions>=0:
                    denominator+=impressions;numerator+=impressions*ctr
            if denominator:weighted={'value_percent':numerator/denominator,'impressions':denominator,
                'source':asset_id+'/'+filename,'scope':'exported_video_rows_only'}
    if isinstance(totals,dict) and totals['metrics']['returning_viewers']==0 and any(
        (number(row['metrics']['returning_viewers']) or 0)>0 for row in content):
        totals['metrics']['returning_viewers']='unavailable'
        totals['returning_viewers_issue']='Export aggregate reports zero while individual rows have returning viewers; aggregate zero is not trustworthy, and rows must not be summed.'
    return {'totals':totals,'impression_weighted_ctr':weighted,'content':content}


def normalize_sources(sources,channel,mode):
    api=sources.get('api',{})
    records={}
    if mode=='periodic':
        for key,dataset in api.items():
            rows=[]
            for page in dataset.get('pages',[]):
                names=[h['name'] for h in page.get('columnHeaders',[])]
                rows.extend(dict(zip(names,row)) for row in page.get('rows',[]))
            records[key]={'status':dataset['status'],'rows':rows,'window':dataset.get('window'),'reason':dataset.get('reason'),
                'coverage':api_coverage(rows,dataset.get('window')) if key.endswith(':daily') else {'returned_rows':len(rows),'requested_window':dataset.get('window'),'completeness':'not established from returned rows'}}
    totals='unavailable';weighted='unavailable';content=[];short={}
    long_window=next((studio_period(files) for files in sources.get('studio',{}).values()
        if (studio_period(files) or {}).get('span_days')==28),None)
    for asset_id,files in sources.get('studio',{}).items():
        period=studio_period(files)
        normalized=normalize_studio_export(asset_id,files)
        if period and period['span_days']==7:
            for row in normalized['content']:
                row['duration_seconds']=row['metrics']['duration_seconds']
                row['published_at']=row['values'].get('视频发布时间',row['values'].get('Video publish time'))
                annotate_video_comparability(row,period['end'])
            if not long_window:continue
            offset=(date.fromisoformat(long_window['end'])-date.fromisoformat(period['end'])).days
            if offset not in (0,7):continue
            short['recent_7d' if offset==0 else 'previous_7d']={
                'status':'available','window':period,'source':'studio/'+asset_id,
                'scope':'studio_exported_content',
                'filter_verification':sources.get('studio_provenance',{}).get(asset_id,{}).get('filter_verification','unavailable'),
                'filter_scope':sources.get('studio_provenance',{}).get(asset_id,{}).get('filter_scope'),
                'provenance':sources.get('studio_provenance',{}).get(asset_id,{}),
                'filter_note':'ZIP does not record UI filters; any confirmation is user supplied, not program verification',
                **normalized}
        else:
            totals=normalized['totals'];weighted=normalized['impression_weighted_ctr'];content.extend(normalized['content'])
    for role in ('recent_7d','previous_7d'):
        short.setdefault(role,{'status':'unavailable','reason':'未提供或未找到该周期的完整 Studio 导出；不能使用28天CTR代替'})
    derived=[]
    for record in records.get('28:videos',{}).get('rows',[]):
        views=number(record.get('views'));minutes=number(record.get('estimatedMinutesWatched'))
        subscribers=number(record.get('subscribersGained'))
        derived.append({'video_id':record.get('video'),'scope':'analytics_video_28d',
            'average_view_duration_minutes':minutes/views if views and minutes is not None else 'unavailable',
            'subscriber_gain_per_1000_views':subscribers/views*1000 if views and subscribers is not None else 'unavailable'})
    return {'channel':channel,'mode':mode,'channel_totals_28d':totals,'derived_video_metrics':derived,
        'impression_weighted_ctr':weighted,'studio_content':content,'api_datasets':records,'windows':sources.get('windows',{}),
        'studio_windows':sources.get('studio_windows',{}),'studio_short_windows':short,'unavailable_is_not_zero':True}


def short_window_comparison(windows):
    """Compare source totals; do not average video CTRs or invent a missing baseline."""
    def metrics(role):
        totals=windows.get(role,{}).get('totals')
        return totals.get('metrics',{}) if isinstance(totals,dict) else {}
    recent,previous=metrics('recent_7d'),metrics('previous_7d')
    comparison={'scope':'Studio exported-content totals; same UI filter must be confirmed',
        'recent_source':windows.get('recent_7d',{}).get('source','unavailable'),
        'previous_source':windows.get('previous_7d',{}).get('source','unavailable')}
    for metric in ('views','impressions','watch_hours','subscribers_net','subscribers_gained'):
        current,prior=number(recent.get(metric)),number(previous.get(metric))
        comparison[metric+'_change_pct']=(current-prior)/prior*100 if current is not None and prior is not None and prior>0 else 'unavailable'
    for metric,key in (('ctr_percent','ctr_change_pp'),('average_percentage_viewed','apv_change_pp')):
        current,prior=number(recent.get(metric)),number(previous.get(metric))
        comparison[key]=current-prior if current is not None and prior is not None else 'unavailable'
    return comparison


def api_short_comparison(datasets):
    result={'scope':'API daily rows; only complete equal-length seven-day windows are compared'}
    pair=[datasets.get(key+':daily',{}) for key in ('7','previous7')]
    complete=all(d.get('status')=='available' and d.get('coverage',{}).get('all_requested_days_returned')
        and d.get('coverage',{}).get('returned_days')==7 for d in pair)
    result['status']='available' if complete else 'unavailable'
    for field in ('views','estimatedMinutesWatched','subscribersGained','subscribersLost'):
        totals=[]
        for dataset in pair:
            values=[number(row.get(field)) for row in dataset.get('rows',[])]
            totals.append(sum(values) if complete and values and all(v is not None for v in values) else None)
        current,prior=totals
        result[field]={'recent_7d':current if current is not None else 'unavailable',
            'previous_7d':prior if prior is not None else 'unavailable',
            'change_pct':(current-prior)/prior*100 if current is not None and prior is not None and prior>0 else 'unavailable'}
    return result


def annotate_video_comparability(row,end):
    duration=number(row.get('duration_seconds'))
    row['duration_class']='up_to_3_minutes' if duration is not None and duration<=180 else 'over_3_minutes' if duration is not None else 'unavailable'
    published=row.get('published_at') or ''
    parsed=None
    for fmt in ('%b %d, %Y','%Y-%m-%d'):
        try:parsed=datetime.strptime(published[:10] if fmt=='%Y-%m-%d' else published,fmt).date();break
        except (ValueError,TypeError):pass
    days=(date.fromisoformat(end)-parsed).days if parsed and end else None
    row['complete_days_since_publish']=days if days is not None else 'unavailable'
    row['maturity']='mature_7_complete_days' if days is not None and days>=7 else 'early' if days is not None else 'unavailable'
    return row


def validate_screenshot_observations(checks):
    for check in checks.values():
        observations=check.get('observations',[])
        if not isinstance(observations,list):raise ValueError('截图 observations 必须为列表')
        for item in observations:
            if not isinstance(item,dict) or item.get('status') not in {'available','unavailable','not_applicable'}:
                raise ValueError('截图指标缺少可用性状态')
            for key in ('metric','scope','window','evidence','unit'):
                if not isinstance(item.get(key),str) or not item[key].strip():raise ValueError('截图指标缺少来源依据、口径或周期')
            value=item.get('value')
            if item['status']=='available':
                if isinstance(value,bool) or not isinstance(value,(str,int,float)) or (isinstance(value,(int,float)) and not math.isfinite(value)):
                    raise ValueError('截图可用指标必须有可读值')
            elif value is not None:raise ValueError('截图缺失指标不能填零或猜测值')


def observation_window_coverage(window,formal_window):
    """Card-specific evidence must not inherit the page's top-level date filter."""
    if re.search(r'过去\s*(?:7|90|365)\s*天|自发布以来|现在|实时|since publish|lifetime|last (?:7|90|365) days',window,re.I):
        return {'matches_formal_window':False,'within_formal_window':None}
    dates=re.findall(r'20\d{2}[-/]\d{1,2}[-/]\d{1,2}',window)
    try:dates=[datetime.strptime(value.replace('/','-'),'%Y-%m-%d').date().isoformat() for value in dates]
    except ValueError:dates=[]
    if len(dates)==2 and dates[0]<=dates[1] and formal_window.get('start') and formal_window.get('end'):
        return {'matches_formal_window':dates==[formal_window['start'],formal_window['end']],
            'within_formal_window':formal_window['start']<=dates[0]<=dates[1]<=formal_window['end']}
    return {'matches_formal_window':None,'within_formal_window':None}


def formal_snapshot(sources, channel):
    """Freeze measured facts using source-scoped arithmetic, not model output."""
    from datetime import datetime, timezone
    normalized = sources['normalized']
    datasets = normalized['api_datasets']
    def dataset(key):
        value = datasets.get(key, {})
        return {'status': value.get('status', 'unavailable'), 'source': 'api/' + key,
                'window': value.get('window'), 'reason':value.get('reason'), 'rows': value.get('rows', []), 'coverage':value.get('coverage')}
    api_videos = dataset('28:videos')
    studio_window = studio_screenshot_window(sources)
    studio_rows=[{'video':row['video_id'],**row['metrics'],'source':row['source'],
        'scope':row['scope'],'published_at':row['values'].get('视频发布时间',row['values'].get('Video publish time'))}
        for row in normalized['studio_content'] if row.get('content_type','video')=='video' and number(row['metrics']['views']) is not None]
    videos={'status':'available','source':'studio/content_table','scope':'exported_video_rows',
        'window':studio_window,'rows':studio_rows} if studio_rows else api_videos
    for row in videos['rows']:annotate_video_comparability(row,sources['windows']['28'].get('end'))
    ranked=sorted([row for row in videos['rows'] if number(row.get('views')) is not None],key=lambda row:number(row['views']),reverse=True)
    total=sum(number(row['views']) for row in ranked) if ranked and videos['status']=='available' else None
    # Three disjoint relative performance bands, not repeated top-N lists.
    width=max(1,len(ranked)//3)
    top=ranked[:width];low=ranked[max(width,len(ranked)-width):]
    middle=ranked[width:max(width,len(ranked)-width)]
    traffic = dataset('28:traffic')
    traffic_rows=[row for row in traffic['rows'] if number(row.get('views')) is not None]
    traffic_total = sum(number(row['views']) for row in traffic_rows)
    traffic = {**traffic, 'scope': 'analytics_traffic_views', 'shares_percent': [
        {'source_type': row.get('insightTrafficSourceType'),
         'value': (number(row.get('views')) or 0) / traffic_total * 100}
        for row in traffic_rows] if traffic_total else 'unavailable'}
    screenshots = sources.get('screenshots', [])
    def screenshot_domain(kind,retention_only=False):
        ids = [m['id'] for m in screenshots if m['kind'] == kind]
        observations=[{**item,'source':'screenshot/'+material['id'],'extraction':'visual_transcription',**observation_window_coverage(item['window'],studio_window)}
            for material in screenshots if material['kind']==kind
            for item in sources.get('screenshot_checks',{}).get(material['id'],{}).get('observations',[]) if not retention_only or item['metric'].startswith('retention')]
        if observations:return {'status':'available','source':'Studio screenshot','scope':'per-card scopes retained below','observations':observations,'screenshot_ids':ids}
        return {'status': 'unavailable', 'reason': '截图结构化读取尚未完成；不把缺失值记为0',
                'screenshot_ids': ids} if ids else 'not_applicable' if kind in {'posts','ab'} else 'unavailable'
    comparable={}
    for row in ranked:comparable.setdefault(row['duration_class']+'/'+row['maturity'],[]).append(row)
    details = {item['id']: item for group in sources.get('video_details', {}).values()
               for item in group.get('response', {}).get('items', [])}
    mapped = {row['youtube_video_id'] for row in sources.get('video_drama_mapping', []) if row.get('drama_code') or row.get('local_metadata_source')}
    return {'schema_version': 2, 'snapshot_status': 'measured_with_explicit_gaps',
        'generated_at': datetime.now(timezone.utc).isoformat(), 'channel': channel,
        'channel_public_data': {'status':'available' if sources.get('identity',{}).get('items') else 'unavailable','source':'youtube-data/channels.list(mine=true)','scope':'channel lifetime public statistics at collection time','identity':sources.get('identity',{}).get('items',[])},
        'data_windows': {'recent_28d': sources['windows']['28'], 'recent_90d': sources['windows']['90'],
            **{role:window for role,key in (('recent_7d','7'),('previous_7d','previous7'))
                if (window:=sources.get('windows',{}).get(key))}},
        'availability_rules': ['unavailable is not zero', 'Studio exported-content and API video scopes stay separate'],
        'channel_totals_28d': normalized['channel_totals_28d'],
        'trend': {'recent_28d': dataset('28:daily'), 'recent_90d': dataset('90:daily'),
            'recent_7d':dataset('7:daily'),'previous_7d':dataset('previous7:daily')},
        'studio_short_windows': normalized['studio_short_windows'],
        'short_window_comparison': short_window_comparison(normalized['studio_short_windows']),
        'api_short_window_comparison':api_short_comparison(datasets),
        'api_observed_end':sources.get('api_observed_end','unavailable'),
        'traffic_7d':dataset('7:traffic'), 'traffic_previous_7d':dataset('previous7:traffic'),
        'api_videos_7d':dataset('7:videos'), 'api_videos_previous_7d':dataset('previous7:videos'),
        'audience_28d': {'country': dataset('28:country'), 'device': dataset('28:device'),
                         'studio_segments': screenshot_domain('audience')},
        'traffic_28d_video_pct': traffic, 'retention_intro_30s_pct': screenshot_domain('videos',True),'video_page_cards':screenshot_domain('videos'),
        'top_videos_28d': {**videos, 'rows':top,'cohort':'upper relative view band; maturity must be considered separately'},
        'low_videos_28d': {**videos, 'rows':list(reversed(low)),'cohort':'lower relative view band; not automatically mature weak content'},
        'middle_videos_28d': {**videos, 'rows':middle,'cohort':'middle relative view band'},
        'comparable_video_groups':comparable,
        'video_metric_coverage': {'ranking_source':videos['source'],'ranking_scope':videos.get('scope'),'exported_content_rows':len(normalized['studio_content']),'studio_rows':sum(row.get('content_type','video')=='video' for row in normalized['studio_content']),'ranked_studio_rows':len(studio_rows),'unranked_studio_ids':[row['video_id'] for row in normalized['studio_content'] if row.get('content_type','video')=='video' and number(row['metrics']['views']) is None],'api_rows':len(api_videos['rows']),'api_daily_coverage':dataset('28:daily').get('coverage'),'ranked_view_sum':total,'studio_aggregate_views':normalized['channel_totals_28d']['metrics']['views'] if isinstance(normalized['channel_totals_28d'],dict) else 'unavailable'},
        'api_video_sample':api_videos,
        'concentration_28d': {'scope':videos.get('scope','analytics_video_rows_only'), 'source':videos['source'],
            'total_views': total, 'top_1_share_pct': (number(ranked[0].get('views')) or 0)/total*100 if total else 'unavailable',
            'top_5_share_pct': sum(number(row['views']) for row in ranked[:5])/total*100 if total else 'unavailable'} if total is not None else 'unavailable',
        'community_posts': {'screenshot':screenshot_domain('posts'),'studio_rows':[row for row in normalized['studio_content'] if row.get('content_type')=='post']} if any(row.get('content_type')=='post' for row in normalized['studio_content']) else screenshot_domain('posts'), 'ab_testing': screenshot_domain('ab'),
        'impression_weighted_ctr': normalized['impression_weighted_ctr'],
        'studio_content': normalized['studio_content'],
        'derived_video_metrics': normalized['derived_video_metrics'],
        'video_inventory': list(details.values()),
        'video_source_coverage':[{'video_id':row['video_id'],'in_studio':True,'in_api_video_rows':row['video_id'] in {v.get('video') for v in api_videos['rows']},'in_inventory':row['video_id'] in details} for row in normalized['studio_content'] if row.get('content_type','video')=='video'],
        'video_inventory_coverage': {k:v for k,v in sources.get('uploads_inventory',{}).items() if k!='pages'},
        'video_detail_gaps': [{'source':key,'reason':group.get('reason')} for key,group in sources.get('video_details',{}).items() if group.get('status')!='available'],
        'unmatched_video_ids': sorted(set(details) - mapped),
        'source_manifest': [{'source': 'api/' + key, 'status': value['status'], 'window': value.get('window'),'reason':value.get('reason'),'coverage':value.get('coverage')}
                            for key, value in datasets.items()] +
            [{'source': 'studio/' + key, 'window': value,'provenance':sources.get('studio_provenance',{}).get(key,{})} for key, value in sources.get('studio_windows', {}).items()] +
            [{'source': 'screenshot/' + m['id'], 'kind': m['kind']} for m in screenshots]}
