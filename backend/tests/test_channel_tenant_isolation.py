from datetime import date, datetime, time
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal
from zhiju import auth_context, database
from zhiju.api import channel as channel_api, identity as identity_api, operations as operations_api
from zhiju.database import TenantSession
from zhiju.models import Base
from zhiju.models import (
    Channel, ChannelAnalysisReport, ChannelCommunitySlot, ChannelDnaVersion,
    ChannelKeyword, ChannelPlaylist, ChannelProfile, ChannelPublishSlot,
    ChannelScheduleEntry, Drama, DramaProductionState, GoogleAccount, OAuthGrant, AuthorizationEvent,
    ScheduleCandidate,
    MediaAsset,
)
from zhiju.schemas.channel import ChannelDnaVersionCreate, ChannelProfileUpsert
from zhiju.schemas.identity import ChannelStatusChange
from zhiju.schemas.operations import CommunitySlotCreate, ScheduleCreate
from zhiju.services import channel as channel_service, identity, operations


ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = Principal(
    user_id="user-a", tenant_id="tenant-a", membership_role="owner", platform_role=None,
    device_id=None, device_trust_level="normal", permissions=frozenset({"channel.read"}),
)
# Literal fixtures for the twenty non-root tables in the channel scope map.
CHANNEL_PARENTS = {
    "channel_profiles": {"channel_id": "channels", "avatar_asset_id": "media_assets", "banner_asset_id": "media_assets"},
    "channel_initialization_drafts": {"channel_id": "channels", "applied_report_id": "channel_analysis_reports", "applied_dna_version_id": "channel_dna_versions"},
    "channel_pinned_comment_templates": {"channel_id": "channels"},
    "channel_branding_assets": {"channel_id": "channels", "asset_id": "media_assets"},
    "channel_keywords": {"channel_id": "channels"},
    "channel_analysis_reports": {"channel_id": "channels"},
    "channel_analysis_topic_scores": {"report_id": "channel_analysis_reports"},
    "channel_analysis_keyword_scores": {"report_id": "channel_analysis_reports"},
    "channel_audience_profiles": {"report_id": "channel_analysis_reports"},
    "channel_strategy_recommendations": {"report_id": "channel_analysis_reports"},
    "channel_analysis_evidence": {"report_id": "channel_analysis_reports"},
    "channel_dna_versions": {"channel_id": "channels", "analysis_report_id": "channel_analysis_reports"},
    "channel_dna_signals": {"dna_version_id": "channel_dna_versions"},
    "channel_logo_profiles": {"channel_id": "channels"},
    "channel_playlists": {"channel_id": "channels"},
    "channel_publish_slots": {"channel_id": "channels"},
    "channel_community_slots": {"channel_id": "channels", "publish_slot_id": "channel_publish_slots"},
    "channel_schedule_entries": {
        "channel_id": "channels", "drama_id": "dramas", "channel_dna_version_id": "channel_dna_versions",
        "playlist_id": "channel_playlists", "publish_slot_id": "channel_publish_slots",
        "replaced_by_schedule_id": "channel_schedule_entries",
    },
    "sync_watermarks": {"channel_id": "channels"},
    "youtube_channel_daily_metrics": {"channel_id": "channels"},
}


@pytest.fixture
def migration():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    revision = next((r for r in ScriptDirectory.from_config(config).walk_revisions()
                     if r.revision == "c2e5f8a3b721"), None)
    return revision.module if revision else None


@pytest.fixture
def legacy_graph():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        for name in ("channels", "dramas", "media_assets"):
            table = sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True),
                             sa.Column("tenant_id", sa.String(36)))
        for name, parents in CHANNEL_PARENTS.items():
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True),
                     *(sa.Column(column, sa.String(36)) for column in parents))
        metadata.create_all(connection)
        for name in ("channels", "dramas", "media_assets"):
            connection.execute(metadata.tables[name].insert(), [
                {"id": "a", "tenant_id": "tenant-a"}, {"id": "b", "tenant_id": "tenant-b"},
            ])
        for name, parents in CHANNEL_PARENTS.items():
            connection.execute(metadata.tables[name].insert(), [
                {"id": key, **{column: key for column in parents}} for key in ("a", "b")
            ])
        yield connection
    engine.dispose()


def install_operations(monkeypatch, migration, connection):
    assert migration is not None, "Task 4 channel graph migration is missing"
    assert migration.down_revision == "b1d4e7f2a610"
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))


