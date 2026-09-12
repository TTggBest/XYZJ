"""Task 5 behavior tests. SQLite is an isolated ORM fixture, not a product DB."""
from dataclasses import replace
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

from zhiju import auth_context, database
from zhiju.api import drama_library as library_api, drama_progress as progress_api
from zhiju.api import history as history_api, operations as operations_api
from zhiju.auth_context import Principal
from zhiju.app import create_app
from zhiju.database import TenantSession
from zhiju.models import (
    Base, Channel, ChannelDnaVersion, ChannelPlaylist, ChannelPublishSlot,
    ChannelScheduleEntry, Drama, DramaAlias, DramaCoreTerm, DramaProductionState,
    DramaTranslation, Language, PublishCadenceTemplateSlot, ScheduleCandidate,
    ScheduleChangeHistory,
)
from zhiju.schemas.operations import DramaTranslationUpsert, ScheduleCandidateCreate
from zhiju.services import drama_library, drama_progress, operations


ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = Principal("user-a", "tenant-a", "owner", None, None, "normal", frozenset())
CHILD_PARENTS = {
    "drama_aliases": {"drama_id": "dramas"},
    "drama_core_terms": {"drama_id": "dramas"},
    "drama_translations": {"drama_id": "dramas"},
    "drama_production_states": {"drama_id": "dramas"},
    "schedule_candidates": {"schedule_id": "channel_schedule_entries", "drama_id": "dramas"},
    "schedule_change_history": {"schedule_id": "channel_schedule_entries", "old_drama_id": "dramas", "new_drama_id": "dramas"},
}


@pytest.fixture
def migration():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    revision = next((r for r in ScriptDirectory.from_config(config).walk_revisions()
                     if r.revision == "d3f6a9b4c832"), None)
    return revision.module if revision else None


def install_migration(migration, connection, monkeypatch):
    assert migration is not None, "Task 5 drama/schedule migration is missing"
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))


@pytest.fixture
def legacy_graph():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        for name in ("channels", "dramas"):
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True),
                     sa.Column("tenant_id", sa.String(36)))
        sa.Table("channel_schedule_entries", metadata, sa.Column("id", sa.String(36), primary_key=True),
                 sa.Column("tenant_id", sa.String(36)), sa.Column("channel_id", sa.String(36)),
                 sa.Column("drama_id", sa.String(36)))
        for name, parents in CHILD_PARENTS.items():
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True),
                     *(sa.Column(column, sa.String(36)) for column in parents))
        metadata.create_all(connection)
        for name in ("channels", "dramas"):
            connection.execute(metadata.tables[name].insert(), [
                {"id": key, "tenant_id": f"tenant-{key}"} for key in ("a", "b")])
        connection.execute(metadata.tables["channel_schedule_entries"].insert(), [
            {"id": key, "tenant_id": f"tenant-{key}", "channel_id": key, "drama_id": key}
            for key in ("a", "b")])
        for name, parents in CHILD_PARENTS.items():
            connection.execute(metadata.tables[name].insert(), [
                {"id": key, **{column: key for column in parents}} for key in ("a", "b")])
        yield connection
    engine.dispose()


def test_migration_backfills_every_child_and_orm_scopes_it(migration, legacy_graph, monkeypatch):
    install_migration(migration, legacy_graph, monkeypatch)
    migration.upgrade()
    for name in CHILD_PARENTS:
        assert legacy_graph.execute(sa.text(f"SELECT id, tenant_id FROM {name} ORDER BY id")).all() == [
            ("a", "tenant-a"), ("b", "tenant-b")]
        model = next(m.class_ for m in Base.registry.mappers if m.local_table.name == name)
        with TenantSession(bind=legacy_graph, info={"tenant_id": "tenant-a"}) as session:
            assert session.scalars(sa.select(model.id)).all() == ["a"], name
    migration.downgrade()
    for name in CHILD_PARENTS:
        assert "tenant_id" not in {c["name"] for c in sa.inspect(legacy_graph).get_columns(name)}
        assert legacy_graph.scalar(sa.text(f"SELECT COUNT(*) FROM {name}")) == 2


@pytest.mark.parametrize("table,column,value", [
    (table, column, value)
    for table, parents in CHILD_PARENTS.items() for column in parents
    for value in (["missing", "b"] if len(parents) > 1 else ["missing", None])
] + [
    ("channel_schedule_entries", "channel_id", "b"),
    ("channel_schedule_entries", "drama_id", "b"),
    ("channel_schedule_entries", "tenant_id", "tenant-b"),
    ("channel_schedule_entries", "channel_id", "missing"),
    ("channels", "tenant_id", None), ("dramas", "tenant_id", None),
])
def test_migration_conflict_stops_before_any_ddl(migration, legacy_graph, monkeypatch, table, column, value):
    install_migration(migration, legacy_graph, monkeypatch)
    legacy_graph.execute(sa.text(f"UPDATE {table} SET {column} = :value WHERE id = 'a'"), {"value": value})
    with pytest.raises(RuntimeError, match="tenant"):
        migration.upgrade()
    for name in CHILD_PARENTS:
        assert "tenant_id" not in {c["name"] for c in sa.inspect(legacy_graph).get_columns(name)}


