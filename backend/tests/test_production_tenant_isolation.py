"""Production tenant boundaries; SQLite is used only for isolated ORM fixtures."""
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju import auth_context, database
from zhiju.app import create_app
from zhiju.auth_context import Principal
from zhiju.database import TenantSession
from zhiju.models import (
    Base, Channel, ChannelDnaVersion, ChannelPlaylist, ChannelPublishSlot,
    ChannelScheduleEntry, CommunityPostAsset, Drama, MediaAsset, OperationPackage,
    OperationTask, PackageArtifact, PackageCommunityPost, PackageCoverVariant,
    PackageCreativeSlot, PackageDescription, PackageOutputCopyState,
    PackagePlaylistAssignment, PackageSimilarityCheck, PackageTitle,
    PackageValidationResult, ProductionBatch, ProductionNodeRun, SystemEvent,
    TaskEvent, WorkOrder,
)
from zhiju.services import package_outputs, production

ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = Principal("user-a", "tenant-a", "owner", None, None, "normal", frozenset())
CHILDREN = (OperationTask, TaskEvent, WorkOrder, OperationPackage, ProductionNodeRun,
            PackageTitle, PackageDescription, PackageCoverVariant, PackageCommunityPost,
            CommunityPostAsset, PackagePlaylistAssignment, PackageCreativeSlot,
            PackageArtifact, PackageValidationResult, PackageSimilarityCheck, PackageOutputCopyState)


