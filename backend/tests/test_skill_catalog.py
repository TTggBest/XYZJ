from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile
from sqlalchemy import select
from test_v14_api import client, PRINCIPAL
from test_v14_runs import store
from zhiju import auth_context
from zhiju.database import TenantSession
from zhiju.models.v14 import V14Setting
from zhiju.services import skill_catalog
from zhiju.workflow_bundles import BASELINE


def admin(client):
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL,platform_role='super_admin')


def test_builtin_categories_share_production_versions_and_analysis_files(client):
    admin(client)
    result=client.get('/api/v3/skill-categories')
    assert result.status_code==200,result.text
    categories={c['id']:c for c in result.json()}
    assert list(categories)==['channel-analysis','package-production','channel-scheduling','channel-initialization']
    assert len(categories['channel-analysis']['versions'])==1
    legacy=client.get('/api/v3/workflow-versions').json()
    assert categories['package-production']['versions']==legacy['versions']
    assert categories['package-production']['default_id']==legacy['default_id']
    detail=client.get('/api/v3/skill-categories/channel-analysis/versions/builtin-xy-yt-report-v2',params={'path':'SKILL.md'}).json()
    assert 'references/asset-contract.md' in detail['files']
    assert 'scripts/validate_generation_spec.py' in detail['files']
    assert 'XY YouTube Report V2' in detail['content']


def test_production_upload_and_default_are_same_live_registry(client):
    admin(client)
    response=client.post('/api/v3/skill-categories/package-production/versions',data={'label':'V18'},files={'file':('skills.zip',BASELINE.read_bytes())})
    assert response.status_code==200,response.text
    vid=response.json()['id']
    assert client.post('/api/v3/skill-categories/package-production/default',json={'version_id':vid}).status_code==409
    assert client.post(f'/api/v3/skill-categories/package-production/versions/{vid}/publish').status_code==200
    assert client.post('/api/v3/skill-categories/package-production/default',json={'version_id':vid}).status_code==200
    assert client.get('/api/v3/workflow-versions').json()['default_id']==vid
    assert client.get(f'/api/v3/workflow-versions/{vid}/download').content==BASELINE.read_bytes()


def test_new_category_versions_publish_defaults_and_tenant_isolation(client,store):
    assert client.post('/api/v3/skill-categories',json={'name':'测试'}).status_code==403
    admin(client)
    cid=client.post('/api/v3/skill-categories',json={'name':'测试','description':'新增能力'}).json()['id']
    assert client.post('/api/v3/skill-categories',json={'name':'测试'}).status_code==409
    assert client.post('/api/v3/skill-categories',json={'name':'频道分析'}).status_code==409
    data=BytesIO()
    with ZipFile(data,'w') as z:z.writestr('SKILL.md','# Example\nInstructions')
    response=client.post(f'/api/v3/skill-categories/{cid}/versions',data={'label':'V1'},files={'file':('skill.zip',data.getvalue())})
    assert response.status_code==200,response.text
    vid=response.json()['id']
    assert client.post(f'/api/v3/skill-categories/{cid}/default',json={'version_id':vid}).status_code==409
    client.post(f'/api/v3/skill-categories/{cid}/versions/{vid}/publish').raise_for_status()
    client.post(f'/api/v3/skill-categories/{cid}/default',json={'version_id':vid}).raise_for_status()
    assert client.get('/api/v3/skill-categories').json()[-1]['default_id']==vid
    with TenantSession(store,info={'tenant_id':'tenant-b'}) as s:
        assert len(skill_catalog.catalog(s))==4
        import pytest
        from fastapi import HTTPException
        with pytest.raises(HTTPException):skill_catalog.archive(s,cid,vid)


def test_analysis_default_freezes_complete_version_and_old_snapshot_unchanged(client,store):
    admin(client)
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        original=skill_catalog.analysis_snapshot(s)
    response=client.post('/api/v3/skill-categories/channel-analysis/versions',data={'label':'xy-yt-report-v2'},files={'file':('skill.zip',skill_catalog.BUNDLE.read_bytes())})
    assert response.status_code==200,response.text
    assert response.json()['revision']==2
    vid=response.json()['id']
    client.post(f'/api/v3/skill-categories/channel-analysis/versions/{vid}/publish').raise_for_status()
    client.post('/api/v3/skill-categories/channel-analysis/default',json={'version_id':vid}).raise_for_status()
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        current=skill_catalog.analysis_snapshot(s)
        assert current['id']==vid
        assert original['id']=='builtin-xy-yt-report-v2'
        assert current['files']==original['files']
        assert s.scalar(select(V14Setting)).payload['analysis_skill_version_id']==vid
    # A version from one category must never become another category's default.
    cid=client.post('/api/v3/skill-categories',json={'name':'other'}).json()['id']
    assert client.post(f'/api/v3/skill-categories/{cid}/default',json={'version_id':vid}).status_code==409


def test_reject_invalid_skill_zip(client):
    admin(client)
    response=client.post('/api/v3/skill-categories/channel-analysis/versions',data={'label':'bad'},files={'file':('bad.zip',b'bad')})
    assert response.status_code==422


