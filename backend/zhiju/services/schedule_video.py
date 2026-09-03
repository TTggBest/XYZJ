from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import ChannelScheduleEntry, OperationTask
from zhiju.schemas.operations import SourceVideoUpdate
from zhiju.services.channel import NotFoundError
from zhiju.services.feishu_sync import normalized_video_id, video_id_from_url
from zhiju.services.identity import _audit


def _normalized_values(payload: SourceVideoUpdate) -> tuple[str | None, str | None]:
    video_url = payload.source_video_url
    explicit_video_id = payload.source_video_id or ""
    video_id = (
        video_id_from_url(video_url or "")
        or video_id_from_url(explicit_video_id)
        or normalized_video_id(video_url or "", explicit_video_id)
        or None
    )
    return video_id, video_url


def _apply_video_values(
    schedule: ChannelScheduleEntry,
    task: OperationTask | None,
    payload: SourceVideoUpdate,
) -> None:
    video_id, video_url = _normalized_values(payload)
    schedule.source_video_id = video_id
    schedule.source_video_url = video_url
    schedule.source_video_overridden = True
    if task is not None:
        task.source_video_id = video_id
        task.source_video_url = video_url


def update_schedule_source_video(
    session: Session,
    schedule_id: str,
    payload: SourceVideoUpdate,
) -> ChannelScheduleEntry:
    schedule = session.scalar(
        select(ChannelScheduleEntry)
        .where(ChannelScheduleEntry.id == schedule_id)
        .with_for_update()
    )
    if schedule is None:
        raise NotFoundError("排期不存在")
    task = session.scalar(
        select(OperationTask)
        .where(OperationTask.schedule_id == schedule.id)
        .with_for_update()
    )
    _apply_video_values(schedule, task, payload)
    _audit(session, "schedule.source_video_updated", "channel_schedule_entry", schedule.id)
    session.commit()
    session.refresh(schedule)
    return schedule


def update_task_source_video(
    session: Session,
    task_id: str,
    payload: SourceVideoUpdate,
) -> OperationTask:
    task = session.scalar(
        select(OperationTask).where(OperationTask.id == task_id).with_for_update()
    )
    if task is None:
        raise NotFoundError("任务不存在")
    if task.schedule_id is None:
        video_id, video_url = _normalized_values(payload)
        task.source_video_id = video_id
        task.source_video_url = video_url
    else:
        schedule = session.scalar(
            select(ChannelScheduleEntry)
            .where(ChannelScheduleEntry.id == task.schedule_id)
            .with_for_update()
        )
        if schedule is None:
            raise NotFoundError("任务关联的排期不存在")
        _apply_video_values(schedule, task, payload)
    _audit(session, "task.source_video_updated", "operation_task", task.id)
    session.commit()
    session.refresh(task)
    return task