@pytest.fixture
def store():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for number, key in enumerate(("a", "b"), 1):
            objects = [
                Channel(id=f"channel-{key}", youtube_channel_id=f"UC-{key}", original_name="同形频道", status="active"),
                Drama(id=f"drama-{key}", drama_number=number, drama_code=f"DR-{key}",
                      chinese_title=f"剧目{key}", normalized_title=f"剧目{key}", content_summary="剧情"),
                ChannelPlaylist(id=f"playlist-{key}", channel_id=f"channel-{key}", local_name="同形列表"),
                ChannelPublishSlot(id=f"slot-{key}", channel_id=f"channel-{key}", slot_type="main",
                                   slot_number=1, local_time=time(12), timezone="Asia/Shanghai"),
                ChannelScheduleEntry(id=f"schedule-{key}", channel_id=f"channel-{key}", drama_id=f"drama-{key}",
                    publish_slot_id=f"slot-{key}", publish_date=date(2026, 9, 13), idempotency_key=f"schedule-{key}",
                    planned_local_time=datetime(2026, 9, 13, 12), planned_beijing_time=datetime(2026, 9, 13, 12),
                    planned_utc_time=datetime(2026, 9, 13, 4)),
                ProductionBatch(id=f"batch-{key}", batch_number=f"batch-{key}", production_date=date(2026, 9, 13), source="native"),
                OperationTask(id=f"task-{key}", batch_id=f"batch-{key}", channel_id=f"channel-{key}",
                    drama_id=f"drama-{key}", task_date=date(2026, 9, 13), target_publish_date=date(2026, 9, 13),
                    source="manual", idempotency_key=f"task-key-{key}", status="dispatched", community_count=1),
                WorkOrder(id=f"work-{key}", task_id=f"task-{key}", batch_id=f"batch-{key}",
                    channel_id=f"channel-{key}", drama_id=f"drama-{key}", production_date=date(2026, 9, 13),
                    target_publish_date=date(2026, 9, 13), community_count=1),
                OperationPackage(id=f"package-{key}", work_order_id=f"work-{key}", batch_id=f"batch-{key}",
                    channel_id=f"channel-{key}", drama_id=f"drama-{key}", status="review_pending"),
                TaskEvent(id=f"event-{key}", task_id=f"task-{key}", new_status="dispatched", reason="test",
                          actor_type="system", occurred_at=datetime(2026, 9, 13)),
                PackageTitle(id=f"title-{key}", package_id=f"package-{key}", variant_number=1,
                             localized_title=f"title {key}", selected=True, status="selected"),
                PackageDescription(id=f"description-{key}", package_id=f"package-{key}", version_number=1,
                                   language="en", localized_text=f"description {key}", selected=True),
                MediaAsset(id=f"asset-{key}", channel_id=f"channel-{key}", operation_package_id=f"package-{key}",
                    storage_provider="local", storage_key=f"{key}.png", sha256="test", file_size_bytes=10,
                    asset_type="image", asset_role="community_image", status="ready", width=1280, height=720),
                PackageCoverVariant(id=f"cover-{key}", package_id=f"package-{key}", title_id=f"title-{key}",
                                    aspect_ratio="16:9", creative_prompt="prompt", selected=True),
                PackageCommunityPost(id=f"post-{key}", package_id=f"package-{key}", sequence_number=1,
                                     language="en", localized_text="post", selected=True),
                CommunityPostAsset(id=f"postasset-{key}", community_post_id=f"post-{key}", asset_id=f"asset-{key}", position_number=1),
                PackagePlaylistAssignment(id=f"assignment-{key}", package_id=f"package-{key}", playlist_id=f"playlist-{key}", rank_number=1),
                PackageCreativeSlot(id=f"creative-{key}", package_id=f"package-{key}", title_hook="hook"),
                PackageArtifact(id=f"artifact-{key}", package_id=f"package-{key}", artifact_format="json", generation_number=1,
                                storage_provider="local", storage_key=f"{key}.json"),
                PackageValidationResult(id=f"validation-{key}", package_id=f"package-{key}", validator_code="test",
                                        result="pass", message="ok", checked_at=datetime(2026, 9, 13)),
                PackageSimilarityCheck(id=f"similarity-{key}", package_id=f"package-{key}", compared_package_id=f"package-{key}",
                                       title_similarity=0.5, result="pass", checked_at=datetime(2026, 9, 13)),
                PackageOutputCopyState(id=f"copy-{key}", package_id=f"package-{key}", output_type="title",
                                       output_id=f"title-{key}", copied_at=datetime(2026, 9, 13)),
            ]
            objects.extend(ProductionNodeRun(id=f"{node}-{key}", work_order_id=f"work-{key}", package_id=f"package-{key}",
                node_type=node, sequence_number=index, attempt_number=2, idempotency_key=f"{node}-{key}",
                status="queued" if node == "search" else "running") for index, node in enumerate(production.NODE_SEQUENCE, 1))
            for obj in objects:
                obj.tenant_id = f"tenant-{key}"
            session.add_all(objects)
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def client(store, monkeypatch, tmp_path):
    app = create_app()
    def unscoped():
        with Session(store) as session:
            yield session
    app.dependency_overrides[database.get_db] = unscoped
    app.dependency_overrides[auth_context.get_current_principal] = lambda: PRINCIPAL
    monkeypatch.setattr(database.database_router, "get_active_engine", lambda: store)
    monkeypatch.setattr(package_outputs, "get_settings", lambda: SimpleNamespace(artifact_root=str(tmp_path)))
    with TestClient(app, raise_server_exceptions=False) as http:
        yield http


@pytest.mark.parametrize("path,key,want", [
    ("/tasks", "id", "task-a"), ("/tasks/overview", "task_id", "task-a"),
    ("/work-orders", "id", "work-a"), ("/work-orders/overview", "work_order_id", "work-a"),
    ("/packages/operations-overview", "package_id", "package-a"),
])
def test_lists_do_not_leak_other_tenant(client, path, key, want):
    response = client.get(f"/api/v3{path}?tenant_id=tenant-b", headers={"X-Tenant-ID": "tenant-b"})
    assert response.status_code == 200, response.text
    assert [row[key] for row in response.json()] == [want]


