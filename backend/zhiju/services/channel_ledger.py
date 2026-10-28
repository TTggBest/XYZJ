"""Read-only channel inventory and usage ledger; never allocates an upload."""
from collections import defaultdict
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models import (
    Channel, ChannelScheduleEntry, Drama, DramaAlias, DramaProductionState,
    SyncWatermark, YoutubeVideo,
)
from zhiju.services.schedule_youtube import title_key, upload_identity
from zhiju.tenant_repository import require_tenant_entity


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def list_channel_ledger(
    session: Session, channel_id: str, *, query: str | None = None, visibility: str | None = None,
    scheduled: bool | None = None, sort_by: str = "drama_code", sort_order: str = "asc",
    page: int = 1, page_size: int = 50,
) -> dict[str, object]:
    channel = require_tenant_entity(session, Channel, channel_id)
    watermark = session.scalar(select(SyncWatermark).where(
        SyncWatermark.channel_id == channel.id, SyncWatermark.data_type == "videos"))
    sync_complete = bool(watermark and watermark.status == "completed" and watermark.data_through_at)
    dramas = {d.id: d for d in session.scalars(select(Drama))}
    names = defaultdict(set)
    for drama in dramas.values():
        names[title_key(drama.chinese_title)].add(drama.id)
        names[title_key(drama.drama_code)].add(drama.id)
    for alias in session.scalars(select(DramaAlias)):
        names[title_key(alias.alias)].add(alias.drama_id)
    production = list(session.scalars(select(DramaProductionState)))
    completed_ids = {p.drama_id for p in production if p.production_completion_status == "completed"}
    inventory_warning = None
    # The existing locally synced completed dramas are the ledger baseline.
    # Reading this page must not require a new upstream sync or asset snapshot.
    ready = {drama_id for drama_id in completed_ids
             if drama_id in dramas and dramas[drama_id].status == "active"}
    videos = list(session.scalars(select(YoutubeVideo).where(YoutubeVideo.channel_id == channel.id)))
    schedules = list(session.scalars(select(ChannelScheduleEntry).where(
        ChannelScheduleEntry.channel_id == channel.id,
        ChannelScheduleEntry.status.not_in(("cancelled", "replaced")),
    ).order_by(ChannelScheduleEntry.planned_utc_time, ChannelScheduleEntry.id)))
    schedules_by_video = defaultdict(list)
    for schedule in schedules:
        if schedule.source_video_id:
            schedules_by_video[schedule.source_video_id].append(schedule)
    used_schedules, represented, rows = set(), set(), []

    def make_row(drama_id, video=None, schedule=None):
        drama = dramas.get(drama_id)
        failed = bool(video and (video.upload_status in {"failed", "rejected"} or video.publish_status == "error"))
        deleted = bool(video and (video.deleted_at or video.publish_status == "deleted" or video.upload_status == "deleted"))
        unavailable = bool(video and watermark and watermark.data_through_at and (
            not video.last_synced_at or _utc(video.last_synced_at) < _utc(watermark.data_through_at)))
        is_public = bool(video and not failed and not deleted and not unavailable and video.privacy_status == "public")
        state = "not_uploaded"
        if video:
            state = "deleted" if deleted else "unavailable" if unavailable else "failed" if failed else "public" if is_public else (
                "scheduled" if video.scheduled_publish_at else video.privacy_status)
        reason = None
        if failed:
            reason = {"failed": "上传或处理失败", "rejected": "YouTube 已拒绝该视频"}.get(video.upload_status, "视频处理异常")
        row_id = "video:" + video.id if video else "schedule:" + schedule.id if schedule else "inventory:" + drama_id
        return {
            "row_id": row_id, "group_id": drama.id if drama else row_id,
            "drama_id": drama.id if drama else None,
            "drama_title": drama.chinese_title if drama else video.title,
            "drama_code": drama.drama_code if drama else None,
            "youtube_video_id": video.youtube_video_id if video else schedule.source_video_id if schedule else None,
            "visibility": state, "scheduled_publish_at": _utc(video.scheduled_publish_at) if video else None,
            "uploaded_at": _utc(video.uploaded_at) if video else None,
            "schedule_id": schedule.id if schedule else None,
            "planned_at": _utc(schedule.planned_utc_time) if schedule else None,
            "has_schedule": schedule is not None, "is_public": is_public,
            "failed": failed, "failure_message": reason,
            "upload_status": video.upload_status if video else None,
            "needs_matching": drama is None,
        }

    for video in videos:
        # Explicit links win. Otherwise use exact library title/alias from the
        # original filename, then the upload title; never fuzzy-match a title.
        linked = schedules_by_video.get(video.youtube_video_id, [])
        explicit = [s for s in schedules if s.id == video.schedule_id]
        drama_id = video.drama_id
        if not drama_id:
            linked_ids = {s.drama_id for s in linked + explicit}
            if len(linked_ids) == 1:
                drama_id = next(iter(linked_ids))
        if not drama_id:
            for identity in (video.original_file_name, video.title):
                candidates = names.get(upload_identity(identity)[0], set())
                if len(candidates) == 1:
                    drama_id = next(iter(candidates))
                    break
                if candidates:
                    break
        matching = [s for s in explicit + linked if s.drama_id == drama_id and s.id not in used_schedules]
        schedule = matching[0] if matching else None
        if schedule:
            used_schedules.add(schedule.id)
        if drama_id in dramas:
            represented.add(drama_id)
        rows.append(make_row(drama_id, video, schedule))
    # A unique, current private upload and one unassigned schedule are the same
    # ledger use. Project them together without writing a schedule assignment.
    video_rows = defaultdict(list)
    remaining_schedules = defaultdict(list)
    videos_by_id = {"video:" + v.id: v for v in videos}
    for row in rows:
        if row["drama_id"]:
            video_rows[row["drama_id"]].append(row)
    for schedule in schedules:
        if schedule.id not in used_schedules:
            remaining_schedules[schedule.drama_id].append(schedule)
    for drama_id, pending in remaining_schedules.items():
        uploaded = video_rows.get(drama_id, [])
        if not sync_complete or len(uploaded) != 1 or len(pending) != 1:
            continue
        row, schedule = uploaded[0], pending[0]
        video = videos_by_id[row["row_id"]]
        language = upload_identity(video.original_file_name)[1]
        if (row["schedule_id"] or row["visibility"] != "private" or video.upload_status != "processed"
                or video.is_blocked or schedule.source_video_id or schedule.source_video_overridden
                or not language or language.casefold() != (channel.default_language or "").casefold()
                or not video.uploaded_at or _utc(video.uploaded_at) > _utc(schedule.planned_utc_time)):
            continue
        row.update(schedule_id=schedule.id, planned_at=_utc(schedule.planned_utc_time), has_schedule=True)
        used_schedules.add(schedule.id)
    for schedule in schedules:
        if schedule.id not in used_schedules:
            represented.add(schedule.drama_id)
            row = make_row(schedule.drama_id, schedule=schedule)
            if video_rows.get(schedule.drama_id) or schedule.source_video_id:
                row["visibility"] = "pending_match"
            rows.append(row)
    for drama_id in ready - represented:
        rows.append(make_row(drama_id))

    if query:
        needle = query.strip().casefold()
        rows = [r for r in rows if any(needle in str(r[k] or "").casefold()
                                      for k in ("drama_title", "drama_code", "youtube_video_id"))]
    if visibility:
        rows = [r for r in rows if r["visibility"] == visibility]
    if scheduled is not None:
        rows = [r for r in rows if r["has_schedule"] == scheduled]

    groups = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    reverse = sort_order == "desc"
    def sort_value(row):
        value = row[sort_by]
        if sort_by == "visibility" and value == "scheduled":
            return "scheduled:" + row["scheduled_publish_at"].isoformat()
        return value.isoformat() if hasattr(value, "isoformat") else str(value or "").casefold()

    # Sort whole groups and then their rows. Pagination is also by group, so
    # repeated uploads never split across pages or interleave with other dramas.
    for group in groups.values():
        group.sort(key=lambda r: (r["uploaded_at"] is None, r["uploaded_at"] or _utc(datetime.max), r["row_id"]))
        group.sort(key=sort_value, reverse=reverse)
        group.sort(key=lambda r: not bool(sort_value(r)))
    def group_value(group):
        values = [sort_value(r) for r in group if sort_value(r)]
        return (max(values) if reverse else min(values)) if values else ""
    ordered = sorted(groups.values(), key=lambda g: (g[0]["drama_title"], g[0]["group_id"]))
    ordered.sort(key=group_value, reverse=reverse)
    ordered.sort(key=lambda g: not bool(group_value(g)))
    return {
        "channel_id": channel.id, "channel_name": channel.operational_name or channel.original_name,
        "language": channel.default_language,
        "items": [row for group in ordered[(page - 1) * page_size:page * page_size] for row in group],
        "total": len(rows), "drama_count": len(groups), "page": page,
        "pages": ceil(len(groups) / page_size), "page_size": page_size,
        "last_synced_at": _utc(watermark.data_through_at) if watermark else None,
        "sync_status": watermark.status if watermark else None,
        "sync_complete": sync_complete,
        "inventory_basis": f"以现有已同步、制作完成的 {len(ready)} 部剧为底表，匹配本频道上传及排期；未上传表示本频道暂无上传记录",
        "completed_drama_count": len(completed_ids), "inventory_warning": inventory_warning,
    }
