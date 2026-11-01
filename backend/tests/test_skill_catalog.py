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
    assert list(categories)==['channel-analysis','package-production']
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
        assert len(skill_catalog.catalog(s))==2
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