@pytest.mark.parametrize("method,path,payload", [
    ("POST", "/tasks", {"schedule_id": "schedule-b", "task_date": "2026-09-13", "idempotency_key": "foreign-task"}),
    ("POST", "/tasks/task-b/dispatch", None),
    ("PATCH", "/tasks/task-b/source-video", {"source_video_id": "abcdefghijk"}),
    ("GET", "/work-orders/work-b", None),
    ("POST", "/work-orders/work-b/nodes/search/start", {"worker_key": "worker-a"}),
    ("POST", "/work-orders/work-b/nodes/title/finish", {"success": False}),
    ("POST", "/work-orders/work-b/nodes/title/retry", {"reason": "retry"}),
    ("POST", "/packages/package-b/review", {"decision": "approved"}),
    ("GET", "/packages/package-b/outputs", None),
    ("GET", "/packages/package-b/copy-progress", None),
    ("PUT", "/packages/package-b/copy-progress", {"output_type": "title", "output_id": "00000000-0000-4000-8000-000000000002"}),
    ("POST", "/packages/package-b/outputs/titles", {"titles": [{"variant_number": i, "localized_title": "new"} for i in (1, 2, 3)]}),
    ("POST", "/packages/package-b/outputs/covers", {"covers": [{"title_id": "title-b", "aspect_ratio": "16:9", "creative_prompt": "new"}]}),
    ("POST", "/packages/package-b/outputs/description", {"language": "en", "localized_text": "new"}),
    ("POST", "/packages/package-b/outputs/community", {"posts": [{"sequence_number": 1, "language": "en", "localized_text": "new"}]}),
    ("POST", "/packages/package-b/validations", {"validator_code": "new", "result": "pass", "message": "ok"}),
    ("GET", "/packages/package-b/similarity-checks", None),
    ("PUT", "/packages/package-a/similarity-checks/package-b", {"title_similarity": 0.5, "result": "pass"}),
    ("POST", "/packages/package-b/merge", None),
])
def test_foreign_ids_are_404_before_state_or_artifact_mutation(client, store, tmp_path, method, path, payload):
    response = client.request(method, f"/api/v3{path}?tenant_id=tenant-b", json=payload,
                              headers={"X-Tenant-ID": "tenant-b"})
    assert response.status_code == 404, response.text
    with Session(store) as session:
        assert session.get(OperationTask, "task-b").status == "dispatched"
        assert session.get(OperationTask, "task-b").source_video_id is None
        assert session.get(ProductionNodeRun, "search-b").status == "queued"
        assert session.get(ProductionNodeRun, "title-b").status == "running"
        assert session.get(OperationPackage, "package-b").status == "review_pending"
        assert session.scalar(sa.select(sa.func.count()).select_from(PackageTitle)) == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(PackageDescription)) == 2
        assert session.scalar(sa.select(sa.func.count()).select_from(SystemEvent)) == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("model", CHILDREN)
def test_child_queries_are_scoped_even_without_a_parent_filter(store, model):
    with TenantSession(bind=store, info={"tenant_id": "tenant-a"}) as session:
        ids = session.scalars(sa.select(model.id)).all()
        assert ids and all(row_id.endswith("-a") for row_id in ids)


@pytest.mark.parametrize("operation", [
    lambda s: production.get_work_order_detail(s, "work-b"),
    lambda s: production.dispatch_task(s, "task-b"),
    lambda s: production.start_node(s, "work-b", "search", "worker-a"),
    lambda s: production.finish_node(s, "work-b", "title", success=False),
    lambda s: production.retry_node(s, "work-b", "title", "test"),
    lambda s: production.review_package(s, "package-b", "approved", None),
    lambda s: package_outputs.get_package_outputs(s, "package-b"),
    lambda s: package_outputs.merge_package(s, "package-b"),
])
def test_cached_foreign_objects_cannot_bypass_service_lookup(store, operation):
    with Session(store) as plain:
        foreign = [plain.get(model, key) for model, key in (
            (WorkOrder, "work-b"), (OperationTask, "task-b"), (OperationPackage, "package-b"))]
        plain.expunge_all()
    with TenantSession(bind=store, info={"tenant_id": "tenant-a"}) as session:
        for obj in foreign:
            session.add(obj)
        with pytest.raises(HTTPException) as exc:
            operation(session)
        assert exc.value.status_code == 404


