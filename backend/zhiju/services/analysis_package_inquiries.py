"""Read selected historical package sections after an analysis has asked a concrete question."""
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select, or_
from zhiju.models import (YoutubeVideo, OperationPackage, OperationTask, WorkOrder, Drama,
    PackageTitle, PackageCoverVariant, PackageDescription, PackageCommunityPost,
    PackageOutputCopyState, MediaAsset)
from zhiju.models.v14 import V14Run, V14Attempt
from zhiju.services.identity import ConflictError
from zhiju.services import channel_analysis

SECTIONS = ('plot_basis', 'titles_and_hooks', 'cover_prompts', 'cover_images',
            'adoption_history', 'description', 'community')


def fields(row, *names):
    return {name: (value.isoformat() if isinstance(value, datetime) else value)
            for name in names for value in [getattr(row, name)]}


def linked_package(s, video):
    if video.operation_package_id:
        package = s.scalar(select(OperationPackage).where(OperationPackage.id == video.operation_package_id,
                                                        OperationPackage.channel_id == video.channel_id))
        return package, 'youtube_video.operation_package_id', None if package else 'direct_package_link_unavailable'
    # Use exact recorded scheduling/work-order relations, never a drama/title match.
    work_ids = select(WorkOrder.id).join(OperationTask, OperationTask.id == WorkOrder.task_id).where(
        OperationTask.channel_id == video.channel_id, OperationTask.source_video_id == video.youtube_video_id)
    links = [OperationPackage.work_order_id.in_(work_ids)]
    if video.schedule_id:
        links.append(OperationPackage.schedule_id == video.schedule_id)
    packages = list(s.scalars(select(OperationPackage).where(
        OperationPackage.channel_id == video.channel_id, or_(*links))))
    if len(packages) != 1:
        return None, 'schedule/work_order', 'ambiguous_package_links' if packages else 'no_package_link'
    return packages[0], 'schedule/work_order', None


def detail(s, channel_id, request):
    result = {'video_id':request['video_id'], 'channel_id':channel_id, 'request':deepcopy(request),
              'retrieved_at':datetime.now(timezone.utc).isoformat(), 'sections':{}, 'gaps':[]}
    video = s.scalar(select(YoutubeVideo).where(YoutubeVideo.channel_id == channel_id,
                                              YoutubeVideo.youtube_video_id == request['video_id']))
    if not video:
        result['gaps'].append('video_not_registered_in_this_channel')
        return result
    requested = set(request['sections'])
    package, relation, gap = linked_package(s, video)
    result['link_source'] = relation
    if 'adoption_history' in requested:
        result['sections']['adoption_history'] = {'current_video':fields(video, 'id','title','published_at',
            'last_synced_at','publish_status','privacy_status'),
            'scope':'Current synchronized video state, not a history of titles/covers over the analysis window.',
            'actual_variant_adoption':'unavailable; package linkage, selection and copying do not prove publication'}
        result['gaps'].append('historical_title_cover_adoption_unavailable')
    if gap:
        result['gaps'].append(gap)
        return result
    result['package'] = fields(package,'id','channel_id','drama_id','work_order_id','schedule_id',
                               'version_number','status','created_at','ready_at','approved_at','delivered_at')
    run = s.execute(select(V14Run.id).where(V14Run.package_id == package.id)).first()
    result['run_id'] = run.id if run else None
    if 'plot_basis' in requested:
        if run:
            result['sections']['plot_basis'] = {'source':'v14_run.input_snapshot', 'run_id':run.id,
                                               'drama':deepcopy((s.scalar(select(V14Run.input_snapshot).where(V14Run.id == run.id)) or {}).get('drama',{}))}
        else:
            drama = s.get(Drama, package.drama_id)
            result['sections']['plot_basis'] = {'source':'current_library_not_frozen_package_plot',
                'drama':fields(drama,'id','content_summary','plot_archive','plot_pattern','core_personas','source_language') if drama else None}
            result['gaps'].append('frozen_package_plot_unavailable')
    if 'titles_and_hooks' in requested:
        titles = list(s.scalars(select(PackageTitle).where(PackageTitle.package_id == package.id).order_by(
            PackageTitle.variant_number, PackageTitle.generation_number)))
        payloads = list(s.execute(select(V14Attempt.id,V14Attempt.payload,V14Attempt.created_at).where(
            V14Attempt.run_id == run.id,V14Attempt.node_type == 'title',V14Attempt.outcome == 'accepted'))) if run else []
        result['sections']['titles_and_hooks'] = {'titles':[fields(t,'id','variant_number','generation_number',
            'localized_title','chinese_translation','core_phrase','selected','status','created_at') for t in titles],
            'accepted_creative_plans':[{'attempt_id':a.id,'created_at':a.created_at.isoformat(),
                                       'payload':deepcopy(a.payload)} for a in payloads]}
    if requested & {'cover_prompts','cover_images'}:
        covers = list(s.scalars(select(PackageCoverVariant).where(PackageCoverVariant.package_id == package.id)))
        if 'cover_prompts' in requested:
            result['sections']['cover_prompts'] = [fields(c,'id','title_id','aspect_ratio','generation_number',
                'creative_prompt','selected','status','created_at') for c in covers]
        if 'cover_images' in requested:
            images = []
            from zhiju.services.image_processing import resolve_media_asset_file
            for cover in covers:
                asset = s.get(MediaAsset,cover.asset_id) if cover.asset_id else None
                image = {'cover_id':cover.id,'title_id':cover.title_id,'asset_id':cover.asset_id,
                         'availability':'unavailable', 'viewed':False}
                if asset and asset.asset_type == 'image' and asset.status == 'ready' and asset.deleted_at is None:
                    image.update(fields(asset,'created_at','mime_type','original_filename'))
                    try:
                        resolve_media_asset_file(s,asset.id)
                        image.update(availability='downloadable',content_path=f'/media-assets/{asset.id}/content')
                    except (FileNotFoundError,ValueError) as exc:
                        image['gap'] = str(exc)
                else:
                    image['gap'] = 'no_ready_image_asset'
                images.append(image)
            result['sections']['cover_images'] = images
            if not images or any(i['availability'] != 'downloadable' for i in images):
                result['gaps'].append('some_or_all_cover_images_unavailable')
    if 'adoption_history' in requested:
        result['sections']['adoption_history']['selection_states'] = {
            'titles':[fields(t,'id','variant_number','generation_number','selected','status','updated_at') for t in
                s.scalars(select(PackageTitle).where(PackageTitle.package_id == package.id))],
            'covers':[fields(c,'id','title_id','generation_number','selected','status','updated_at') for c in
                s.scalars(select(PackageCoverVariant).where(PackageCoverVariant.package_id == package.id))]}
        result['sections']['adoption_history']['copy_events'] = [fields(c,'output_type','output_id','copied_at') for c in
            s.scalars(select(PackageOutputCopyState).where(PackageOutputCopyState.package_id == package.id))]
    if 'description' in requested:
        result['sections']['description'] = [fields(d,'id','version_number','localized_text','chinese_translation',
            'pinned_comment','selected','status','created_at') for d in s.scalars(select(PackageDescription).where(
                PackageDescription.package_id == package.id))]
        result['current_video_description'] = {'text':video.description,'last_synced_at':video.last_synced_at.isoformat() if video.last_synced_at else None}
    if 'community' in requested:
        result['sections']['community'] = [fields(c,'id','sequence_number','version_number','localized_text',
            'chinese_translation','image_prompt','selected','status','planned_time','created_at') for c in
            s.scalars(select(PackageCommunityPost).where(PackageCommunityPost.package_id == package.id))]
    return result


