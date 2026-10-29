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
        'complete_days':(max(dates)-min(dates)).days+1} if dates else None


def normalize_sources(sources,channel,mode):
    api=sources.get('api',{})
    records={}
    if mode=='periodic':
        for key,dataset in api.items():
            rows=[]
            for page in dataset.get('pages',[]):
                names=[h['name'] for h in page.get('columnHeaders',[])]
                rows.extend(dict(zip(names,row)) for row in page.get('rows',[]))
            records[key]={'status':dataset['status'],'rows':rows,'window':dataset.get('window')}
    totals='unavailable';weighted='unavailable'
    for asset_id,files in sources.get('studio',{}).items():
        for filename,rows in files.items():
            if '总计' in filename or 'totals' in filename.lower():
                if rows:totals={'source':asset_id+'/'+filename,'scope':'all_content','values':rows[0]}
            if '表格' in filename or 'table' in filename.lower():
                denominator=numerator=0.0
                for row in rows:
                    # Ignore the aggregate row; never count it along with individual videos.
                    identity=row.get('内容') or row.get('视频 ID') or row.get('Content') or row.get('Video')
                    if not identity or identity in {'总计','Total','Totals'}:continue
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
        'impression_weighted_ctr':weighted,'api_datasets':records,'windows':sources.get('windows',{}),
        'studio_windows':sources.get('studio_windows',{}),'unavailable_is_not_zero':True}