def test_own_node_actions_restore_persisted_tenant_and_write_owned_events(client, store):
    response = client.post("/api/v3/work-orders/work-a/nodes/search/start?tenant_id=tenant-b",
                           json={"worker_key": "internal-worker", "tenant_id": "tenant-b"})
    assert response.status_code == 200, response.text
    response = client.post("/api/v3/work-orders/work-a/nodes/search/finish", json={"success": False})
    assert response.status_code == 200, response.text
    response = client.post("/api/v3/work-orders/work-a/nodes/search/retry", json={"reason": "test"})
    assert response.status_code == 200, response.text
    with Session(store) as session:
        nodes = session.scalars(sa.select(ProductionNodeRun).where(ProductionNodeRun.work_order_id == "work-a")).all()
        assert all(node.tenant_id == "tenant-a" for node in nodes)
        assert any(node.node_type == "search" and node.attempt_number == 3 for node in nodes)
        assert {row.tenant_id for row in session.scalars(sa.select(SystemEvent))} == {"tenant-a"}
        assert session.get(ProductionNodeRun, "search-b").status == "queued"


def test_node_missing_or_conflicting_owner_is_not_inferred_from_work_order(client, store):
    assert hasattr(ProductionNodeRun, "tenant_id"), "node tenant ownership is missing"
    for tenant_id in (None, "tenant-b"):
        with Session(store) as session:
            session.get(ProductionNodeRun, "search-a").tenant_id = tenant_id
            session.commit()
        response = client.post("/api/v3/work-orders/work-a/nodes/search/start", json={"worker_key": "worker"})
        assert response.status_code == 404, response.text


@pytest.mark.parametrize("endpoint,payload", [
    ("covers", {"covers": [{"title_id": "title-b", "aspect_ratio": "16:9", "creative_prompt": "new"}]}),
    ("description", {"language": "en", "localized_text": "new", "playlist_id": "playlist-b"}),
    ("community", {"posts": [{"sequence_number": 1, "language": "en", "localized_text": "new", "asset_ids": ["asset-b"]}]}),
])
def test_foreign_output_parents_are_404_before_superseding_existing_rows(client, store, endpoint, payload):
    response = client.post(f"/api/v3/packages/package-a/outputs/{endpoint}", json=payload)
    assert response.status_code == 404, response.text
    with Session(store) as session:
        assert session.get(PackageDescription, "description-a").selected is True
        assert session.get(PackageCommunityPost, "post-a").selected is True
        assert session.scalar(sa.select(sa.func.count()).select_from(PackageDescription)) == 2


def test_created_task_dispatch_and_outputs_inherit_current_tenant(client, store):
    response = client.post("/api/v3/tasks", json={"schedule_id": "schedule-a", "task_date": "2026-09-14",
                           "idempotency_key": "new-schedule-a", "tenant_id": "tenant-b"})
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    response = client.post(f"/api/v3/tasks/{task_id}/dispatch")
    assert response.status_code == 200, response.text
    detail = response.json()
    package_id = detail["package"]["id"]
    work_id = detail["work_order"]["id"]
    for action in ("start", "finish"):
        payload = {"worker_key": "internal"} if action == "start" else {"success": True}
        response = client.post(f"/api/v3/work-orders/{work_id}/nodes/search/{action}", json=payload)
        assert response.status_code == 200, response.text
    response = client.post(f"/api/v3/work-orders/{work_id}/nodes/title/start", json={"worker_key": "internal"})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v3/packages/{package_id}/outputs/titles", json={"titles": [
        {"variant_number": i, "localized_title": f"new {i}"} for i in (1, 2, 3)],
        "creative_slot": {"title_hook": "new hook"}})
    assert response.status_code == 200, response.text
    with Session(store) as session:
        for model, condition in (
            (OperationTask, OperationTask.id == task_id), (WorkOrder, WorkOrder.id == work_id),
            (OperationPackage, OperationPackage.id == package_id),
            (ProductionNodeRun, ProductionNodeRun.work_order_id == work_id),
            (TaskEvent, TaskEvent.task_id == task_id),
            (PackageTitle, PackageTitle.package_id == package_id),
            (PackageCreativeSlot, PackageCreativeSlot.package_id == package_id),
        ):
            rows = session.scalars(sa.select(model).where(condition)).all()
            assert rows and all(row.tenant_id == "tenant-a" for row in rows)