def inquire(s, run_id, claim_id, requests, *, initial_findings="", image_review=None):
    run = channel_analysis.claimed(s,run_id,claim_id)
    sources = run.input_snapshot.get('sources',{})
    facts = sources.get('fact_snapshot',{})
    if not facts:
        raise ConflictError('先完成指标取数和初判，再按问题回查运营包')
    allowed = {v['id'] for v in facts.get('video_inventory',[]) if v.get('id')}
    allowed.update(v['youtube_video_id'] for v in sources.get('video_drama_mapping',[]) if v.get('youtube_video_id'))
    allowed.update(v['video_id'] for v in facts.get('studio_content',[]) if v.get('video_id'))
    for window in facts.get('studio_short_windows',{}).values():
        allowed.update(v['video_id'] for v in window.get('content',[]) if v.get('video_id') and v.get('content_type','video')=='video')
    for domain in ('top_videos_28d','middle_videos_28d','low_videos_28d','api_videos_7d','api_videos_previous_7d'):
        allowed.update(v['video'] for v in facts.get(domain,{}).get('rows',[]) if v.get('video'))
    for request in requests:
        if request.get('video_id') not in allowed:
            raise ConflictError('回查视频不属于本次频道分析材料')
        if not str(request.get('reason') or '').strip() or not str(request.get('question') or '').strip():
            raise ConflictError('回查必须包含初判理由和具体调查问题')
        if not request.get('sections') or set(request['sections']) - set(SECTIONS):
            raise ConflictError('回查资料段无效')
    history = deepcopy(sources.get('package_inquiries',[]))
    batch = next((b for b in history if b['requests'] == requests),None)
    if batch is None:
        batch = {'initial_findings':initial_findings,'requests':deepcopy(requests),'results':[detail(s,run.channel_id,r) for r in requests]}
        history.append(batch)
    if image_review is not None:
        assets = {i['asset_id'] for r in batch['results'] for i in r['sections'].get('cover_images',[]) if i.get('asset_id')}
        if any(i.get('asset_id') not in assets for i in image_review):
            raise ConflictError('图片复核不属于本次回查资产')
        batch['image_review'] = deepcopy(image_review)
    if history != sources.get('package_inquiries',[]):
        run.input_snapshot = {**run.input_snapshot,'sources':{**sources,'package_inquiries':history}}
        s.commit()
    return deepcopy(batch)