def test_history_nullable_drama_references_inherit_schedule(migration, legacy_graph, monkeypatch):
    install_migration(migration, legacy_graph, monkeypatch)
    legacy_graph.execute(sa.text("UPDATE schedule_change_history SET old_drama_id=NULL, new_drama_id=NULL"))
    migration.upgrade()
    assert legacy_graph.execute(sa.text("SELECT tenant_id FROM schedule_change_history ORDER BY id")).scalars().all() == [
        "tenant-a", "tenant-b"]


@pytest.fixture
def store():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Language(id="en", code="en", name_zh="英语"))
        session.add(PublishCadenceTemplateSlot(id="template", daily_publish_count=1,
                    slot_number=1, slot_type="main", local_video_time=time(12)))
        for number, key in enumerate(("a", "b"), 1):
            objects = [
                Channel(id=key, youtube_channel_id=f"UC-{key}", original_name="同形频道", status="active"),
                ChannelDnaVersion(id=f"dna-{key}", channel_id=key, language="en", primary_genre="剧情",
                                  version_number=1, status="active"),
                ChannelPlaylist(id=f"playlist-{key}", channel_id=key, local_name="同形列表"),
                ChannelPublishSlot(id=f"slot-{key}", channel_id=key, slot_type="main", slot_number=1,
                                   local_time=time(12), timezone="Asia/Shanghai"),
                Drama(id=f"drama-{key}", drama_number=number, drama_code=f"DR-{key}",
                      chinese_title=f"剧目{key}", normalized_title=f"剧目{key}"),
                DramaAlias(id=f"alias-{key}", drama_id=f"drama-{key}", alias=f"别名{key}", normalized_alias=f"别名{key}"),
                DramaCoreTerm(id=f"term-{key}", drama_id=f"drama-{key}", term_type="keyword", term="同形关键词"),
                DramaTranslation(id=f"translation-{key}", drama_id=f"drama-{key}", language_id="en",
                                 translated_title=f"Title {key}", translation_status="ready", asset_status="ready"),
                DramaProductionState(id=f"state-{key}", drama_id=f"drama-{key}",
                                     **{field: "completed" for field in operations.SCHEDULABLE_PRODUCTION_FIELDS}),
                ChannelScheduleEntry(id=f"schedule-{key}", channel_id=key, drama_id=f"drama-{key}",
                    publish_slot_id=f"slot-{key}", publish_date=date(2026, 9, 12), idempotency_key=f"schedule-{key}",
                    planned_local_time=datetime(2026, 9, 12, 12), planned_beijing_time=datetime(2026, 9, 12, 12),
                    planned_utc_time=datetime(2026, 9, 12, 4)),
                ScheduleCandidate(id=f"candidate-{key}", schedule_id=f"schedule-{key}", drama_id=f"drama-{key}",
                                  candidate_type="backup", rank_number=1, reason="test"),
                ScheduleChangeHistory(id=f"history-{key}", schedule_id=f"schedule-{key}", new_drama_id=f"drama-{key}",
                    new_status="planned", reason="test", actor_type="system", changed_at=datetime(2026, 9, 12)),
            ]
            for obj in objects:
                obj.tenant_id = f"tenant-{key}"
            session.add_all(objects)
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def client(store, monkeypatch):
    app = create_app()
    def unscoped():
        with Session(store) as session:
            yield session
    app.dependency_overrides[database.get_db] = unscoped
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    monkeypatch.setattr(database.database_router, "get_active_engine", lambda: store)
    with TestClient(app) as http:
        yield http


