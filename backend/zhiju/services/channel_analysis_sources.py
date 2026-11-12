"""Read-only Google collection and native Studio archive normalization."""
import csv
import io
import copy
import json
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from zipfile import ZipFile, BadZipFile
from sqlalchemy import select
from zhiju.models import (AccountChannelAuthorization, OAuthGrant, OAuthGrantScope, Drama, YoutubeVideo,
                         YoutubeChannelDailyMetric, ChannelAnalysisRun)
from zhiju.config import get_settings
from zhiju.services.identity import ConflictError
from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired, choose_youtube_channel
from zhiju.services.oauth_secret_store import EncryptedDatabaseSecretStore
from zhiju.services.youtube_channel_sync import ensure_grant_access_token, _youtube_request_json, _api_url
from zhiju.services.channel_analysis import claimed, material_path
from zhiju.services.channel_analysis_normalize import studio_period, normalize_sources, STUDIO_COLUMNS


def parse_studio_zip(content):
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            csvs=[x for x in archive.infolist() if x.filename.lower().endswith('.csv')]
            if not csvs or sum(x.file_size for x in csvs)>64*1024*1024:
                raise ValueError('ZIP 中没有 CSV 或解压 CSV 超过 64MB')
            result={}
            for entry in csvs:
                data=archive.read(entry).decode('utf-8-sig')
                result[entry.filename]=list(csv.DictReader(io.StringIO(data)))
            headings={key for rows in result.values() for row in rows for key in row}
            if not headings.intersection({'内容','视频 ID','Content','Video','Video ID'}):
                raise ValueError('未识别到原生 Studio 内容/视频表')
            period=studio_period(result)
            if not period or period['span_days'] not in (7,28) or period['complete_days']!=period['span_days']:
                raise ValueError('必须提供带连续实际日期的7天或28天内容导出')
            return result
    except (BadZipFile,UnicodeError,ValueError,RuntimeError) as exc:
        raise ConflictError('无法读取 Studio 内容导出 ZIP：'+str(exc)) from exc


def studio_metric_columns(files):
    headings={key for name,rows in files.items() if '表格' in name or 'table' in name.lower()
        for row in rows for key in row}
    columns={key for key,names in STUDIO_COLUMNS.items() if headings.intersection(names)}
    known={name for names in STUDIO_COLUMNS.values() for name in names}
    known.update({'平均观看时长','Average view duration'})
    metadata={'内容','视频 ID','Content','Video','Video ID','视频标题','Video title','视频发布时间','Video publish time','发布日期','Publish date','内容类型','Content type'}
    columns.update('studio_column:'+name for name in headings-known-metadata)
    if headings.intersection({'平均观看时长','Average view duration'}):columns.add('average_view_duration_seconds')
    return columns


def validate_studio_exports(studio, *, require_recent_7d):
    """Use CSV dates, never upload order or ZIP filenames, to identify each window."""
    windows={key:studio_period(files) for key,files in studio.items()}
    long=[key for key,period in windows.items() if period and period['span_days']==28]
    if len(long)!=1:raise ConflictError('需要且只能提供一份28天 Studio 内容导出')
    long_id=long[0];end=date.fromisoformat(windows[long_id]['end'])
    roles={'recent_28d':long_id}
    for key,period in windows.items():
        if key==long_id:continue
        if not period or period['span_days']!=7:raise ConflictError('其他 Studio 导出必须为完整7天')
        offset=(end-date.fromisoformat(period['end'])).days
        if offset not in (0,7):raise ConflictError('最近7天与28天截止日必须一致；可选前7天截止日应恰好提前7天')
        role='recent_7d' if offset==0 else 'previous_7d'
        if role in roles:raise ConflictError('同一周期只能提供一份 Studio 导出')
        roles[role]=key
    if require_recent_7d and 'recent_7d' not in roles:
        raise ConflictError('缺少最近7天 Studio 内容导出，请与28天导出使用相同截止日和指标')
    if len(roles)>1:
        columns=studio_metric_columns(studio[long_id])
        if not {'views','impressions','ctr_percent'}<=columns:
            raise ConflictError('Studio 导出指标必须包含观看次数、缩略图展示次数和点击率')
        for role,key in roles.items():
            if studio_metric_columns(studio[key])!=columns:
                raise ConflictError('7天与28天内容导出的指标列不一致，请使用相同指标重新导出')
    return roles