def test_channel_graph_migration_backfills_all_parent_chains_and_models_filter_them(
    migration, legacy_graph, monkeypatch,
):
    install_operations(monkeypatch, migration, legacy_graph)
    migration.upgrade()
    for name in CHANNEL_PARENTS:
        assert legacy_graph.execute(sa.text(f"SELECT id, tenant_id FROM {name} ORDER BY id")).all() == [
            ("a", "tenant-a"), ("b", "tenant-b"),
        ]
        columns = {c["name"]: c for c in sa.inspect(legacy_graph).get_columns(name)}
        assert columns["tenant_id"]["nullable"] is True
        assert any(index["column_names"] == ["tenant_id"] for index in sa.inspect(legacy_graph).get_indexes(name))
        model = next(mapper.class_ for mapper in Base.registry.mappers if mapper.local_table.name == name)
        with TenantSession(bind=legacy_graph, info={"tenant_id": "tenant-a"}) as session:
            assert session.scalars(sa.select(model.id)).all() == ["a"], name


@pytest.mark.parametrize("table,column,bad_parent", [
    (table, column, bad_parent)
    for table, parents in CHANNEL_PARENTS.items() for column in parents
    for bad_parent in (["missing", "b"] if len(parents) > 1 else ["missing"])
])
def test_channel_graph_migration_stops_before_ddl_on_orphan_or_disagreeing_parent(
    migration, legacy_graph, monkeypatch, table, column, bad_parent,
):
    install_operations(monkeypatch, migration, legacy_graph)
    legacy_graph.execute(sa.text(f"UPDATE {table} SET {column} = :parent WHERE id = 'a'"), {"parent": bad_parent})
    with pytest.raises(RuntimeError, match=table):
        migration.upgrade()
    assert all("tenant_id" not in {c["name"] for c in sa.inspect(legacy_graph).get_columns(name)}
               for name in CHANNEL_PARENTS)


def test_channel_graph_migration_rejects_unowned_root(migration, legacy_graph, monkeypatch):
    install_operations(monkeypatch, migration, legacy_graph)
    legacy_graph.execute(sa.text("UPDATE channels SET tenant_id = NULL WHERE id = 'a'"))
    with pytest.raises(RuntimeError, match="tenant"):
        migration.upgrade()


def test_channel_graph_downgrade_removes_only_child_scope(migration, legacy_graph, monkeypatch):
    install_operations(monkeypatch, migration, legacy_graph)
    migration.upgrade()
    migration.downgrade()
    for name in CHANNEL_PARENTS:
        assert "tenant_id" not in {c["name"] for c in sa.inspect(legacy_graph).get_columns(name)}
        assert legacy_graph.scalar(sa.text(f"SELECT COUNT(*) FROM {name}")) == 2
    assert legacy_graph.scalar(sa.text("SELECT tenant_id FROM channels WHERE id = 'a'")) == "tenant-a"


@pytest.fixture
def channel_store():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for index, key in enumerate(("a", "b"), start=1):
            owned = {"tenant_id": f"tenant-{key}"}
            session.add_all([
                Channel(id=key, youtube_channel_id=f"UC-{key}", original_name="同名频道", status="active", **owned),
                ChannelProfile(id=f"profile-{key}", channel_id=key, description=f"{key} description", **owned),
                ChannelAnalysisReport(id=f"report-{key}", channel_id=key, report_type="manual", version_number=1, **owned),
                ChannelDnaVersion(id=f"dna-{key}", channel_id=key, language="zh", primary_genre="剧情", version_number=1, status="active", **owned),
                ChannelPlaylist(id=f"playlist-{key}", channel_id=key, local_name="同名列表", **owned),
                ChannelPublishSlot(id=f"slot-{key}", channel_id=key, slot_type="main", slot_number=1,
                                   local_time=time(12), timezone="Asia/Shanghai", **owned),
                ChannelCommunitySlot(id=f"community-{key}", channel_id=key, schedule_mode="fixed",
                                     local_time=time(13), timezone="Asia/Shanghai", **owned),
                Drama(id=f"drama-{key}", drama_number=index, drama_code=f"DR-{key}",
                      chinese_title=f"剧目{key}", normalized_title=f"drama{key}", **owned),
                DramaProductionState(drama_id=f"drama-{key}", cloud_download_status="completed",
                    parameter_normalization_status="completed", youtube_upload_status="completed",
                    copyright_verification_status="completed", subtitle_extraction_status="completed",
                    guishou_upload_status="completed", role_extraction_status="completed", tts_status="completed",
                    production_completion_status="completed", **owned),
                ChannelScheduleEntry(id=f"schedule-{key}", channel_id=key, drama_id=f"drama-{key}",
                    publish_slot_id=f"slot-{key}", publish_date=date(2026, 9, 12), idempotency_key=f"schedule-{key}",
                    planned_local_time=datetime(2026, 9, 12, 12), planned_beijing_time=datetime(2026, 9, 12, 12),
                    planned_utc_time=datetime(2026, 9, 12, 4), **owned),
                GoogleAccount(id=f"account-{key}", nickname="同名账号", google_email=f"{key}@example.com", **owned),
                OAuthGrant(id=f"grant-{key}", account_id=f"account-{key}", provider_subject=key,
                           credential_ref=f"secret-{key}", status="active"),
                AuthorizationEvent(id=f"event-{key}", account_id=f"account-{key}", channel_id=key,
                                   event_type="test", result="success", occurred_at=datetime(2026, 9, 12)),
                MediaAsset(id=f"asset-{key}", channel_id=key, storage_provider="local", storage_key=f"{key}.png",
                           asset_type="image", asset_role="channel_avatar", status="ready", sha256="a" * 64,
                           file_size_bytes=1, mime_type="image/png", width=100, height=100, **owned),
            ])
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def tenant_session(channel_store):
    with TenantSession(channel_store, info={"tenant_id": "tenant-a"}) as session:
        yield session


