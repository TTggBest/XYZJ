"""Read package usage by drama, independent of publishing and production control."""
from sqlalchemy import select,func,distinct,or_
from zhiju.models import (Drama,OperationPackage,WorkOrder,Channel,PackageTitle,PackageCoverVariant,
    PackageDescription,PackageCommunityPost,Language)
from zhiju.services.package_outputs import get_package_outputs
from zhiju.services.identity import channel_order_columns
from zhiju.tenant_repository import require_tenant_entity
from zhiju.services.channel import NotFoundError


def has_outputs():
    return or_(
        select(PackageTitle.id).where(PackageTitle.package_id==OperationPackage.id,
            func.trim(PackageTitle.localized_title)!='').correlate(OperationPackage).exists(),
        select(PackageCoverVariant.id).where(PackageCoverVariant.package_id==OperationPackage.id,
            func.trim(PackageCoverVariant.creative_prompt)!='').correlate(OperationPackage).exists(),
        select(PackageDescription.id).where(PackageDescription.package_id==OperationPackage.id,
            func.trim(PackageDescription.localized_text)!='').correlate(OperationPackage).exists(),
        select(PackageCommunityPost.id).where(PackageCommunityPost.package_id==OperationPackage.id,
            or_(func.trim(PackageCommunityPost.localized_text)!='',func.trim(PackageCommunityPost.image_prompt)!=''))
            .correlate(OperationPackage).exists())


def summaries(session,drama_ids):
    if not drama_ids:return {}
    rows=session.execute(select(OperationPackage.drama_id,func.count(OperationPackage.id),
        func.count(distinct(OperationPackage.channel_id)),func.max(WorkOrder.production_date))
        .join(WorkOrder,WorkOrder.id==OperationPackage.work_order_id)
        .where(OperationPackage.drama_id.in_(drama_ids),has_outputs()).group_by(OperationPackage.drama_id))
    return {drama_id:{'package_count':count,'package_channel_count':channels,'latest_package_production_date':latest}
            for drama_id,count,channels,latest in rows}


def records(session,drama_id,package_id=None):
    statement=(select(OperationPackage.id.label('package_id'),OperationPackage.channel_id,
        Channel.original_name.label('channel_name'),Channel.operational_name.label('channel_operational_name'),
        Channel.default_language.label('language'),Language.name_zh.label('language_name'),
        WorkOrder.production_date,OperationPackage.version_number,OperationPackage.status,
        OperationPackage.created_at,OperationPackage.ready_at)
        .join(WorkOrder,WorkOrder.id==OperationPackage.work_order_id)
        .join(Channel,Channel.id==OperationPackage.channel_id)
        .outerjoin(Language,Language.code==Channel.default_language)
        .where(OperationPackage.drama_id==drama_id,has_outputs()))
    if package_id:statement=statement.where(OperationPackage.id==package_id)
    return [dict(row) for row in session.execute(statement.order_by(*channel_order_columns(),
        WorkOrder.production_date.desc(),OperationPackage.version_number.desc(),OperationPackage.created_at.desc(),OperationPackage.id)).mappings()]


def list_for_drama(session,drama_id):
    drama=require_tenant_entity(session,Drama,drama_id)
    items=records(session,drama_id)
    previews=cover_previews(session,[row['package_id'] for row in items])
    for row in items:row['cover_previews']=previews.get(row['package_id'],[])
    return {'drama_id':drama.id,'drama_name':drama.chinese_title,'drama_code':drama.drama_code,
        'package_count':len(items),'channel_count':len({row['channel_id'] for row in items}),'items':items}


def cover_previews(session,package_ids):
    """Batch current A/B/C title-cover pairs, without fetching full package outputs."""
    if not package_ids:return {}
    titles={}
    for row in session.execute(select(PackageTitle.id,PackageTitle.package_id,PackageTitle.variant_number,
            PackageTitle.localized_title,PackageTitle.chinese_translation)
            .where(PackageTitle.package_id.in_(package_ids),PackageTitle.variant_number.in_([1,2,3]))
            .order_by(PackageTitle.generation_number.desc(),PackageTitle.variant_number)).mappings():
        titles.setdefault((row['package_id'],row['variant_number']),row)
    if not titles:return {}
    covers={}
    for row in session.execute(select(PackageCoverVariant.title_id,PackageCoverVariant.aspect_ratio,PackageCoverVariant.asset_id)
            .where(PackageCoverVariant.package_id.in_(package_ids),PackageCoverVariant.title_id.in_([t['id'] for t in titles.values()]))
            .order_by(PackageCoverVariant.generation_number.desc(),PackageCoverVariant.aspect_ratio)).mappings():
        covers.setdefault((row['title_id'],row['aspect_ratio']),{'aspect_ratio':row['aspect_ratio'],'asset_id':row['asset_id']})
    result={}
    for (package_id,variant_number),title in sorted(titles.items()):
        result.setdefault(package_id,[]).append({'variant_number':variant_number,
            'localized_title':title['localized_title'],'chinese_translation':title['chinese_translation'],
            'covers':[covers[(title['id'],ratio)] for ratio in ('16:9','4:5') if (title['id'],ratio) in covers]})
    return result


def detail(session,drama_id,package_id):
    require_tenant_entity(session,Drama,drama_id)
    rows=records(session,drama_id,package_id)
    if not rows:raise NotFoundError('该剧目没有这份已生产的运营包')
    return {'record':rows[0],'outputs':get_package_outputs(session,package_id)}
