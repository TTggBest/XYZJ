"""Read-only Google collection and native Studio archive normalization."""
import csv
import io
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
from zhiju.services.channel_analysis_normalize import studio_period, normalize_sources


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
            if not period or period['complete_days']!=28:
                raise ValueError('必须提供带实际日期的最近28天内容导出')
            return result
    except (BadZipFile,UnicodeError,ValueError,RuntimeError) as exc:
        raise ConflictError('无法读取 Studio 内容导出 ZIP：'+str(exc)) from exc


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
    if run.input_snapshot.get('sources_complete'):return run
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
        if not sources.get('windows'):
            end=datetime.now(ZoneInfo('America/Los_Angeles')).date()-timedelta(days=1)
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
        for days in (28,90):
            window=sources['windows'][str(days)]
            start=date.fromisoformat(window['start'])
            specs=[('daily','day','views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost','day'),
                ('videos','video','views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained','-views'),
                ('country','country','views,estimatedMinutesWatched','-views'),
                ('traffic','insightTrafficSourceType','views,estimatedMinutesWatched','-views'),
                ('device','deviceType','views,estimatedMinutesWatched','-views')]
            for name,dimension,metrics,sort in specs:
                key=f'{days}:{name}'
                cached=sources['api'].get(key) or reusable.get(key)
                if cached and cached.get('status')=='available' and cached.get('window')==window:
                    sources['api'][key]=cached
                    continue
                params={'ids':'channel==MINE','startDate':str(start),'endDate':str(end),
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
        if not any(x.get('pages') and any(p.get('rows') for p in x['pages']) for x in sources['api'].values()):
            raise ConflictError('Analytics 无可用数据；不能以冷启动代替正式数据分析')
        sources['studio']={m['id']:parse_studio_zip(material_path(run,m['id']).read_bytes())
            for m in run.materials if m['kind']=='studio_zip'}
        video_ids=set(session.scalars(select(YoutubeVideo.youtube_video_id).where(YoutubeVideo.channel_id==run.channel_id)))
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
        'plot':d.content_summary if d else None} for v,d in session.execute(
            select(YoutubeVideo,Drama).outerjoin(Drama,Drama.id==YoutubeVideo.drama_id).where(
                YoutubeVideo.channel_id==run.channel_id,YoutubeVideo.deleted_at.is_(None)))]
    sources['screenshots']=[m for m in run.materials if m['kind']!='studio_zip']
    sources['availability_rules']=['unavailable','not_applicable','pending','measured numeric value']
    sources['studio_windows']={key:studio_period(value) for key,value in sources.get('studio',{}).items()}
    for period in sources['studio_windows'].values():
        if date.fromisoformat(period['end'])>end or (end-date.fromisoformat(period['end'])).days>7:
            raise ConflictError('Studio 导出周期不是近期完整28天，请重新建立分析任务并上传近期导出')
    sources['normalized']=normalize_sources(sources,channel,run.mode)
    claimed(session,run_id,claim_id)
    snapshot['sources']=sources;snapshot['sources_complete']=True;run.input_snapshot=snapshot;run.phase='analysis'
    session.commit();return run