@pytest.mark.parametrize("operation", [
    lambda s: channel_service.get_channel_detail(s, "b"),
    lambda s: channel_service.list_reports(s, "b"),
    lambda s: channel_service.list_dna_versions(s, "b"),
    lambda s: identity.change_channel_status(s, "b", ChannelStatusChange(status="paused", reason="test")),
    lambda s: identity.archive_channel(s, "b", "test"),
    lambda s: operations.list_playlists(s, "b"),
    lambda s: operations.list_publish_slots(s, "b"),
    lambda s: operations.list_community_slots(s, "b"),
    lambda s: operations.list_schedules(s, channel_id="b"),
    lambda s: operations.list_schedule_overview(s, channel_id="b"),
    lambda s: operations.list_channel_schedule_page(s, channel_id="b"),
    lambda s: operations.change_schedule_status(s, "schedule-b", "cancelled", "test"),
    lambda s: operations.change_community_slot_status(s, "community-b", "inactive", "test"),
])
def test_service_channel_and_schedule_foreign_ids_are_404(tenant_session, operation):
    with pytest.raises(HTTPException) as exc:
        operation(tenant_session)
    assert exc.value.status_code == 404


def test_dna_cannot_reference_foreign_report_and_does_not_supersede_current_dna(tenant_session):
    with pytest.raises(HTTPException) as exc:
        channel_service.create_dna_version(tenant_session, "a", ChannelDnaVersionCreate(
            analysis_report_id="report-b", language="zh", primary_genre="剧情", activate=True,
        ))
    assert exc.value.status_code == 404
    assert tenant_session.get(ChannelDnaVersion, "dna-a").status == "active"
    assert tenant_session.scalar(sa.select(sa.func.count()).select_from(ChannelDnaVersion)) == 1


def test_profile_rejects_foreign_asset_even_if_cached_in_identity_map(tenant_session, channel_store):
    with Session(channel_store) as other:
        asset = other.get(MediaAsset, "asset-b")
        other.expunge(asset)
    tenant_session.add(asset)
    with pytest.raises(HTTPException) as exc:
        channel_service.upsert_profile(tenant_session, "a", ChannelProfileUpsert(avatar_asset_id="asset-b"))
    assert exc.value.status_code == 404


def test_relative_community_slot_rejects_foreign_publish_slot(tenant_session):
    with pytest.raises(HTTPException) as exc:
        operations.create_community_slot(tenant_session, "a", CommunitySlotCreate(
            schedule_mode="relative", publish_slot_id="slot-b", offset_minutes=60, timezone="Asia/Shanghai",
        ))
    assert exc.value.status_code == 404


def test_existing_schedule_retry_remains_idempotent_after_channel_paused(tenant_session):
    tenant_session.get(Channel, "a").status = "paused"
    tenant_session.commit()
    result = operations.create_schedule(tenant_session, "a", ScheduleCreate(
        drama_id="drama-a", publish_slot_id="slot-a", publish_date=date(2026, 9, 12),
        idempotency_key="schedule-a",
    ))
    assert result.id == "schedule-a"