def test_copy_rejects_foreign_output_id_in_own_package(client, store):
    foreign_id = "00000000-0000-4000-8000-000000000002"
    with Session(store) as session:
        session.add(PackageTitle(id=foreign_id, tenant_id="tenant-b", package_id="package-b",
                                variant_number=2, localized_title="foreign"))
        session.commit()
    response = client.put("/api/v3/packages/package-a/copy-progress",
                          json={"output_type": "title", "output_id": foreign_id})
    assert response.status_code == 404, response.text
    with Session(store) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(PackageOutputCopyState)) == 2


@pytest.fixture
def migration():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    revision = next((r for r in ScriptDirectory.from_config(config).walk_revisions()
                     if r.revision == "e4a7b0c5d943"), None)
    return revision.module if revision else None


# Literal graph independent of migration's parent map. The migration preflight is
# pure row validation; DDL is recorded here and later exercised on backed-up MySQL.
LEGACY_PARENTS = {
    "production_batches": {}, "channels": {}, "dramas": {},
    "channel_dna_versions": {"channel_id": "channels"},
    "channel_publish_slots": {"channel_id": "channels"},
    "channel_playlists": {"channel_id": "channels"},
    "channel_schedule_entries": {"channel_id": "channels", "drama_id": "dramas", "publish_slot_id": "channel_publish_slots", "playlist_id": "channel_playlists", "channel_dna_version_id": "channel_dna_versions"},
    "operation_tasks": {"batch_id": "production_batches", "channel_id": "channels", "drama_id": "dramas", "schedule_id": "channel_schedule_entries", "publish_slot_id": "channel_publish_slots", "playlist_id": "channel_playlists"},
    "task_events": {"task_id": "operation_tasks"},
    "work_orders": {"task_id": "operation_tasks", "batch_id": "production_batches", "schedule_id": "channel_schedule_entries", "channel_id": "channels", "drama_id": "dramas", "channel_dna_version_id": "channel_dna_versions", "publish_slot_id": "channel_publish_slots", "playlist_id": "channel_playlists"},
    "operation_packages": {"work_order_id": "work_orders", "batch_id": "production_batches", "schedule_id": "channel_schedule_entries", "channel_id": "channels", "drama_id": "dramas", "channel_dna_version_id": "channel_dna_versions"},
    "media_assets": {"channel_id": "channels", "operation_package_id": "operation_packages"},
    "production_node_runs": {"work_order_id": "work_orders", "package_id": "operation_packages"},
    "package_titles": {"package_id": "operation_packages"},
    "package_descriptions": {"package_id": "operation_packages"},
    "package_cover_variants": {"package_id": "operation_packages", "title_id": "package_titles", "asset_id": "media_assets"},
    "package_community_posts": {"package_id": "operation_packages"},
    "community_post_assets": {"community_post_id": "package_community_posts", "asset_id": "media_assets"},
    "package_playlist_assignments": {"package_id": "operation_packages", "playlist_id": "channel_playlists"},
    "package_creative_slots": {"package_id": "operation_packages"},
    "package_artifacts": {"package_id": "operation_packages"},
    "package_validation_results": {"package_id": "operation_packages"},
    "package_similarity_checks": {"package_id": "operation_packages", "compared_package_id": "operation_packages"},
    "package_output_copy_states": {"package_id": "operation_packages"},
}


