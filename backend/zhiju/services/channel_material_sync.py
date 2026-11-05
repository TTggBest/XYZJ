"""Import existing channel materials from two explicit source sheets.

Selected channels refresh nonempty source values; other channels only fill blanks.
No generated Skill versions, channel creations, or publishing calls are involved.
"""
from datetime import datetime,timezone
from sqlalchemy import select
from zhiju.models import Channel,ChannelProfile,ChannelKeyword,ChannelPinnedCommentTemplate,ChannelPlaylist,FeishuSyncRun
from zhiju.services import feishu_sync as source
from zhiju.services.identity import _audit

LANGUAGES={**source.CHANNEL_LANGUAGE_CONFIG,
    '泰语':('th','TH','泰国','Asia/Bangkok'),
    '法语':('fr','FR','法国','Europe/Paris'),
    '拉美西班牙语':('es','MX','墨西哥','America/Mexico_City')}


def sync_material_rows(session,info_rows,branding_rows,refresh_channel_ids=()):
    refresh=set(refresh_channel_ids)
    channels=list(session.scalars(select(Channel).where(Channel.deleted_at.is_(None))))
    by_id={c.id:c for c in channels};by_external={c.youtube_channel_id:c for c in channels};by_name={c.original_name:c for c in channels}
    if refresh-set(by_id):raise source.FeishuSyncError('刷新范围包含不存在的频道')
    brand={r['频道名'].strip():r for r in branding_rows if r.get('频道名')}
    changes=[];matched=set();unmatched=[]
    def assign(obj,key,value,overwrite):
        if value is None or (isinstance(value,str) and not value.strip()):return
        old=getattr(obj,key)
        if (overwrite or old is None or (isinstance(old,str) and not old.strip())) and old!=value:
            setattr(obj,key,value);changes.append({'channel_id':channel.id,'field':obj.__tablename__+'.'+key})
    for row in info_rows:
        name=row.get('频道名','').strip()
        if not name:continue
        external=source.resolve_youtube_channel_id(row['频道地址']) if row.get('频道地址','').strip() else None
        channel=by_external.get(external) or by_name.get(name)
        if not channel:unmatched.append(name);continue
        if external and channel.youtube_channel_id!=external:raise source.FeishuSyncError('频道名称与频道地址不匹配：'+name)
        if channel.id in matched:raise source.FeishuSyncError('频道信息重复：'+name)
        if name not in brand:raise source.FeishuSyncError('频道装修缺少：'+name)
        matched.add(channel.id);overwrite=channel.id in refresh;b=brand[name]
        language_name=row.get('语言','').strip()
        locale=LANGUAGES.get(language_name)
        if locale is None and (overwrite or not channel.default_language):raise source.FeishuSyncError('未配置频道语言：'+language_name)
        if locale:
            language,country,country_name,zone=locale
            for key,value in [('default_language',language),('country_code',country),('country_name_zh',country_name)]:assign(channel,key,value,overwrite)
            # A language recommendation never overwrites an existing audience timezone.
            assign(channel,'timezone',zone,False)
        for key,column in [('operational_name','本地昵称'),('channel_type','频道类型'),('drama_type','短剧类型')]:assign(channel,key,row.get(column),overwrite)
        assign(channel,'youtube_channel_url',row.get('频道地址'),False)
        profile=session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id==channel.id))
        if profile is None:profile=ChannelProfile(channel_id=channel.id,status='active');session.add(profile)
        for key,value in [('language',channel.default_language),('description',b.get('说明')),('popup_scheme',row.get('弹框')),('title_template',row.get('标题模版')),('fixed_symbol',row.get('固定符号'))]:assign(profile,key,value,overwrite)
        for kind,column in [('keyword','关键词'),('tag','标签')]:
            existing=list(session.scalars(select(ChannelKeyword).where(ChannelKeyword.channel_id==channel.id,ChannelKeyword.keyword_type==kind,ChannelKeyword.status=='active')))
            terms=source._split_terms(b.get(column,''))
            if not terms or (not overwrite and existing):continue
            desired=set(terms)
            for item in existing:
                if overwrite and item.source=='feishu_channel_branding' and (item.keyword not in desired or item.language!=channel.default_language):
                    item.status='archived';changes.append({'channel_id':channel.id,'field':'keywords.archived'})
            active={item.keyword for item in existing if item.language==channel.default_language and item.status=='active'}
            for term in terms:
                if term not in active:
                    prior=session.scalar(select(ChannelKeyword).where(ChannelKeyword.channel_id==channel.id,ChannelKeyword.keyword_type==kind,ChannelKeyword.keyword==term,ChannelKeyword.language==channel.default_language))
                    if prior:prior.status='active'
                    else:session.add(ChannelKeyword(channel_id=channel.id,keyword_type=kind,keyword=term,language=channel.default_language,source='feishu_channel_branding',status='active'))
                    active.add(term);changes.append({'channel_id':channel.id,'field':kind})
        for language,column in [(channel.default_language,'置顶回复'),('zh-CN','置顶回复中文')]:
            body=row.get(column,'').strip()
            active=session.scalar(select(ChannelPinnedCommentTemplate).where(ChannelPinnedCommentTemplate.channel_id==channel.id,ChannelPinnedCommentTemplate.language==language,ChannelPinnedCommentTemplate.status=='active'))
            if body and (overwrite or not active or not active.body):
                if not active or active.body!=body:
                    source._sync_pinned_template(session,channel,language,body);changes.append({'channel_id':channel.id,'field':'pinned_comment.'+language})
        for sequence in range(1,6):
            title=row.get(f'播放列表{sequence}','').strip()
            if not title:continue
            playlist=session.scalar(select(ChannelPlaylist).where(ChannelPlaylist.channel_id==channel.id,ChannelPlaylist.local_name==title,ChannelPlaylist.status!='deleted'))
            if playlist is None:
                playlist=ChannelPlaylist(channel_id=channel.id,local_name=title,status='active',sort_order=sequence);session.add(playlist)
                changes.append({'channel_id':channel.id,'field':'playlist.created'})
            url=row.get(f'列表地址{sequence}','').strip()
            for key,value in [('local_description',row.get(f'播放列表说明{sequence}')),('url',url),('youtube_playlist_id',source.youtube_playlist_id_from_url(url) if url else None)]:assign(playlist,key,value,overwrite)
    if refresh-matched:raise source.FeishuSyncError('指定刷新频道未出现在频道信息表')
    return {'rows_read':len(matched),'changes':changes,'channels_updated':len({c['channel_id'] for c in changes}),'unmatched':unmatched}


def sync_channel_materials(session,wiki_token,refresh_channel_ids=(),preview=True):
    source._require_tenant_context(session)
    client=source._client()
    info_id=client.sheet_id_by_title(wiki_token,'频道信息')
    brand_id=client.sheet_id_by_title(wiki_token,'频道装修')
    info=client.rows(wiki_token,info_id,'AA');branding=client.rows(wiki_token,brand_id,'G')
    transaction=session.begin_nested()
    try:
        result=sync_material_rows(session,info,branding,refresh_channel_ids)
        result.update(preview=preview,source_wiki=wiki_token,source_sheets={'频道信息':info_id,'频道装修':brand_id})
        if preview:transaction.rollback()
        else:
            run=FeishuSyncRun(sync_type='channels',sheet_id=info_id,environment=source.get_settings().env,status='completed',rows_read=result['rows_read'],rows_updated=result['channels_updated'],rows_inserted=0,rows_skipped=result['rows_read']-result['channels_updated'],started_at=datetime.now(timezone.utc),completed_at=datetime.now(timezone.utc))
            session.add(run)
            _audit(session,'channel.materials_synced','feishu_sheet',info_id,str(result['source_sheets']))
            transaction.commit();session.commit()
        return result
    except Exception:
        transaction.rollback();raise