def test_account_owned_authorization_lists_hide_foreign_data(tenant_session):
    assert [row["id"] for row in identity.list_oauth_grants(tenant_session)] == ["grant-a"]
    assert [row.id for row in identity.list_authorization_events(tenant_session)] == ["event-a"]


def test_channel_graph_lists_contain_only_current_tenant(tenant_session):
    assert [row.id for row in identity.list_channels(tenant_session)] == ["a"]
    assert [row["channel_id"] for row in identity.list_channel_overview(tenant_session)] == ["a"]
    assert [row["id"] for row in channel_service.list_reports(tenant_session, "a")] == ["report-a"]
    assert [row["id"] for row in channel_service.list_dna_versions(tenant_session, "a")] == ["dna-a"]
    assert [row.id for row in operations.list_playlists(tenant_session, "a")] == ["playlist-a"]
    assert [row.id for row in operations.list_schedules(tenant_session)] == ["schedule-a"]


OPERATION_TENANT_ENDPOINTS = {
    "patch_channel_cadence", "get_cadence_overview",
    "get_playlists", "post_playlist", "patch_playlist", "get_publish_slots",
    "get_publish_slot_overview", "post_publish_slot", "patch_publish_slot",
    "get_community_slots", "post_community_slot", "patch_community_slot_status",
    "get_schedules", "get_channel_schedule_page", "get_schedule_overview",
    "post_schedule", "patch_schedule_status", "patch_schedule_source_video",
    "post_schedule_candidate", "post_select_schedule_candidate",
}


@pytest.fixture
def tenant_client(channel_store, monkeypatch):
    app = FastAPI()
    for router in (identity_api.router, operations_api.router, channel_api.router):
        app.include_router(router, prefix="/api")

    def unscoped_db():
        with Session(channel_store) as session:
            yield session

    app.dependency_overrides[database.get_db] = unscoped_db
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    monkeypatch.setattr(database.database_router, "get_active_engine", lambda: channel_store)
    with TestClient(app) as client:
        yield client


def test_mixed_api_routers_bind_only_their_tenant_routes():
    for router in (identity_api.router, channel_api.router, operations_api.router):
        for route in router.routes:
            if router is operations_api.router and route.name not in OPERATION_TENANT_ENDPOINTS:
                continue
            direct = {dependency.call for dependency in route.dependant.dependencies}
            if route.name == "put_device":
                assert database.get_db in direct
                assert auth_context.get_tenant_db not in direct
            else:
                assert auth_context.get_tenant_db in direct, route.path


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/channels/b", None),
    ("PUT", "/channels/b/hub", {}),
    ("PATCH", "/channels/b/status", {"status": "paused", "reason": "test"}),
    ("DELETE", "/channels/b?reason=test", None),
    ("GET", "/channels/b/analysis-reports", None),
    ("GET", "/channels/a/analysis-reports/report-b", None),
    ("GET", "/channels/b/dna-versions", None),
    ("POST", "/channels/a/dna-versions", {"analysis_report_id": "report-b", "language": "zh", "primary_genre": "剧情"}),
    ("POST", "/channels/a/analysis-reports", {"report_type": "manual", "evidence": [
        {"source_type": "schedule", "source_entity_id": "schedule-b"}]}),
    ("GET", "/channels/b/playlists", None),
    ("PATCH", "/channels/a/playlists/playlist-b", {"local_name": "changed"}),
    ("GET", "/channels/b/publish-slots", None),
    ("GET", "/channels/b/community-slots", None),
    ("GET", "/schedules?channel_id=b", None),
    ("GET", "/schedules/channel-view?channel_id=b", None),
    ("POST", "/channels/b/schedules", {"drama_id": "drama-a", "publish_slot_id": "slot-a", "publish_date": "2026-09-13", "idempotency_key": "new-schedule"}),
    ("PATCH", "/schedules/schedule-b/status", {"status": "cancelled", "reason": "test"}),
    ("PATCH", "/schedules/schedule-b/source-video", {"source_video_id": "abcdefghijk"}),
    ("GET", "/media-assets/asset-b", None),
    ("GET", "/accounts/account-b/oauth-grants", None),
])
def test_http_cross_tenant_ids_are_404(tenant_client, method, path, payload):
    response = tenant_client.request(method, f"/api/v3{path}", json=payload)
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("path,expected", [
    ("/channels", "a"), ("/accounts", "account-a"), ("/oauth-grants", "grant-a"),
    ("/authorization-events", "event-a"), ("/schedules", "schedule-a"),
    ("/media-assets", "asset-a"),
])
def test_http_lists_are_scoped_to_principal(tenant_client, path, expected):
    response = tenant_client.get(f"/api/v3{path}?tenant_id=tenant-b", headers={"X-Tenant-ID": "tenant-b"})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [expected]


