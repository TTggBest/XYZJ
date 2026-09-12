from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.database import TenantSession
from zhiju.models import (
    AccountChannelAuthorization,
    AuditEvent,
    Channel,
    ChannelAnalysisReport,
    ChannelCommunitySlot,
    ChannelDnaVersion,
    ChannelKeyword,
    ChannelPinnedCommentTemplate,
    ChannelPlaylist,
    ChannelProfile,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    DemoDataBatch,
    Drama,
    DramaTranslation,
    GoogleAccount,
    IntegrationAccount,
    IntegrationCredential,
    MediaAsset,
    OAuthGrant,
    OperationPackage,
    OperationTask,
    ProductionNodeRun,
    ScheduleCandidate,
    ScheduleChangeHistory,
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
from zhiju.services.channel import NotFoundError
from zhiju.tenant_repository import require_tenant_entity


TIMELINE_ENTITY_MODELS = {
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


def _require_tenant_context(session: Session) -> str:
    tenant_id = session.info.get("tenant_id")
    if not isinstance(session, TenantSession) or not tenant_id:
        raise HTTPException(status_code=403, detail="请选择当前主账号")
    return str(tenant_id)


def list_system_events(
    session: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    new_status: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SystemEvent]:
    _require_tenant_context(session)
    statement = select(SystemEvent)
    if entity_type:
        statement = statement.where(SystemEvent.entity_type == entity_type)
    if entity_id:
        statement = statement.where(SystemEvent.entity_id == entity_id)
    if new_status:
        statement = statement.where(SystemEvent.new_status == new_status)
    if occurred_from:
        statement = statement.where(SystemEvent.occurred_at >= occurred_from)
    if occurred_to:
        statement = statement.where(SystemEvent.occurred_at <= occurred_to)
    return list(
        session.scalars(
            statement.order_by(SystemEvent.occurred_at.desc(), SystemEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )


def list_audit_events(
    session: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEvent]:
    _require_tenant_context(session)
    statement = select(AuditEvent)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        statement = statement.where(AuditEvent.entity_id == entity_id)
    if action:
        statement = statement.where(AuditEvent.action == action)
    if actor_type:
        statement = statement.where(AuditEvent.actor_type == actor_type)
    if occurred_from:
        statement = statement.where(AuditEvent.occurred_at >= occurred_from)
    if occurred_to:
        statement = statement.where(AuditEvent.occurred_at <= occurred_to)
    return list(
        session.scalars(
            statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )


def get_entity_timeline(
    session: Session, entity_type: str, entity_id: str, *, limit: int = 200
) -> list[dict[str, object]]:
    _require_tenant_context(session)
    model = TIMELINE_ENTITY_MODELS.get(entity_type)
    if model is None:
        raise HTTPException(status_code=404, detail="数据不存在")
    require_tenant_entity(session, model, entity_id)
    statuses = list_system_events(
        session, entity_type=entity_type, entity_id=entity_id, limit=limit
    )
    audits = list_audit_events(
        session, entity_type=entity_type, entity_id=entity_id, limit=limit
    )
    timeline = [
        {
            "event_kind": "status",
            "id": item.id,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "old_status": item.old_status,
            "new_status": item.new_status,
            "reason": item.reason,
            "actor_type": item.actor_type,
            "actor_id": item.actor_id,
            "occurred_at": item.occurred_at,
        }
        for item in statuses
    ]
    timeline.extend(
        {
            "event_kind": "audit",
            "id": item.id,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "action": item.action,
            "actor_type": item.actor_type,
            "actor_id": item.actor_id,
            "change_summary": item.change_summary,
            "occurred_at": item.occurred_at,
        }
        for item in audits
    )
    timeline.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
    return timeline[:limit]


def list_task_events(session: Session, task_id: str) -> list[TaskEvent]:
    _require_tenant_context(session)
    try:
        require_tenant_entity(session, OperationTask, task_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise NotFoundError("任务不存在")
    return list(
        session.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.occurred_at.desc(), TaskEvent.id.desc())
        )
    )


def list_schedule_history(
    session: Session, schedule_id: str
) -> list[ScheduleChangeHistory]:
    _require_tenant_context(session)
    require_tenant_entity(session, ChannelScheduleEntry, schedule_id)
    return list(
        session.scalars(
            select(ScheduleChangeHistory)
            .where(ScheduleChangeHistory.schedule_id == schedule_id)
            .order_by(ScheduleChangeHistory.changed_at.desc(), ScheduleChangeHistory.id.desc())
        )
    )


def list_video_status_history(
    session: Session, video_id: str
) -> list[YoutubeVideoStatusHistory]:
    _require_tenant_context(session)
    require_tenant_entity(session, YoutubeVideo, video_id)
    return list(
        session.scalars(
            select(YoutubeVideoStatusHistory)
            .where(YoutubeVideoStatusHistory.video_id == video_id)
            .order_by(YoutubeVideoStatusHistory.changed_at.desc(), YoutubeVideoStatusHistory.id.desc())
        )
    )
