from datetime import date
import pytest
from sqlalchemy import select
from zhiju.database import TenantSession
from zhiju.models import Drama,DramaProductionState,OperationPackage,PackageTitle,WorkOrder,OperationTask,Channel
from test_v14_api import store,client


def complete(s,drama_id):
    from zhiju.services.drama_progress import NODE_DEFINITIONS
    s.add(DramaProductionState(drama_id=drama_id,**{field:'completed' for _,_,field in NODE_DEFINITIONS}))


def seed(s):
    complete(s,'drama-a')
    s.add(Drama(id='unused',drama_number=3,drama_code='unused',chinese_title='同名剧',normalized_title='同名剧'))
    complete(s,'unused')
    s.add(PackageTitle(package_id='package-a',variant_number=1,localized_title='First actual title',selected=True,status='selected'))
    for number,channel in [(2,'channel-a'),(3,'second-channel')]:
        if number==3:s.add(Channel(id=channel,youtube_channel_id='UC-second',original_name='Deuxième',default_language='fr'))
        task=f'task-{number}';work=f'work-{number}'
        s.add(OperationTask(id=task,batch_id='batch-a',channel_id=channel,drama_id='drama-a',source='manual',
            task_date=date(2026,10,number),target_publish_date=date(2026,11,number),idempotency_key=task))
        s.add(WorkOrder(id=work,task_id=task,batch_id='batch-a',channel_id=channel,drama_id='drama-a',
            production_date=date(2026,10,number),target_publish_date=date(2026,11,number)))
        s.add(OperationPackage(id=f'package-{number}',work_order_id=work,channel_id=channel,drama_id='drama-a',status='text_ready'))
        s.add(PackageTitle(package_id=f'package-{number}',variant_number=1,localized_title=f'Title {number}',selected=True,status='selected'))
    # An empty pre-created version must not count. Keep a produced older package version.
    s.add(OperationPackage(id='empty-new-version',work_order_id='work-a',channel_id='channel-a',drama_id='drama-a',version_number=2))
    s.commit()


