from datetime import datetime
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from zhiju.models import Base, MediaAsset
from zhiju.database import TenantSession
from zhiju.auth_context import get_tenant_db
from zhiju.api import channel as channel_api
from zhiju.services.channel import get_media_asset


def test_download_state_is_persistent_and_does_not_mark_missing_or_other_tenant_assets(tmp_path, monkeypatch):
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    active={'tenant':'tenant-a'}
    def db():
        with TenantSession(bind=engine,info={'tenant_id':active['tenant']}) as s:
            yield s
    app=FastAPI();app.include_router(channel_api.router,prefix='/api');app.dependency_overrides[get_tenant_db]=db
    for tenant,key in [('tenant-a','ours'),('tenant-b','theirs')]:
        with TenantSession(bind=engine,info={'tenant_id':tenant}) as s:
            s.add(MediaAsset(id=key,storage_provider='local',storage_key=key+'.png',original_filename=key+'.png',asset_type='image',asset_role='other',mime_type='image/png',width=1,height=1,sha256='a'*64,file_size_bytes=3,status='ready'))
            s.commit()
    source=tmp_path/'image.png';source.write_bytes(b'png')
    def resolve(s,key):
        asset=get_media_asset(s,key)
        if not source.exists(): raise FileNotFoundError('原图不存在')
        return asset,source
    monkeypatch.setattr(channel_api,'resolve_media_asset_file',resolve)
    c=TestClient(app)
    assert c.get('/api/v3/media-assets/ours').json().get('downloaded_at') is None
    response=c.post('/api/v3/media-assets/ours/download-complete')
    assert response.status_code==200,response.text
    assert response.json()['downloaded_at']
    assert c.get('/api/v3/media-assets/ours').json()['downloaded_at']==response.json()['downloaded_at']
    assert c.post('/api/v3/media-assets/theirs/download-complete').status_code==404
    active['tenant']='tenant-b'
    source.unlink()
    assert c.post('/api/v3/media-assets/theirs/download-complete').status_code==404
    assert c.get('/api/v3/media-assets/theirs').json()['downloaded_at'] is None


def test_download_timestamp_migration_keeps_existing_media_rows():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    file=Path(__file__).resolve().parents[1]/'alembic/versions/f19c20261101_media_downloaded_at.py'
    spec=importlib.util.spec_from_file_location('download_migration',file)
    revision=importlib.util.module_from_spec(spec);spec.loader.exec_module(revision)
    engine=create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE media_assets (id TEXT PRIMARY KEY, original_filename TEXT)'))
        c.execute(text("INSERT INTO media_assets VALUES ('old','cover.png')"))
        revision.op=Operations(MigrationContext.configure(c));revision.upgrade()
        assert c.execute(text('SELECT id,original_filename,downloaded_at FROM media_assets')).one()==('old','cover.png',None)
        revision.downgrade()
        assert c.execute(text('SELECT * FROM media_assets')).one()==('old','cover.png')
