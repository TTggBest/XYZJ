from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SystemEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_type: str
    entity_id: str
    old_status: str | None
    new_status: str
    reason: str
    actor_type: str
    actor_id: str | None
    occurred_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str
    request_id: str | None
    idempotency_key: str | None
    change_summary: str | None
    occurred_at: datetime


class EntityTimelineItem(BaseModel):
    event_kind: Literal["status", "audit"]
    id: str
    entity_type: str
    entity_id: str
    action: str | None = None
    old_status: str | None = None
    new_status: str | None = None
    reason: str | None = None
    actor_type: str
    actor_id: str | None = None
    change_summary: str | None = None
    occurred_at: datetime


class TaskEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    old_status: str | None
    new_status: str
    reason: str
    actor_type: str
    actor_id: str | None
    occurred_at: datetime


class ScheduleHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schedule_id: str
    old_drama_id: str | None
    new_drama_id: str | None
    old_planned_utc_time: datetime | None
    new_planned_utc_time: datetime | None
    old_status: str | None
    new_status: str
    reason: str
    actor_type: str
    actor_id: str | None
    changed_at: datetime


class VideoStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    old_publish_status: str | None
    new_publish_status: str
    old_privacy_status: str | None
    new_privacy_status: str
    reason: str
    source: str
    changed_at: datetime