def test_completed_list_summarizes_actual_packages_across_channels_without_any_video(client,store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:seed(s)
    response=client.get('/api/v3/drama-production',params={'overall_status':'completed'})
    assert response.status_code==200,response.text
    rows={row['drama_id']:row for row in response.json()['items']}
    assert rows['drama-a']['package_count']==3
    assert rows['drama-a']['package_channel_count']==2
    assert rows['drama-a']['latest_package_production_date']=='2026-10-17'
    assert rows['unused']['package_count']==rows['unused']['package_channel_count']==0
    response=client.get('/api/v3/dramas/drama-a/packages')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['package_count']==3 and data['channel_count']==2
    assert {row['package_id'] for row in data['items']}=={'package-a','package-2','package-3'}
    assert {row['production_date'] for row in data['items']}=={'2026-10-17','2026-10-02','2026-10-03'}
    assert all(row['version_number']==1 for row in data['items'])
    assert client.get('/api/v3/dramas/unused/packages').json()['items']==[]


def test_historical_versions_and_retries_are_not_confused_with_other_drama_or_tenant(client,store):
    from zhiju.models import PackageCoverVariant
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        seed(s)
        original=s.get(Drama,'drama-a');other=s.get(Drama,'unused');other.chinese_title=original.chinese_title
        s.add(PackageTitle(package_id='empty-new-version',variant_number=1,localized_title='New package version',selected=True,status='selected'))
        s.add(PackageTitle(package_id='package-a',variant_number=1,generation_number=2,localized_title='Retried title',selected=True,status='selected'))
        s.add(PackageCoverVariant(package_id='package-a',title_id=s.scalar(select(PackageTitle.id).where(
            PackageTitle.package_id=='package-a',PackageTitle.generation_number==2)),aspect_ratio='16:9',creative_prompt='Bound to retried title'))
        s.commit()
    with TenantSession(store,info={'tenant_id':'tenant-b'}) as s:
        complete(s,'drama-b')
        s.add(PackageTitle(package_id='package-b',variant_number=1,localized_title='Other company secret',selected=True,status='selected'));s.commit()
    rows=client.get('/api/v3/dramas/drama-a/packages').raise_for_status().json()
    assert rows['package_count']==4 and rows['channel_count']==2
    assert {'package-a','empty-new-version'} <= {r['package_id'] for r in rows['items']}
    assert client.get('/api/v3/dramas/unused/packages').json()['package_count']==0
    detail=client.get('/api/v3/dramas/drama-a/packages/package-a').raise_for_status().json()
    assert [t['localized_title'] for t in detail['outputs']['titles']]==['Retried title','First actual title']
    assert detail['outputs']['covers'][0]['creative_prompt']=='Bound to retried title'
    assert client.get('/api/v3/dramas/unused/packages/package-a').status_code==404
    assert client.get('/api/v3/dramas/drama-b/packages').status_code==404
    assert client.get('/api/v3/dramas/drama-a/packages/package-b').status_code==404


def test_history_and_details_only_read_and_routes_are_tenant_classified(client,store):
    from sqlalchemy import event
    from zhiju.tenant_scope import TENANT_ROUTES
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:seed(s)
    statements=[]
    def trace(conn,cursor,statement,params,context,executemany):statements.append(statement.strip().split()[0].upper())
    event.listen(store,'before_cursor_execute',trace)
    try:
        for path in ('/drama-production?overall_status=completed','/dramas/drama-a/packages','/dramas/drama-a/packages/package-a'):
            result=client.get('/api/v3'+path);assert result.status_code==200,result.text
    finally:event.remove(store,'before_cursor_execute',trace)
    assert not set(statements)&{'INSERT','UPDATE','DELETE'}
    for path in ('/api/v3/dramas/{drama_id}/packages','/api/v3/dramas/{drama_id}/packages/{package_id}'):
        assert ('GET',path) in TENANT_ROUTES


def test_history_includes_inline_cover_previews_bound_to_current_titles(client,store):
    from zhiju.models import PackageCoverVariant
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        seed(s)
        old=s.scalar(select(PackageTitle).where(PackageTitle.package_id=='package-a'))
        s.add_all([
            PackageTitle(id='current-a',package_id='package-a',variant_number=1,generation_number=2,
                localized_title='Current A',chinese_translation='当前标题A'),
            PackageTitle(id='current-b',package_id='package-a',variant_number=2,localized_title='Current B'),
            PackageCoverVariant(package_id='package-a',title_id=old.id,aspect_ratio='16:9',creative_prompt='Old title cover',asset_id='old-title-asset'),
            PackageCoverVariant(package_id='package-a',title_id='current-a',aspect_ratio='16:9',generation_number=1,creative_prompt='Old attempt',asset_id='old-attempt-asset'),
            PackageCoverVariant(package_id='package-a',title_id='current-a',aspect_ratio='16:9',generation_number=2,creative_prompt='Current cover',asset_id='current-landscape'),
            PackageCoverVariant(package_id='package-a',title_id='current-a',aspect_ratio='4:5',creative_prompt='Portrait',asset_id='current-portrait'),
            PackageCoverVariant(package_id='package-2',title_id=s.scalar(select(PackageTitle.id).where(PackageTitle.package_id=='package-2')),
                aspect_ratio='16:9',creative_prompt='Other package',asset_id='other-package-image'),
        ])
        s.commit()
    rows={row['package_id']:row for row in client.get('/api/v3/dramas/drama-a/packages').raise_for_status().json()['items']}
    previews=rows['package-a']['cover_previews']
    assert [p['variant_number'] for p in previews]==[1,2]
    assert previews[0]['localized_title']=='Current A' and previews[0]['chinese_translation']=='当前标题A'
    assert {c['asset_id'] for c in previews[0]['covers']}=={'current-landscape','current-portrait'}
    assert previews[1]['covers']==[]
    assert rows['package-2']['cover_previews'][0]['covers'][0]['asset_id']=='other-package-image'
    assert rows['package-3']['cover_previews'][0]['covers']==[]

    # An unfinished retry must not silently display an older generated image.
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        s.add(PackageCoverVariant(package_id='package-a',title_id='current-a',aspect_ratio='16:9',generation_number=3,creative_prompt='Pending retry'))
        s.commit()
    row=next(row for row in client.get('/api/v3/dramas/drama-a/packages').json()['items'] if row['package_id']=='package-a')
    assert next(c for c in row['cover_previews'][0]['covers'] if c['aspect_ratio']=='16:9')['asset_id'] is None