def test_http_creation_and_update_use_principal_and_preserve_other_tenant(tenant_client, channel_store):
    response = tenant_client.post("/api/v3/channels", json={
        "youtube_channel_id": "UC-new", "original_name": "同名频道", "tenant_id": "tenant-b",
    })
    assert response.status_code == 201, response.text
    new_id = response.json()["id"]
    response = tenant_client.put("/api/v3/channels/a/profile", json={"description": "changed", "tenant_id": "tenant-b"})
    assert response.status_code == 200, response.text
    with Session(channel_store) as session:
        assert session.get(Channel, new_id).tenant_id == "tenant-a"
        assert session.get(ChannelProfile, "profile-a").description == "changed"
        assert session.get(ChannelProfile, "profile-b").description == "b description"


def test_http_device_registration_keeps_platform_session(tenant_client, channel_store):
    response = tenant_client.put("/api/v3/devices/register", json={
        "device_key": "test-device", "hostname": "test-host", "name": "test", "os_type": "macos",
    })
    assert response.status_code == 200, response.text
    with Session(channel_store) as session:
        events = session.execute(sa.select(Base.metadata.tables["audit_events"]).where(
            Base.metadata.tables["audit_events"].c.action == "device.created"
        ).with_only_columns(Base.metadata.tables["audit_events"].c.tenant_id)).all()
        assert events == [(None,)]


@pytest.fixture
def schedule_candidates(channel_store):
    with Session(channel_store) as session:
        session.add_all([
            ScheduleCandidate(id=f"candidate-{key}", schedule_id=f"schedule-{key}",
                              drama_id=f"drama-{key}", candidate_type="backup", rank_number=1,
                              reason="test", status="available", tenant_id=f"tenant-{key}")
            for key in ("a", "b")
        ])
        session.commit()


def test_http_candidate_write_creates_own_candidate(tenant_client, channel_store):
    response = tenant_client.post("/api/v3/schedules/schedule-a/candidates", json={
        "drama_id": "drama-a", "rank_number": 2, "reason": "own candidate",
    })
    assert response.status_code == 201, response.text
    with Session(channel_store) as session:
        candidate = session.get(ScheduleCandidate, response.json()["id"])
        assert (candidate.schedule_id, candidate.drama_id, candidate.status) == (
            "schedule-a", "drama-a", "available",
        )
        assert session.scalar(sa.select(sa.func.count()).select_from(ScheduleCandidate)
                              .where(ScheduleCandidate.schedule_id == "schedule-b")) == 0


def test_http_candidate_write_selects_own_candidate(tenant_client, channel_store, schedule_candidates):
    response = tenant_client.post("/api/v3/schedules/schedule-a/candidates/candidate-a/select", json={
        "reason": "select own candidate",
    })
    assert response.status_code == 200, response.text
    assert response.json()["id"] == "schedule-a"
    with Session(channel_store) as session:
        assert session.get(ScheduleCandidate, "candidate-a").status == "selected"
        assert session.get(ScheduleCandidate, "candidate-b").status == "available"


@pytest.mark.parametrize("path,payload", [
    ("/schedules/schedule-b/candidates", {"drama_id": "drama-a", "rank_number": 2, "reason": "test"}),
    ("/schedules/schedule-b/candidates/candidate-b/select", {"reason": "test"}),
    ("/schedules/schedule-a/candidates/candidate-b/select", {"reason": "test"}),
])
def test_http_candidate_write_foreign_schedule_or_candidate_is_404(
    tenant_client, channel_store, schedule_candidates, path, payload,
):
    response = tenant_client.post(f"/api/v3{path}", json=payload)
    assert response.status_code == 404, response.text
    with Session(channel_store) as session:
        assert session.execute(sa.select(ScheduleCandidate.id, ScheduleCandidate.status)
                               .order_by(ScheduleCandidate.id)).all() == [
            ("candidate-a", "available"), ("candidate-b", "available"),
        ]


@pytest.mark.parametrize("channel_id,status", [("a", 200), ("b", 404)])
def test_http_media_assets_channel_filter_authorizes_owner(tenant_client, channel_id, status):
    response = tenant_client.get("/api/v3/media-assets", params={"channel_id": channel_id})
    assert response.status_code == status, response.text
    if status == 200:
        assert [row["id"] for row in response.json()] == ["asset-a"]