def test_save_executor_settings_preserves_selected_analysis_version(client):
    admin(client)
    response=client.post('/api/v3/skill-categories/channel-analysis/versions',data={'label':'v-next'},files={'file':('skill.zip',skill_catalog.BUNDLE.read_bytes())})
    vid=response.json()['id']
    client.post(f'/api/v3/skill-categories/channel-analysis/versions/{vid}/publish').raise_for_status()
    client.post('/api/v3/skill-categories/channel-analysis/default',json={'version_id':vid}).raise_for_status()
    config=client.get('/api/v3/v14/settings').json()
    config.pop('analysis_skill_version_id')
    config['default_model']='changed-model'
    response=client.put('/api/v3/v14/settings',json=config)
    assert response.status_code==200,response.text
    assert response.json()['analysis_skill_version_id']==vid


def test_catalog_migration_preserves_existing_tables():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/f20d20261102_skill_catalog.py'
    spec=importlib.util.spec_from_file_location('catalog_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE existing (value TEXT)')
        conn.exec_driver_sql("INSERT INTO existing VALUES ('preserved')")
        migration.op=Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert {'skill_categories','skill_bundle_versions'}<=set(sa.inspect(conn).get_table_names())
        assert conn.exec_driver_sql('SELECT value FROM existing').scalar()=='preserved'
        migration.downgrade()
        assert sa.inspect(conn).get_table_names()==['existing']


def test_production_catalog_places_builtin_v14_last_and_preserves_default(client,store):
    from datetime import datetime, timezone
    from zhiju.models.v14 import WorkflowSkillVersion
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        for index,(label,revision) in enumerate([('V15',1),('V16',3),('V16',4),('V17',1)],1):
            s.add(WorkflowSkillVersion(id=f'order-{index}',label=label,revision=revision,
                status='published',archive=BASELINE.read_bytes(),change_summary='',
                created_at=datetime(2026,10,index,tzinfo=timezone.utc)))
        setting=s.scalar(select(V14Setting))
        setting.payload={**setting.payload,'workflow_version_id':'order-4'}
        s.commit()
    catalog=client.get('/api/v3/skill-categories').json()
    production=next(c for c in catalog if c['id']=='package-production')
    assert [(v['label'],v['revision']) for v in production['versions']]==[
        ('V17',1),('V16',4),('V16',3),('V15',1),('V14',1)]
    assert production['default_id']=='order-4'
    assert client.get('/api/v3/workflow-versions').json()['versions']==production['versions']


def test_initialization_syncs_nine_modules_without_inventing_versions(client,store):
    from zhiju.models import Skill,SkillVersion
    admin(client)
    response=client.post('/api/v3/skill-categories/channel-initialization/sync')
    assert response.status_code==200,response.text
    modules=response.json()
    assert len(modules)==9
    assert not {'initial_analysis','operating_reference'} & {m['module_key'] for m in modules}
    assert all(m['skill_id'] and m['current_version_id'] is None for m in modules)
    assert all(m['readiness']=='missing_published_version' for m in modules)
    assert client.post('/api/v3/skill-categories/channel-initialization/sync').json()==modules
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        assert len(list(s.scalars(select(Skill))))==9
        assert list(s.scalars(select(SkillVersion)))==[]
    group=next(c for c in client.get('/api/v3/skill-categories').json() if c['id']=='channel-initialization')
    assert len(group['modules'])==9
    assert group['versions']==[]
    assert client.post('/api/v3/skill-categories/channel-initialization/versions',data={'label':'bad'},files={'file':('skills.zip',skill_catalog.BUNDLE.read_bytes())}).status_code==409


def test_production_review_lists_manifest_skills_and_compares_their_bodies(client):
    import json
    from test_workflow_bundles import archive

    admin(client)
    url = '/api/v3/skill-categories/package-production/versions'

    def upload(label, bodies):
        data = archive({
            'zhiju-workflow.json': json.dumps({'label': label, 'entrypoint': 'bridge.py', 'skills': list(bodies)}),
            'bridge.py': '# internal script',
            'tests/test_bridge.py': '# internal test',
            **{f'{name}/SKILL.md': body for name, body in bodies.items()},
        })
        response = client.post(url, data={'label': label}, files={'file': ('skills.zip', data)})
        return response.raise_for_status().json()['id'], data

    v19, _ = upload('V19', {'xy-cover-v19': 'cross-major rule\n', 'xy-cover-scene-v19': 'retired rule\n'})
    previous, _ = upload('V20', {'xy-cover-v20': 'previous rule\n'})
    current, current_zip = upload('V20', {'xy-title-v20': 'title rule\n', 'xy-cover-v20': 'current rule\n'})
    detail = client.get(f'{url}/{current}').raise_for_status().json()
    assert detail['skills'] == ['xy-title-v20', 'xy-cover-v20']
    assert detail['skill'] == 'xy-title-v20' and detail['content'] == 'title rule\n'
    assert 'files' not in detail
    assert client.get(f'{url}/{current}', params={'skill': 'bridge.py'}).status_code == 422
    assert client.get(f'{url}/{current}/download').content == current_zip

    for other, name, before, only in (
        (previous, 'xy-cover-v20', 'previous rule', []),
        (v19, 'xy-cover-v19', 'cross-major rule', ['xy-cover-scene-v19']),
    ):
        review = client.get(f'{url}/{current}', params={'skill': 'xy-cover-v20', 'compare_to': other}).raise_for_status().json()
        assert review['skills'] == detail['skills']
        assert review['content'] == 'current rule\n'
        assert review['compared_skill'] == name
        assert review['comparison_only'] == only
        assert f'-{before}\n+current rule' in review['diff']
    missing = client.get(f'{url}/{current}', params={'skill': 'xy-title-v20', 'compare_to': v19}).raise_for_status().json()
    assert missing['compared_skill'] is None and missing['diff'] is None
    assert missing['content'] == 'title rule\n'