@pytest.fixture
def legacy_rows():
    existing = {"production_batches", "channels", "dramas", "channel_dna_versions", "channel_publish_slots",
                "channel_playlists", "channel_schedule_entries", "media_assets"}
    rows = {name: [{"id": key, **{column: key for column in parents},
                   **({"tenant_id": f"tenant-{key}"} if name in existing else {})}
                  for key in ("a", "b")] for name, parents in LEGACY_PARENTS.items()}
    rows["system_events"] = [{"id": "event-a", "tenant_id": "tenant-a", "entity_type": "operation_task", "entity_id": "a"}]
    for row in rows["package_output_copy_states"]:
        row.update(output_type="title", output_id=row["id"])
    return rows


def test_migration_derives_all_child_owners_from_agreeing_parents(migration, legacy_rows):
    assert migration is not None, "Task 6 migration is missing"
    owners = migration.validate_owners(legacy_rows)
    for model in CHILDREN:
        assert owners[model.__tablename__] == {"a": "tenant-a", "b": "tenant-b"}


@pytest.mark.parametrize("table,column,value", [
    (table, column, value) for table, parents in LEGACY_PARENTS.items()
    for column in parents for value in (("missing", "b") if len(parents) > 1 or table.startswith("channel_") else ("missing", None))
] + [("channels", "tenant_id", None), ("production_batches", "tenant_id", None),
     ("media_assets", "tenant_id", "tenant-b"), ("system_events", "tenant_id", "tenant-b")])
def test_migration_rejects_each_orphan_and_cross_tenant_parent(migration, legacy_rows, table, column, value):
    assert migration is not None, "Task 6 migration is missing"
    legacy_rows[table][0][column] = value
    with pytest.raises(RuntimeError, match=rf"{table}:.*tenant"):
        migration.validate_owners(legacy_rows)


def test_migration_conflict_precedes_any_ddl(migration, legacy_rows, monkeypatch):
    assert migration is not None, "Task 6 migration is missing"
    legacy_rows["package_similarity_checks"][0]["compared_package_id"] = "b"
    ops = Mock()
    monkeypatch.setattr(migration, "op", ops)
    monkeypatch.setattr(migration, "load_rows", lambda connection: legacy_rows)
    with pytest.raises(RuntimeError, match="package_similarity_checks:a"):
        migration.upgrade()
    assert ops.method_calls == [("get_bind", (), {})]


@pytest.mark.parametrize("output_type,target", [
    ("title", "package_titles"), ("cover", "package_cover_variants"),
    ("description", "package_descriptions"), ("community_text", "package_community_posts"),
    ("community_image", "package_community_posts"),
])
@pytest.mark.parametrize("output_id", ["b", "missing"])
def test_migration_rejects_foreign_or_missing_copy_target(migration, legacy_rows, output_type, target, output_id):
    legacy_rows["package_output_copy_states"][0].update(output_type=output_type, output_id=output_id)
    with pytest.raises(RuntimeError, match="package_output_copy_states:a.*tenant"):
        migration.validate_owners(legacy_rows)


def test_migration_accepts_documented_optional_links_but_rejects_missing_required_slot(migration, legacy_rows):
    for name, columns in {
        "operation_tasks": ("batch_id", "schedule_id", "playlist_id", "publish_slot_id"),
        "work_orders": ("batch_id", "schedule_id", "playlist_id", "publish_slot_id", "channel_dna_version_id"),
        "operation_packages": ("batch_id", "schedule_id", "channel_dna_version_id"),
        "package_cover_variants": ("asset_id",),
        "media_assets": ("channel_id", "operation_package_id"),
        "channel_schedule_entries": ("playlist_id", "channel_dna_version_id"),
    }.items():
        for row in legacy_rows[name]:
            row.update({column: None for column in columns})
    assert migration.validate_owners(legacy_rows)["operation_packages"] == {"a": "tenant-a", "b": "tenant-b"}
    legacy_rows["channel_schedule_entries"][0]["publish_slot_id"] = None
    with pytest.raises(RuntimeError, match="channel_schedule_entries:a.*tenant"):
        migration.validate_owners(legacy_rows)
