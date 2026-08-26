from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.history import (
    AuditEventRead,
    EntityTimelineItem,
    ScheduleHistoryRead,
    SystemEventRead,
    TaskEventRead,
    VideoStatusHistoryRead,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.history import (
    get_entity_timeline,
    list_audit_events,
    list_schedule_history,
    list_system_events,
    list_task_events,
    list_video_status_history,
)


router = APIRouter(prefix="/v3", tags=["history"])


@router.get("/system-events", response_model=list[SystemEventRead])
def get_system_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    new_status: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[SystemEventRead]:
    return list_system_events(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        new_status=new_status,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )


@router.get("/audit-events", response_model=list[AuditEventRead])
def get_audit_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[AuditEventRead]:
    return list_audit_events(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_type=actor_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/entities/{entity_type}/{entity_id}/timeline",
    response_model=list[EntityTimelineItem],
)
def get_timeline(
    entity_type: str,
    entity_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_db),
) -> list[EntityTimelineItem]:
    return get_entity_timeline(session, entity_type, entity_id, limit=limit)


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventRead])
def get_task_events(
    task_id: str, session: Session = Depends(get_db)
) -> list[TaskEventRead]:
    try:
        return list_task_events(session, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/schedules/{schedule_id}/history",
    response_model=list[ScheduleHistoryRead],
)
def get_schedule_history(
    schedule_id: str, session: Session = Depends(get_db)
) -> list[ScheduleHistoryRead]:
    try:
        return list_schedule_history(session, schedule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/youtube/videos/{video_id}/status-history",
    response_model=list[VideoStatusHistoryRead],
)
def get_video_history(
    video_id: str, session: Session = Depends(get_db)
) -> list[VideoStatusHistoryRead]:
    try:
        return list_video_status_history(session, video_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