@pytest.mark.parametrize("path,key,expected", [
    ("/dramas", "id", "drama-a"), ("/dramas/library", "id", "drama-a"),
    ("/drama-production", "drama_id", "drama-a"), ("/drama-translations", "id", "translation-a"),
    ("/drama-translations/matrix", "drama_id", "drama-a"),
    ("/schedules/eligible-dramas", "id", "drama-a"),
    ("/schedules/schedule-a/candidates", "id", "candidate-a"),
    ("/schedules/schedule-a/history", "id", "history-a"),
    ("/channels/a/playlists", "id", "playlist-a"), ("/channels/a/publish-slots", "id", "slot-a"),
])
def test_http_lists_and_pages_only_return_principal_tenant(client, path, key, expected):
    response = client.get(f"/api/v3{path}?tenant_id=tenant-b", headers={"X-Tenant-ID": "tenant-b"})
    assert response.status_code == 200, response.text
    data = response.json()
    if isinstance(data, dict):
        assert data["total"] == 1
        data = data["items"]
    assert [row[key] for row in data] == [expected]


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/dramas/drama-b", None), ("GET", "/dramas/drama-b/translations", None),
    ("GET", "/dramas/drama-b/production-state", None),
    ("GET", "/schedules/schedule-b/candidates", None), ("GET", "/schedules/schedule-b/history", None),
    ("PATCH", "/dramas/drama-b", {"chinese_title": "changed"}),
    ("PUT", "/dramas/drama-b/languages/en", {"translation_status": "ready", "asset_status": "ready"}),
    ("DELETE", "/dramas/drama-b/languages/en", None),
    ("PUT", "/dramas/drama-b/translations/en", {"translation_status": "pending", "asset_status": "missing", "reason": "test"}),
    ("PUT", "/dramas/drama-b/production-state", {}),
    ("PUT", "/dramas/drama-b/production-state/exclusion", {"excluded": True}),
    ("POST", "/dramas/drama-b/production-state/cloud-download/complete", None),
    ("POST", "/channels/a/schedules", {"drama_id": "drama-b", "publish_slot_id": "slot-a",
                                         "publish_date": "2026-09-13", "idempotency_key": "foreign-drama"}),
    ("POST", "/schedules/schedule-a/candidates", {"drama_id": "drama-b", "rank_number": 2, "reason": "test"}),
    ("POST", "/schedules/schedule-a/candidates/candidate-b/select", {"reason": "test"}),
    ("PATCH", "/schedules/schedule-b/source-video", {"source_video_id": "abcdefghijk"}),
    ("PATCH", "/schedules/schedule-b/status", {"status": "cancelled", "reason": "test"}),
])
def test_foreign_ids_are_404_without_mutation(client, store, method, path, payload):
    response = client.request(method, f"/api/v3{path}", json=payload)
    assert response.status_code == 404, response.text
    with Session(store) as session:
        assert session.get(Drama, "drama-b").chinese_title == "剧目b"
        assert session.get(DramaTranslation, "translation-b").translated_title == "Title b"
        assert session.get(ChannelScheduleEntry, "schedule-a").drama_id == "drama-a"
        assert session.get(ScheduleCandidate, "candidate-b").status == "available"


def test_alias_search_hides_foreign_titles(client):
    assert client.get("/api/v3/dramas/match", params={"title": "别名b"}).json() is None
    assert client.get("/api/v3/dramas/match", params={"title": "别名a"}).json()["id"] == "drama-a"


@pytest.mark.parametrize("operation", [
    lambda s: drama_library.get_drama_library_detail(s, "drama-b"),
    lambda s: drama_progress.get_drama_progress(s, "drama-b"),
    lambda s: operations.upsert_drama_translation(s, "drama-b", "en", DramaTranslationUpsert(
        translation_status="pending", asset_status="missing", reason="test")),
    lambda s: operations.create_schedule_candidate(s, "schedule-a", ScheduleCandidateCreate(
        drama_id="drama-b", rank_number=2, reason="test")),
])
def test_cached_foreign_drama_cannot_bypass_service_authorization(store, operation):
    with Session(store) as unscoped:
        foreign = unscoped.get(Drama, "drama-b")
        unscoped.expunge(foreign)
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as session:
        session.add(foreign)
        with pytest.raises(HTTPException) as error:
            operation(session)
        assert error.value.status_code == 404


def test_own_edits_stamp_children_and_leave_other_tenant_unchanged(client, store):
    response = client.patch("/api/v3/dramas/drama-a", json={"chinese_title": "剧目a", "aliases": ["new alias"],
        "core_terms": [{"term_type": "keyword", "term": "new term"}], "tenant_id": "tenant-b"})
    assert response.status_code == 200, response.text
    response = client.post("/api/v3/schedules/schedule-a/candidates/candidate-a/select", json={"reason": "choose"})
    assert response.status_code == 200, response.text
    with Session(store) as session:
        for model in (DramaAlias, DramaCoreTerm):
            assert session.scalar(sa.select(model).where(model.drama_id == "drama-a")).tenant_id == "tenant-a"
        rows = session.scalars(sa.select(ScheduleChangeHistory).where(ScheduleChangeHistory.schedule_id == "schedule-a")).all()
        assert len(rows) == 2 and {row.tenant_id for row in rows} == {"tenant-a"}
        assert session.get(DramaAlias, "alias-b").alias == "别名b"
        assert session.get(ScheduleCandidate, "candidate-b").status == "available"


@pytest.mark.parametrize("path", ["/languages", "/cadence-templates"])
def test_shared_catalog_reads_require_login_but_remain_shared(client, path):
    assert client.get(f"/api/v3{path}").status_code == 200
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(
        PRINCIPAL, tenant_id=None, membership_role=None, platform_role="super_admin")
    assert client.get(f"/api/v3{path}").status_code == 200
    client.app.dependency_overrides.pop(auth_context.get_current_principal)
    assert client.get(f"/api/v3{path}").status_code == 401


@pytest.mark.parametrize("method,path,payload", [
    ("POST", "/languages", {"code": "fr", "name_zh": "法语"}),
    ("PUT", "/cadence-templates/1", {"slots": [{"slot_number": 1, "slot_type": "main", "local_video_time": "13:00:00"}]}),
])
def test_only_platform_permission_can_write_shared_catalog(client, method, path, payload):
    response = client.request(method, f"/api/v3{path}", json=payload)
    assert response.status_code == 403, response.text
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(PRINCIPAL, platform_role="super_admin")
    response = client.request(method, f"/api/v3{path}", json=payload)
    assert response.status_code in (200, 201), response.text
