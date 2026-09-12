from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from zhiju import auth_context, database
from zhiju.api import history as history_api
from zhiju.api import identity as identity_api
from zhiju.api import settings as settings_api
from zhiju.api import skill as skill_api
from zhiju.app import app
from zhiju.database import TenantSession
from zhiju.models import (
    AppIconSetting,
    AccountChannelAuthorization,
    AuditEvent,
    Base,
    Channel,
    ChannelAnalysisReport,
    ChannelCommunitySlot,
    ChannelDnaVersion,
    ChannelDramaType,
    ChannelKeyword,
    ChannelPinnedCommentTemplate,
    ChannelPlaylist,
    ChannelProfile,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    Device,
    DemoDataBatch,
    Drama,
    DramaTranslation,
    GoogleAccount,
    ImageProcessingRun,
    IntegrationAccount,
    IntegrationCredential,
    MediaAsset,
    OAuthGrant,
    OperationPackage,
    OperationTask,
    ProductionBatch,
    ProductionNodeRun,
    RuntimePackageBuild,
    ScheduleCandidate,
    ScheduleChangeHistory,
    Skill,
    SyncWatermark,
    SystemEvent,
    TaskEvent,
    WorkOrder,
    YoutubeComment,
    YoutubeCommentReply,
    YoutubeVideo,
    YoutubeVideoPlaylistMembership,
    YoutubeVideoStatusHistory,
)
from zhiju.permissions import require_platform_permission
from zhiju.schemas.settings import ChannelDramaTypeCreate, ChannelDramaTypeUpdate
from zhiju.services import history, settings
from zhiju.services.channel import NotFoundError
from zhiju.services.image_processing import list_processing_run_page


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store():
    engine = sa.create_engine(
        "sqlite://",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for key in ("a", "b"):
            tenant_id = f"tenant-{key}"
            task_id = f"task-{key}"
            schedule_id = f"schedule-{key}"
            video_id = f"video-{key}"
            batch_id = f"batch-{key}"
            session.add_all(
                [
                    SystemEvent(
                        id=f"system-{key}",
                        tenant_id=tenant_id,
                        entity_type="operation_task",
                        entity_id=task_id,
                        new_status="completed",
                        reason=key,
                        actor_type="system",
                        occurred_at=NOW,
                    ),
                    AuditEvent(
                        id=f"audit-{key}",
                        tenant_id=tenant_id,
                        actor_type="system",
                        action="task.updated",
                        entity_type="operation_task",
                        entity_id=task_id,
                        occurred_at=NOW,
                    ),
                    OperationTask(
                        id=task_id,
                        tenant_id=tenant_id,
                        channel_id=f"channel-{key}",
                        drama_id=f"drama-{key}",
                        task_date=date(2026, 9, 13),
                        target_publish_date=date(2026, 9, 14),
                        community_count=0,
                        source="manual",
                        status="completed",
                        idempotency_key=f"task-key-{key}",
                    ),
                    OperationTask(
                        id=f"task-empty-{key}",
                        tenant_id=tenant_id,
                        channel_id=f"channel-{key}",
                        drama_id=f"drama-{key}",
                        task_date=date(2026, 9, 13),
                        target_publish_date=date(2026, 9, 14),
                        community_count=0,
                        source="manual",
                        status="pending_dispatch",
                        idempotency_key=f"task-empty-key-{key}",
                    ),
                    TaskEvent(
                        id=f"task-event-{key}",
                        tenant_id=tenant_id,
                        task_id=task_id,
                        new_status="completed",
                        reason=key,
                        actor_type="system",
                        occurred_at=NOW,
                    ),
                    ChannelScheduleEntry(
                        id=schedule_id,
                        tenant_id=tenant_id,
                        channel_id=f"channel-{key}",
                        drama_id=f"drama-{key}",
                        publish_slot_id=f"slot-{key}",
                        publish_date=date(2026, 9, 14),
                        planned_local_time=NOW,
                        planned_beijing_time=NOW,
                        planned_utc_time=NOW,
                        community_count=0,
                        status="planned",
                        priority=100,
                        idempotency_key=f"schedule-key-{key}",
                        source_type="manual",
                    ),
                    ScheduleChangeHistory(
                        id=f"schedule-history-{key}",
                        tenant_id=tenant_id,
                        schedule_id=schedule_id,
                        new_status="planned",
                        reason=key,
                        actor_type="system",
                        changed_at=NOW,
                    ),
                    YoutubeVideo(
                        id=video_id,
                        tenant_id=tenant_id,
                        youtube_video_id=f"remote-{key}",
                        channel_id=f"channel-{key}",
                        title=key,
                        url=f"https://youtu.be/{key}",
                        privacy_status="public",
                        publish_status="published",
                        source="manual",
                    ),
                    YoutubeVideoStatusHistory(
                        id=f"video-history-{key}",
                        tenant_id=tenant_id,
                        video_id=video_id,
                        new_publish_status="published",
                        new_privacy_status="public",
                        reason=key,
                        source="manual",
                        changed_at=NOW,
                    ),
                    ProductionBatch(
                        id=batch_id,
                        tenant_id=tenant_id,
                        batch_number=f"batch-{key}",
                        production_date=date(2026, 9, 13),
                        source="native",
                        status="active",
                    ),
                    ImageProcessingRun(
                        id=f"image-run-{key}",
                        tenant_id=tenant_id,
                        batch_id=batch_id,
                        status="classified",
                        total_files=1,
                        matched_files=1,
                        unmatched_files=0,
                        generated_files=0,
                    ),
                    ChannelDramaType(
                        id=f"drama-type-{key}",
                        tenant_id=tenant_id,
                        code=f"type-{key}",
                        name=f"Type {key}",
                        sort_order=0,
                        status="active",
                    ),
                ]
            )
        session.commit()
    yield engine
    engine.dispose()


def tenant_session(store, tenant_id="tenant-a"):
    return TenantSession(
        store,
        info={
            "tenant_id": tenant_id,
            "user_id": f"user-{tenant_id}",
            "permissions": frozenset(),
        },
    )


def test_history_and_image_processing_history_return_only_current_tenant(store):
    with tenant_session(store) as session:
        assert [row.id for row in history.list_system_events(session)] == ["system-a"]
        assert [row.id for row in history.list_audit_events(session)] == ["audit-a"]
        assert {row["id"] for row in history.get_entity_timeline(
            session, "operation_task", "task-a"
        )} == {"system-a", "audit-a"}
        assert [row.id for row in history.list_task_events(session, "task-a")] == [
            "task-event-a"
        ]
        assert [row.id for row in history.list_schedule_history(session, "schedule-a")] == [
            "schedule-history-a"
        ]
        assert [row.id for row in history.list_video_status_history(session, "video-a")] == [
            "video-history-a"
        ]
        image_page = list_processing_run_page(session)
        assert image_page["total"] == 1
        assert [row.id for row in image_page["items"]] == ["image-run-a"]

        with pytest.raises(NotFoundError):
            history.list_task_events(session, "task-b")
        with pytest.raises(HTTPException) as schedule_error:
            history.list_schedule_history(session, "schedule-b")
        assert schedule_error.value.status_code == 404
        with pytest.raises(HTTPException) as video_error:
            history.list_video_status_history(session, "video-b")
        assert video_error.value.status_code == 404


def test_history_services_reject_unscoped_sessions(store):
    with Session(store) as session:
        calls = (
            lambda: history.list_system_events(session),
            lambda: history.list_audit_events(session),
            lambda: history.get_entity_timeline(session, "operation_task", "task-a"),
            lambda: history.list_task_events(session, "task-a"),
            lambda: history.list_schedule_history(session, "schedule-a"),
            lambda: history.list_video_status_history(session, "video-a"),
        )
        for call in calls:
            with pytest.raises(HTTPException, match="主账号"):
                call()


@pytest.fixture
def tenant_http_client(store):
    def override_tenant_db():
        with tenant_session(store) as session:
            yield session

    app.dependency_overrides[auth_context.get_tenant_db] = override_tenant_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_entity_timeline_hides_foreign_tenant_entity(tenant_http_client):
    response = tenant_http_client.get(
        "/api/v3/entities/operation_task/task-b/timeline"
    )

    assert response.status_code == 404


def test_entity_timeline_returns_empty_list_for_owned_entity_without_events(
    tenant_http_client,
):
    response = tenant_http_client.get(
        "/api/v3/entities/operation_task/task-empty-a/timeline"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_entity_timeline_returns_not_found_for_missing_entity(tenant_http_client):
    response = tenant_http_client.get(
        "/api/v3/entities/operation_task/task-missing/timeline"
    )

    assert response.status_code == 404


def test_entity_timeline_supports_every_business_event_entity_type():
    expected = {
        "channel": Channel,
        "channel_analysis_report": ChannelAnalysisReport,
        "channel_authorization": AccountChannelAuthorization,
        "channel_community_slot": ChannelCommunitySlot,
        "channel_dna_version": ChannelDnaVersion,
        "channel_keyword": ChannelKeyword,
        "channel_pinned_comment_template": ChannelPinnedCommentTemplate,
        "channel_playlist": ChannelPlaylist,
        "channel_profile": ChannelProfile,
        "channel_publish_slot": ChannelPublishSlot,
        "channel_schedule_entry": ChannelScheduleEntry,
        "demo_data_batch": DemoDataBatch,
        "drama": Drama,
        "drama_translation": DramaTranslation,
        "google_account": GoogleAccount,
        "integration_account": IntegrationAccount,
        "integration_credential": IntegrationCredential,
        "media_asset": MediaAsset,
        "oauth_grant": OAuthGrant,
        "operation_package": OperationPackage,
        "operation_task": OperationTask,
        "production_node_run": ProductionNodeRun,
        "schedule_candidate": ScheduleCandidate,
        "sync_watermark": SyncWatermark,
        "work_order": WorkOrder,
        "youtube_comment": YoutubeComment,
        "youtube_comment_reply": YoutubeCommentReply,
        "youtube_playlist_membership": YoutubeVideoPlaylistMembership,
        "youtube_video": YoutubeVideo,
    }

    assert getattr(history, "TIMELINE_ENTITY_MODELS", {}) == expected


def test_channel_drama_type_settings_require_tenant_session_and_scope_writes(store):
    with Session(store) as session:
        calls = (
            lambda: settings.list_channel_initialization_rules(session),
            lambda: settings.list_channel_drama_types(session),
            lambda: settings.create_channel_drama_type(
                session,
                ChannelDramaTypeCreate(
                    code="unscoped", name="Unscoped", status="active", sort_order=0
                ),
            ),
            lambda: settings.update_channel_drama_type(
                session,
                "drama-type-a",
                ChannelDramaTypeUpdate(name="Unscoped"),
            ),
        )
        for call in calls:
            with pytest.raises(HTTPException, match="主账号"):
                call()

    with tenant_session(store) as session:
        assert [row.id for row in settings.list_channel_drama_types(session)] == [
            "drama-type-a"
        ]
        created = settings.create_channel_drama_type(
            session,
            ChannelDramaTypeCreate(
                code="type-new", name="Type new", status="active", sort_order=1
            ),
        )
        assert created.tenant_id == "tenant-a"
        with pytest.raises(HTTPException) as foreign_error:
            settings.update_channel_drama_type(
                session,
                "drama-type-b",
                ChannelDramaTypeUpdate(name="Foreign update"),
            )
        assert foreign_error.value.status_code == 404


def _dependencies(route):
    return {dependency.call for dependency in route.dependant.dependencies}


def test_history_and_settings_routes_split_tenant_and_platform_dependencies():
    for route in history_api.router.routes:
        assert auth_context.get_tenant_db in _dependencies(route), route.name
        assert database.get_db not in _dependencies(route), route.name

    tenant_setting_routes = {
        "get_channel_initialization_rules",
        "get_channel_drama_types",
        "post_channel_drama_type",
        "put_channel_drama_type",
    }
    platform_read_routes = {
        "get_runtime_settings",
        "get_devices",
        "get_runtime_packages",
        "download_runtime_package",
        "get_app_icon",
    }
    settings_routes = {route.name: route for route in settings_api.router.routes}
    for name in tenant_setting_routes:
        assert auth_context.get_tenant_db in _dependencies(settings_routes[name]), name
        assert database.get_db not in _dependencies(settings_routes[name]), name
    for name in platform_read_routes:
        dependencies = _dependencies(settings_routes[name])
        assert {auth_context.get_current_principal, database.get_db}.issubset(dependencies), name
        assert auth_context.get_tenant_db not in dependencies, name
    for name, route in settings_routes.items():
        if name in tenant_setting_routes | platform_read_routes:
            continue
        dependencies = _dependencies(route)
        assert {require_platform_permission, database.get_db}.issubset(dependencies), name
        assert auth_context.get_tenant_db not in dependencies, name


def test_platform_catalogs_stay_global_and_skill_writes_require_platform_permission():
    for model in (Skill, RuntimePackageBuild, AppIconSetting, Device):
        assert "tenant_id" not in model.__table__.c

    read_names = {
        "get_skills",
        "get_skill",
        "get_skill_versions",
        "get_skill_version_detail",
    }
    for route in skill_api.router.routes:
        dependencies = _dependencies(route)
        assert database.get_db in dependencies, route.name
        assert auth_context.get_tenant_db not in dependencies, route.name
        if route.name in read_names:
            assert auth_context.get_current_principal in dependencies, route.name
        else:
            assert require_platform_permission in dependencies, route.name

    device_registration = next(
        route for route in identity_api.router.routes if route.name == "put_device"
    )
    assert require_platform_permission in _dependencies(device_registration)
    assert database.get_db in _dependencies(device_registration)
    assert auth_context.get_tenant_db not in _dependencies(device_registration)


def test_business_audit_requires_tenant_while_platform_audit_may_be_global(store):
    with tenant_session(store) as session:
        event = AuditEvent(
            actor_type="system",
            action="channel.updated",
            entity_type="channel",
            entity_id="channel-a",
            occurred_at=NOW,
        )
        session.add(event)
        session.commit()
        assert event.tenant_id == "tenant-a"

    with Session(store) as session:
        platform_event = AuditEvent(
            actor_type="system",
            action="skill.updated",
            entity_type="skill",
            entity_id="skill-a",
            occurred_at=NOW,
        )
        session.add(platform_event)
        session.commit()
        assert platform_event.tenant_id is None

    with Session(store) as session:
        session.add(
            AuditEvent(
                actor_type="system",
                action="channel.updated",
                entity_type="channel",
                entity_id="channel-b",
                occurred_at=NOW,
            )
        )
        with pytest.raises(ValueError, match="tenant_id"):
            session.commit()