def reuse_previous_studio(session,run,sources):
    """Reuse an original export only with exact dates, metrics and user-confirmed filters."""
    roles=sources['studio_roles']
    if 'previous_7d' in roles:return
    current_id=roles.get('recent_7d')
    current=next((m for m in run.materials if m['id']==current_id),{})
    scope=current.get('filter_scope')
    if not scope or current.get('filter_verification')!='user_confirmed':return
    target=date.fromisoformat(sources['studio_windows'][current_id]['end'])-timedelta(days=7)
    columns=studio_metric_columns(sources['studio'][current_id])
    ids=session.scalars(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==run.channel_id,
        ChannelAnalysisRun.id!=run.id,ChannelAnalysisRun.status.in_(['ready','applied','superseded']))
        .order_by(ChannelAnalysisRun.created_at.desc()))
    for previous_id in ids:
        previous=session.get(ChannelAnalysisRun,previous_id)
        for item in previous.materials:
            if item['kind']!='studio_zip' or item.get('filter_scope')!=scope or item.get('filter_verification')!='user_confirmed':continue
            period=item.get('period') or {}
            if period.get('span_days')!=7 or period.get('end')!=str(target):continue
            path=material_path(previous,item['id'])
            if not path.is_file():continue
            files=parse_studio_zip(path.read_bytes())
            actual=studio_period(files)
            if actual!=period or studio_metric_columns(files)!=columns:continue
            key='reused:'+previous.id+':'+item['id']
            sources['studio'][key]=files;sources['studio_windows'][key]=actual
            sources['studio_provenance'][key]={**item,'reused_from':{'run_id':previous.id,'material_id':item['id']}}
            sources['studio_roles']['previous_7d']=key
            return


def verify_authorization(session,channel,fetcher=_youtube_request_json):
    auth=session.scalar(select(AccountChannelAuthorization).where(
        AccountChannelAuthorization.channel_id==channel['id'],AccountChannelAuthorization.status=='active',
        AccountChannelAuthorization.verified_youtube_channel_id==channel['youtube_channel_id']
    ).order_by(AccountChannelAuthorization.verified_at.desc()).limit(1))
    if not auth:raise YouTubeAuthorizationRequired('频道没有有效授权，请先授权')
    grant=session.get(OAuthGrant,auth.oauth_grant_id)
    if not grant or grant.status!='active':raise YouTubeAuthorizationRequired('频道授权已失效')
    scopes=set(session.scalars(select(OAuthGrantScope.scope).where(OAuthGrantScope.grant_id==grant.id)))
    if 'https://www.googleapis.com/auth/yt-analytics.readonly' not in scopes:
        raise YouTubeAuthorizationRequired('缺少频道 Analytics 读取权限，请重新授权')
    token=ensure_grant_access_token(session,EncryptedDatabaseSecretStore(session,get_settings().oauth_encryption_key),grant)
    profile=fetcher(_api_url('channels',part='snippet,statistics,contentDetails',mine='true',maxResults=50),token)
    if len(profile.get('items',[]))!=1:raise ConflictError('授权返回的频道不唯一')
    try:verified=choose_youtube_channel(profile,expected_channel_id=channel['youtube_channel_id'])
    except ValueError as exc:raise ConflictError('授权频道与当前频道不一致，请重新授权正确频道') from exc
    if verified['snippet']['title']!=channel['original_name']:
        raise ConflictError('YouTube 频道名称已变化，请先确认频道身份再分析')
    return token,profile,verified


