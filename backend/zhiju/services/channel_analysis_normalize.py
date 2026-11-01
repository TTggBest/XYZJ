"""Source-scoped arithmetic; absent values are never numeric zero."""
from datetime import date


def number(value):
    try:return float(str(value).replace(',','').replace('%','').strip())
    except (ValueError,TypeError):return None


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


def normalize_sources(sources,channel,mode):
    api=sources.get('api',{})
    records={}
    if mode=='periodic':
        for key,dataset in api.items():
            rows=[]
            for page in dataset.get('pages',[]):
                names=[h['name'] for h in page.get('columnHeaders',[])]
                rows.extend(dict(zip(names,row)) for row in page.get('rows',[]))
            records[key]={'status':dataset['status'],'rows':rows,'window':dataset.get('window'),'reason':dataset.get('reason')}
    totals='unavailable';weighted='unavailable';content=[]
    for asset_id,files in sources.get('studio',{}).items():
        for filename,rows in files.items():
            if '总计' in filename or 'totals' in filename.lower():
                if rows:totals={'source':asset_id+'/'+filename,'scope':'all_content','values':rows[0]}
            if '表格' in filename or 'table' in filename.lower():
                denominator=numerator=0.0
                for row in rows:
                    # Ignore the aggregate row; never count it along with individual videos.
                    identity=row.get('内容') or row.get('视频 ID') or row.get('Content') or row.get('Video') or row.get('Video ID')
                    if not identity or identity in {'总计','Total','Totals'}:continue
                    content.append({'video_id':identity,'source':asset_id+'/'+filename,
                        'scope':'exported_content_row','values':dict(row)})
                    impressions=number(row.get('展示次数',row.get('Impressions')))
                    ctr=number(row.get('展示点击率 (%)',row.get('Impressions click-through rate (%)')))
                    if impressions is not None and ctr is not None and impressions>=0:
                        denominator+=impressions;numerator+=impressions*ctr
                if denominator:weighted={'value_percent':numerator/denominator,'impressions':denominator,
                    'source':asset_id+'/'+filename,'scope':'exported_content_rows_only'}
    derived=[]
    for record in records.get('28:videos',{}).get('rows',[]):
        views=number(record.get('views'));minutes=number(record.get('estimatedMinutesWatched'))
        subscribers=number(record.get('subscribersGained'))
        derived.append({'video_id':record.get('video'),'scope':'analytics_video_28d',
            'average_view_duration_minutes':minutes/views if views and minutes is not None else 'unavailable',
            'subscriber_gain_per_1000_views':subscribers/views*1000 if views and subscribers is not None else 'unavailable'})
    return {'channel':channel,'mode':mode,'channel_totals_28d':totals,'derived_video_metrics':derived,
        'impression_weighted_ctr':weighted,'studio_content':content,'api_datasets':records,'windows':sources.get('windows',{}),
        'studio_windows':sources.get('studio_windows',{}),'unavailable_is_not_zero':True}


def formal_snapshot(sources, channel):
    """Freeze measured facts using source-scoped arithmetic, not model output."""
    from datetime import datetime, timezone
    normalized = sources['normalized']
    datasets = normalized['api_datasets']
    def dataset(key):
        value = datasets.get(key, {})
        return {'status': value.get('status', 'unavailable'), 'source': 'api/' + key,
                'window': value.get('window'), 'reason':value.get('reason'), 'rows': value.get('rows', [])}
    videos = dataset('28:videos')
    ranked = sorted([row for row in videos['rows'] if number(row.get('views')) is not None],
                    key=lambda row: number(row['views']), reverse=True)
    # Per-video coverage is explicitly separate from all-content Studio totals.
    total = sum(number(row['views']) for row in ranked) if ranked and videos['status']=='available' else None
    traffic = dataset('28:traffic')
    traffic_rows=[row for row in traffic['rows'] if number(row.get('views')) is not None]
    traffic_total = sum(number(row['views']) for row in traffic_rows)
    traffic = {**traffic, 'scope': 'analytics_traffic_views', 'shares_percent': [
        {'source_type': row.get('insightTrafficSourceType'),
         'value': (number(row.get('views')) or 0) / traffic_total * 100}
        for row in traffic_rows] if traffic_total else 'unavailable'}
    screenshots = sources.get('screenshots', [])
    def screenshot_domain(kind):
        ids = [m['id'] for m in screenshots if m['kind'] == kind]
        return {'status': 'unavailable', 'reason': '截图可供报告视觉分析；未形成程序可核实的数值',
                'screenshot_ids': ids} if ids else 'not_applicable' if kind in {'posts','ab'} else 'unavailable'
    details = {item['id']: item for group in sources.get('video_details', {}).values()
               for item in group.get('response', {}).get('items', [])}
    mapped = {row['youtube_video_id'] for row in sources.get('video_drama_mapping', []) if row.get('drama_code')}
    return {'schema_version': 2, 'snapshot_status': 'measured_with_explicit_gaps',
        'generated_at': datetime.now(timezone.utc).isoformat(), 'channel': channel,
        'data_windows': {'recent_28d': sources['windows']['28'], 'recent_90d': sources['windows']['90']},
        'availability_rules': ['unavailable is not zero', 'Studio all-content and API video scopes stay separate'],
        'channel_totals_28d': normalized['channel_totals_28d'],
        'trend': {'recent_28d': dataset('28:daily'), 'recent_90d': dataset('90:daily')},
        'audience_28d': {'country': dataset('28:country'), 'device': dataset('28:device'),
                         'studio_segments': screenshot_domain('audience')},
        'traffic_28d_video_pct': traffic, 'retention_intro_30s_pct': screenshot_domain('videos'),
        'top_videos_28d': {**videos, 'rows': ranked[:10]},
        'low_videos_28d': {**videos, 'scope':'lowest within returned API video rows', 'rows': list(reversed(ranked[-10:]))},
        'middle_videos_28d': {**videos, 'rows':ranked[max(0,len(ranked)//2-2):len(ranked)//2+3]},
        'video_metric_coverage': 'API returned video rows; if 200 rows, weak cohort is relative to returned top 200, not all uploads',
        'concentration_28d': {'scope': 'analytics_video_rows_only', 'source': 'api/28:videos',
            'total_views': total, 'top_1_share_pct': (number(ranked[0].get('views')) or 0)/total*100 if total else 'unavailable',
            'top_5_share_pct': sum(number(row['views']) for row in ranked[:5])/total*100 if total else 'unavailable'} if total is not None else 'unavailable',
        'community_posts': screenshot_domain('posts'), 'ab_testing': screenshot_domain('ab'),
        'impression_weighted_ctr': normalized['impression_weighted_ctr'],
        'studio_content': normalized['studio_content'],
        'derived_video_metrics': normalized['derived_video_metrics'],
        'video_inventory': list(details.values()),
        'video_inventory_coverage': {k:v for k,v in sources.get('uploads_inventory',{}).items() if k!='pages'},
        'video_detail_gaps': [{'source':key,'reason':group.get('reason')} for key,group in sources.get('video_details',{}).items() if group.get('status')!='available'],
        'unmatched_video_ids': sorted(set(details) - mapped),
        'source_manifest': [{'source': 'api/' + key, 'status': value['status'], 'window': value.get('window'),'reason':value.get('reason')}
                            for key, value in datasets.items()] +
            [{'source': 'studio/' + key, 'window': value} for key, value in sources.get('studio_windows', {}).items()] +
            [{'source': 'screenshot/' + m['id'], 'kind': m['kind']} for m in screenshots]}
