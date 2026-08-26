from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import (
    AuditEvent,
    ChannelScheduleEntry,
    OperationTask,
    ScheduleChangeHistory,
    SystemEvent,
    TaskEvent,
    YoutubeVideo,
    YoutubeVideoStatusHistory,
)
from zhiju.services.channel import NotFoundError


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
    if session.get(OperationTask, task_id) is None:
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
    if session.get(ChannelScheduleEntry, schedule_id) is None:
        raise NotFoundError("排期不存在")
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
    if session.get(YoutubeVideo, video_id) is None:
        raise NotFoundError("YouTube视频不存在")
    return list(
        session.scalars(
            select(YoutubeVideoStatusHistory)
            .where(YoutubeVideoStatusHistory.video_id == video_id)
            .order_by(YoutubeVideoStatusHistory.changed_at.desc(), YoutubeVideoStatusHistory.id.desc())
        )
    )