def collect(session,run_id,claim_id,fetcher=_youtube_request_json):
    run=claimed(session,run_id,claim_id)
    if run.input_snapshot.get('cold_start'):
        from zhiju.services.channel_analysis import cold_start_snapshot,assert_no_measured_report,verify_cold_start_authorization
        verify_cold_start_authorization(session,run.channel_id,run.input_snapshot['channel']['youtube_channel_id'])
        assert_no_measured_report(session,run.channel_id)
        if run.input_snapshot.get('sources_complete'):return run
        snapshot=dict(run.input_snapshot)
        if not snapshot['channel'].get('default_language') or not snapshot['channel'].get('country_name_zh'):
            raise ConflictError('冷启动资料缺少目标语言或市场，请补充后重试')
        snapshot['sources']={'api':{'status':'not_applicable','reason':'channel-initial-audience 无 Analytics 冷启动'},
            'normalized':cold_start_snapshot(snapshot['channel'],snapshot['initial_facts'])}
        snapshot['sources_complete']=True;run.input_snapshot=snapshot;run.phase='analysis'
        session.commit();return run
    if run.input_snapshot.get('sources_complete'):
        if run.mode=='periodic':
            from zhiju.services.channel_analysis_normalize import formal_snapshot
            snapshot=copy.deepcopy(run.input_snapshot)
            snapshot['sources']['normalized']=normalize_sources(snapshot['sources'],snapshot['channel'],run.mode)
            facts=formal_snapshot(snapshot['sources'],snapshot['channel'])
            previous=snapshot['sources'].get('fact_snapshot',{})
            if previous.get('generated_at'):facts['generated_at']=previous['generated_at']
            snapshot['sources']['fact_snapshot']=facts
            snapshot['normalization_revision']=5 if snapshot.get('studio_input_contract') else 4;run.input_snapshot=snapshot
            session.commit()
        return run
    snapshot=dict(run.input_snapshot);channel=snapshot['channel']
    sources=snapshot.get('sources') or {}
    def checkpoint():
        claimed(session,run_id,claim_id)
        run.input_snapshot={**snapshot,'sources':json.loads(json.dumps(sources))}
        session.commit()
    if run.mode=='periodic':
        token,profile,verified=verify_authorization(session,channel,fetcher)
        # YouTube Analytics calendar days follow Pacific time, including DST.
        created=date.fromisoformat(verified['snippet']['publishedAt'][:10])
        sources['identity']=profile;sources.setdefault('api',{})
        sources['studio']={m['id']:parse_studio_zip(material_path(run,m['id']).read_bytes())
            for m in run.materials if m['kind']=='studio_zip'}
        sources['studio_windows']={key:studio_period(value) for key,value in sources['studio'].items()}
        last_complete=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=1)
        sources['studio_roles']=validate_studio_exports(sources['studio'],
            require_recent_7d=7 in snapshot.get('studio_required_periods',[]))
        sources['studio_provenance']={m['id']:dict(m) for m in run.materials if m['kind']=='studio_zip'}
        if snapshot.get('studio_input_contract')=='dual-window-v1':reuse_previous_studio(session,run,sources)
        period=sources['studio_windows'][sources['studio_roles']['recent_28d']]
        studio_end=date.fromisoformat(period['end'])
        if studio_end>last_complete or (last_complete-studio_end).days>7:
            raise ConflictError('Studio 导出周期不是近期完整28天，请上传近期导出')
        if not sources.get('windows'):
            end=studio_end
            # Keep the Studio end date and clip the API start to channel creation.
            windows={}
            for days in (28,90):
                start=max(created,end-timedelta(days=days-1))
                if start>end:raise ConflictError('频道尚无完整运营日，请选择冷启动或稍后再分析')
                windows[str(days)]={'start':str(start),'end':str(end),'timezone':'America/Los_Angeles',
                    'complete_days':(end-start).days+1}
            sources['windows']=windows
            checkpoint()
        end=date.fromisoformat(sources['windows']['28']['end'])
        previous_id=session.scalar(select(ChannelAnalysisRun.id).where(ChannelAnalysisRun.channel_id==run.channel_id,
            ChannelAnalysisRun.id!=run.id,ChannelAnalysisRun.status.in_(['ready','applied','superseded']))
            .order_by(ChannelAnalysisRun.created_at.desc()).limit(1))
        previous=session.get(ChannelAnalysisRun,previous_id) if previous_id else None
        reusable=previous.input_snapshot.get('sources',{}).get('api',{}) if previous else {}
        dual=snapshot.get('studio_input_contract')=='dual-window-v1'
        for days in ((28,90,'7','previous7') if dual else (28,90)):
            if days=='7' and '7' not in sources['windows']:
                daily=sources['api'].get('28:daily',{})
                observed=[dict(zip([h['name'] for h in page.get('columnHeaders',[])],row)).get('day')
                    for page in daily.get('pages',[]) for row in page.get('rows',[])]
                observed=[value for value in observed if value and sources['windows']['28']['start']<=value<=str(end)]
                actual_end=date.fromisoformat(max(observed)) if observed else end
                sources['api_observed_end']={'requested_end':str(end),'observed_end':str(actual_end) if observed else 'unavailable',
                    'basis':'latest returned daily row; missing days are not zero','collected_at':datetime.now(timezone.utc).isoformat()}
                for name,stop in (('7',actual_end),('previous7',actual_end-timedelta(days=7))):
                    start=max(created,stop-timedelta(days=6))
                    sources['windows'][name]={'start':str(start),'end':str(stop),'timezone':'America/Los_Angeles',
                        'complete_days':max(0,(stop-start).days+1),'requested_days':7}
                checkpoint()
            window=sources['windows'][str(days)]
            start=date.fromisoformat(window['start'])
            specs=[('daily','day','views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,comments,shares','day'),
                ('videos','video','views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained','-views'),
                ('country','country','views,estimatedMinutesWatched','-views'),
                ('traffic','insightTrafficSourceType','views,estimatedMinutesWatched','-views'),
                ('device','deviceType','views,estimatedMinutesWatched','-views')]
            if dual:
                specs[0]=('daily','day','views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost','day')
                if days in ('7','previous7'):specs=[spec for spec in specs if spec[0] in {'daily','videos','traffic'}]
                else:specs.append(('daily_engagement','day','likes,comments,shares','day'))
            for name,dimension,metrics,sort in specs:
                key=f'{days}:{name}'
                if window['start']>window['end']:
                    sources['api'][key]={'status':'unavailable','reason':'频道创建日期晚于该窗口，不能构造运营数据','window':window}
                    continue
                cached=sources['api'].get(key) or reusable.get(key)
                if cached and cached.get('status')=='available' and cached.get('window')==window:
                    sources['api'][key]=cached
                    continue
                params={'ids':'channel==MINE','startDate':str(start),'endDate':window['end'],
                    'metrics':metrics,'dimensions':dimension,'sort':sort,'maxResults':200}
                try:
                    responses=[];offset=1
                    while True:
                        url='https://youtubeanalytics.googleapis.com/v2/reports?'+urlencode({**params,'startIndex':offset})
                        try:response=fetcher(url,token)
                        except ValueError:response=fetcher(url,token)
                        responses.append(response)
                        if len(response.get('rows',[]))<200:break
                        offset+=200
                    sources['api'][key]={'status':'available','window':window,'pages':responses,
                        'collected_at':datetime.now(timezone.utc).isoformat()}
                except (RuntimeError,ValueError) as exc:
                    sources['api'][key]={'status':'unavailable','reason':str(exc),'window':window}
                checkpoint()
        video_ids=set(session.scalars(select(YoutubeVideo.youtube_video_id).where(YoutubeVideo.channel_id==run.channel_id)))
        studio_rows=normalize_sources(sources,channel,run.mode)['studio_content']
        video_ids.update(row['video_id'] for row in studio_rows if row['content_type']=='video')
        for short in normalize_sources(sources,channel,run.mode)['studio_short_windows'].values():
            video_ids.update(row['video_id'] for row in short.get('content',[]) if row['content_type']=='video')
        uploads=verified.get('contentDetails',{}).get('relatedPlaylists',{}).get('uploads')
        if uploads and sources.get('uploads_inventory',{}).get('status')!='available':
            pages=[];page_token=None
            try:
                while True:
                    params={'part':'contentDetails','playlistId':uploads,'maxResults':50}
                    if page_token:params['pageToken']=page_token
                    page=fetcher(_api_url('playlistItems',**params),token);pages.append(page)
                    page_token=page.get('nextPageToken')
                    if not page_token:break
                sources['uploads_inventory']={'status':'available','pages':pages}
            except (ValueError,RuntimeError) as exc:
                sources['uploads_inventory']={'status':'unavailable','reason':str(exc),'pages':pages}
            checkpoint()
        if not uploads:
            sources['uploads_inventory']={'status':'unavailable','reason':'授权身份未返回 uploads 播放列表','pages':[]}
        for page in sources.get('uploads_inventory',{}).get('pages',[]):
            video_ids.update(item['contentDetails']['videoId'] for item in page.get('items',[]))

        for dataset in sources['api'].values():
            for page in dataset.get('pages',[]):
                columns=[h['name'] for h in page.get('columnHeaders',[])]
                if 'video' in columns:video_ids.update(row[columns.index('video')] for row in page.get('rows',[]))
        sources.setdefault('video_details',{})
        ordered=sorted(video_ids)
        for offset in range(0,len(ordered),50):
            ids=','.join(ordered[offset:offset+50])
            if sources['video_details'].get(ids,{}).get('status')=='available':continue
            try:
                details=fetcher(_api_url('videos',part='snippet,statistics,contentDetails,status',id=ids),token)
                sources['video_details'][ids]={'status':'available','response':details}
            except (ValueError,RuntimeError) as exc:
                sources['video_details'][ids]={'status':'unavailable','reason':str(exc)}
            checkpoint()
    else:
        sources['api']={'status':'not_applicable','reason':'冷启动初诊断，不采集运营指标'}
    # Bind platform videos to the actual local drama; never infer from an unrelated title.
    sources['video_drama_mapping']=[{'youtube_video_id':v.youtube_video_id,'title':v.title,
        'duration_seconds':v.duration_seconds,'privacy_status':v.privacy_status,
        'description':v.description,'uploaded_at':str(v.uploaded_at) if v.uploaded_at else None,
        'drama_code':d.drama_code if d else None,'drama_title':d.chinese_title if d else None,
        'plot':(d.content_summary or d.plot_archive) if d else None} for v,d in session.execute(
            select(YoutubeVideo,Drama).outerjoin(Drama,Drama.id==YoutubeVideo.drama_id).where(
                YoutubeVideo.channel_id==run.channel_id,YoutubeVideo.deleted_at.is_(None)))]
    sources['screenshots']=[m for m in run.materials if m['kind']!='studio_zip']
    sources['availability_rules']=['unavailable','not_applicable','pending','measured numeric value']
    sources['studio_windows']={key:studio_period(value) for key,value in sources.get('studio',{}).items()}
    for period in sources['studio_windows'].values():
        if run.mode=='periodic' and (date.fromisoformat(period['end'])>end or (end-date.fromisoformat(period['end'])).days>7):
            raise ConflictError('Studio 导出周期不是近期完整28天，请重新建立分析任务并上传近期导出')
    sources['normalized']=normalize_sources(sources,channel,run.mode)
    if run.mode=='periodic':
        from zhiju.services.channel_analysis_normalize import formal_snapshot
        sources['fact_snapshot']=formal_snapshot(sources,channel)
    claimed(session,run_id,claim_id)
    snapshot['sources']=sources;snapshot['sources_complete']=True;snapshot['normalization_revision']=5 if snapshot.get('studio_input_contract') else 4;run.input_snapshot=snapshot;run.phase='analysis'
    session.commit();return run
