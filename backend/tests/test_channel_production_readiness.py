import pytest
import sqlalchemy as sa

from test_v14_runs import store, configure
from zhiju.database import TenantSession
from zhiju.models import Channel, ChannelPlaylist, ChannelProfile, ChannelPinnedCommentTemplate
from zhiju.models.v14 import V14Run
from zhiju.services.channel_readiness import production_material_issues
from zhiju.services.v14_runs import create_run
from zhiju.services.identity import ConflictError


@pytest.mark.parametrize("missing", ["playlist", "playlist_description", "profile", "pinned", "mismatch"])
def test_incomplete_channel_blocks_before_run_is_created(store, missing):
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
        if missing in ("playlist", "playlist_description", "mismatch"):
            row = s.scalar(sa.select(ChannelPlaylist))
            if missing == "playlist":
                s.delete(row)
            elif missing == "playlist_description":
                row.local_description = None
            else:
                row.url = "https://www.youtube.com/playlist?list=OTHER"
        elif missing == "profile":
            s.delete(s.scalar(sa.select(ChannelProfile)))
        else:
            for row in s.scalars(sa.select(ChannelPinnedCommentTemplate)):
                s.delete(row)
        s.commit()
        with pytest.raises(ConflictError, match="尚未具备生产条件，缺少"):
            create_run(s, "work-a")
        assert s.scalar(sa.select(sa.func.count()).select_from(V14Run)) == 0


def test_new_channel_does_not_appear_ready_from_identity_alone(store):
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        issues = production_material_issues(s, s.get(Channel, "channel-a"))
        assert "频道基础资料" in issues
        assert "hashtag 白名单" in issues
        assert "频道播放列表" in issues


@pytest.mark.parametrize("profile_status", ["active", "draft"])
def test_complete_channel_can_start_and_channel_views_report_ready(store, profile_status):
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        configure(s)
        s.scalar(sa.select(ChannelProfile)).status = profile_status
        s.flush()
        assert production_material_issues(s, s.get(Channel, "channel-a")) == []
        assert create_run(s, "work-a").status == "queued"


def test_channel_list_exposes_material_gaps_separately_from_authorization(store):
    from zhiju.services.identity import list_channel_overview
    from zhiju.schemas.identity import ChannelOverview
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        rows = list_channel_overview(s)
        assert len(rows) == 1
        result = ChannelOverview.model_validate(rows[0])
        assert "频道基础资料" in result.production_material_issues
        assert "hashtag 白名单" in result.production_material_issues


def test_channel_import_response_includes_exact_missing_materials(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from zhiju import auth_context
    from zhiju.api import youtube_oauth
    from test_youtube_channel_import_api_local import PRINCIPAL
    app = FastAPI()
    app.include_router(youtube_oauth.router, prefix="/api")
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as s:
        app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
        app.dependency_overrides[auth_context.get_tenant_db] = lambda: s
        monkeypatch.setattr(youtube_oauth, "commit_channel_import", lambda *args: [s.get(Channel, "channel-a")])
        with TestClient(app) as client:
            response = client.post("/api/v3/youtube/channel-imports/import-a/commit", json={"selections": [
                {"candidate_id": "candidate-a", "target_country_code": "US", "default_genre": "女频"}
            ]})
        assert response.status_code == 200, response.text
        gaps = response.json()["channel_material_issues"]
        assert gaps[0]["channel_id"] == "channel-a"
        assert "频道播放列表" in gaps[0]["missing"]
        assert "hashtag 白名单" in gaps[0]["missing"]

