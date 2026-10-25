"""Local schedule matching. This module never mutates YouTube resources."""
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select

from zhiju.models import (Channel, ChannelScheduleEntry, Drama, DramaAlias, OperationTask,
                          SyncWatermark, YoutubeVideo, YoutubeVideoStatusHistory)
from zhiju.services.identity import ConflictError, _audit
from zhiju.tenant_repository import require_tenant_entity


LANGUAGES = {
    "阿拉伯语": "ar", "阿拉伯": "ar", "arabic": "ar", "ar": "ar",
    "英语": "en", "英文": "en", "english": "en", "en": "en",
    "法语": "fr", "french": "fr", "fr": "fr",
    "巴葡": "pt-BR", "巴葡语": "pt-BR", "巴西葡萄牙语": "pt-BR", "葡萄牙语": "pt", "pt-br": "pt-BR",
    "印尼": "id", "印尼语": "id", "印度尼西亚语": "id", "indonesian": "id", "id": "id",
    "西班牙语": "es", "西语": "es", "es": "es", "德语": "de", "de": "de",
    "日语": "ja", "ja": "ja", "韩语": "ko", "ko": "ko", "中文": "zh", "zh": "zh",
    "泰语": "th", "th": "th", "越南语": "vi", "vi": "vi", "土耳其语": "tr", "tr": "tr",
    "俄语": "ru", "ru": "ru", "意大利语": "it", "it": "it", "印地语": "hi", "hi": "hi",
}
LANGUAGE_LABELS = {"ar": "阿拉伯语", "en": "英语", "fr": "法语", "pt": "葡萄牙语", "pt-BR": "巴葡", "id": "印尼语"}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def title_key(value):
    return re.sub(r"[\s《》〈〉]", "", unicodedata.normalize("NFKC", value or "")).casefold()


def upload_identity(value):
    stem = re.sub(r"\.(mp4|mov|mkv|m4v|webm|avi)$", "", value or "", flags=re.I).strip()
    name, separator, language = stem.rpartition("_")
    return (title_key(name), LANGUAGES.get(language.strip().casefold())) if separator else (title_key(stem), None)


def _warning(code, message):
    errors = {"youtube_blocked", "blocked", "language_error", "identity_conflict", "wrong_language_scheduled",
              "video_error", "video_unavailable", "video_deleted", "bound_unavailable"}
    return {"code": code, "message": message, "severity": "error" if code in errors else "warning"}


def schedule_video_reviews(session, schedules, *, now=None):
    """Batch-load the consumer view, including unusable same-drama uploads."""
    if not schedules:
        return {}
    now = now or datetime.now(timezone.utc)
    channel_ids = {s.channel_id for s in schedules}
    channels = {c.id: c for c in session.scalars(select(Channel).where(Channel.id.in_(channel_ids)))}
    dramas = {d.id: d for d in session.scalars(select(Drama).where(Drama.id.in_({s.drama_id for s in schedules})))}
    names = {d.id: {title_key(d.chinese_title)} for d in dramas.values()}
    for alias in session.scalars(select(DramaAlias).where(DramaAlias.drama_id.in_(dramas))):
        names[alias.drama_id].add(title_key(alias.alias))
    videos = list(session.scalars(select(YoutubeVideo).where(YoutubeVideo.channel_id.in_(channel_ids))))
    watermarks = {w.channel_id: w for w in session.scalars(select(SyncWatermark).where(
        SyncWatermark.channel_id.in_(channel_ids), SyncWatermark.data_type == "videos"))}
    channel_schedules = list(session.scalars(select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id.in_(channel_ids))))
    public_history = set(session.scalars(select(YoutubeVideoStatusHistory.video_id).where(
        YoutubeVideoStatusHistory.video_id.in_([v.id for v in videos]),
        YoutubeVideoStatusHistory.new_privacy_status == "public")))
    result = {}
    for schedule in schedules:
        channel = channels[schedule.channel_id]
        watermark = watermarks.get(channel.id)
        complete = bool(watermark and watermark.status == "completed" and watermark.data_through_at)
        warnings, candidates = [], []
        if not complete:
            warnings.append(_warning("sync_incomplete", "尚未成功同步或最近同步未完成，不能判断本次未上传"))
        for video in videos:
            if video.channel_id != channel.id:
                continue
            file_title, file_language = upload_identity(video.original_file_name)
            video_title, video_language = upload_identity(video.title)
            bound = video.youtube_video_id == schedule.source_video_id
            if not bound and file_title not in names[schedule.drama_id] and video_title not in names[schedule.drama_id]:
                continue
            language = file_language or video_language
            expected = channel.default_language.casefold()
            mismatch = language and language.casefold().split("-")[0] != expected.split("-")[0]
            conflict = bool(file_language and video_language and file_language.casefold() != video_language.casefold())
            identity_conflict = bool((file_title and file_title not in names[schedule.drama_id]) or (video.drama_id and video.drama_id != schedule.drama_id))
            language_check = "mismatch" if mismatch else "conflict" if conflict else "unknown" if not file_language else "match"
            current = bool(complete and video.last_synced_at and utc(video.last_synced_at) >= utc(watermark.data_through_at))
            # Historical rows remain stored, but missing/deleted uploads must not
            # count as current duplicates or keep obsolete restriction warnings.
            deleted = video.deleted_at is not None or video.publish_status == "deleted" or video.upload_status == "deleted"
            if not bound and (deleted or (complete and not current)):
                continue
            occupied = [s.id for s in channel_schedules if s.id != schedule.id and s.source_video_id == video.youtube_video_id]
            if video.schedule_id and video.schedule_id != schedule.id and video.schedule_id not in occupied:
                occupied.append(video.schedule_id)
            was_public = video.id in public_history
            state = "public" if video.privacy_status == "public" else "scheduled" if video.scheduled_publish_at else video.privacy_status
            if video.publish_status in {"error", "deleted"} or video.upload_status in {"failed", "rejected", "deleted"}:
                state = "error"
            elif video.upload_status != "processed":
                state = "processing" if video.upload_status == "uploaded" else "unknown"
            if not current:
                state = "unavailable"
            elif deleted:
                state = "deleted"
            issues = []
            restriction = video.region_restriction or {}
            youtube_blocked = bool((current or not complete) and not deleted and (restriction.get("blocked") or "allowed" in restriction))
            if youtube_blocked:
                if "allowed" in restriction:
                    allowed = restriction["allowed"]
                    regions = "、".join(allowed) if len(allowed) <= 8 else f"{len(allowed)} 个国家或地区"
                    message = f"YouTube 已屏蔽：仅允许在 {regions} 播放，其他地区不可播放" if allowed else "YouTube 已屏蔽：所有国家和地区均不可播放"
                else:
                    blocked_regions = restriction["blocked"]
                    regions = "、".join(blocked_regions) if len(blocked_regions) <= 8 else f"{len(blocked_regions)} 个国家或地区"
                    message = f"YouTube 已屏蔽：{regions} 不可播放"
                issues.append(_warning("youtube_blocked", message))
            if language_check in {"mismatch", "conflict"}:
                message = f"语言错误：视频标注 {LANGUAGE_LABELS.get(language, language) or '未知'}，频道要求 {LANGUAGE_LABELS.get(channel.default_language, channel.default_language)}"
                if conflict:
                    message = f"语言标注冲突：文件名 {LANGUAGE_LABELS.get(file_language, file_language)}，视频标题 {LANGUAGE_LABELS.get(video_language, video_language)}，请人工核对"
                issues.append(_warning("language_error", message))
            elif language_check == "unknown":
                issues.append(_warning("language_unknown", "原始文件名语言无法确认，需人工核对；不是音轨验证"))
            if identity_conflict:
                issues.append(_warning("identity_conflict", "原始文件名与当前剧目不一致，请核对绑定"))
            if video.is_blocked:
                issues.append(_warning("blocked", "该视频已被标记禁播，不能选择"))
            if not video.uploaded_at:
                issues.append(_warning("upload_time_unknown", "上传记录时间未知，不能按最早上传自动选择"))
            if occupied:
                issues.append(_warning("occupied", "已绑定其他排期，不能重复自动分配"))
            if state in {"error", "processing", "unknown", "unavailable", "deleted"}:
                unavailable_message = "当前绑定视频已不在最新同步结果中，可能已删除或不可访问；请重新选择视频" if complete else "最近同步未完成，暂时无法确认该视频状态，保留原绑定"
                issues.append(_warning("video_" + state, {"error": "视频处理失败或被拒绝", "processing": "视频仍在处理", "unknown": "上传处理状态未知", "unavailable": unavailable_message, "deleted": "当前绑定视频已删除，请重新选择视频"}[state]))
            if was_public and video.privacy_status != "public":
                issues.append(_warning("previously_public", "该视频曾经公开，不能视为新上传"))
            if video.scheduled_publish_at and video.privacy_status != "public":
                if language_check in {"mismatch", "conflict"}:
                    issues.append(_warning("wrong_language_scheduled", "错误语言视频已设置定时，请立即检查 YouTube"))
                if utc(video.scheduled_publish_at).replace(second=0, microsecond=0) != utc(schedule.planned_utc_time).replace(second=0, microsecond=0):
                    minutes = int((utc(video.scheduled_publish_at).replace(second=0, microsecond=0) - utc(schedule.planned_utc_time).replace(second=0, microsecond=0)).total_seconds() / 60)
                    issues.append(_warning("schedule_mismatch", f"YouTube定时时间与本次排期不一致：{'晚' if minutes > 0 else '早'} {abs(minutes)} 分钟"))
                if utc(video.scheduled_publish_at) <= now:
                    issues.append(_warning("schedule_overdue", "预约时间已过，仍未公开，请立即检查"))
            if bound and video.privacy_status != "public" and utc(schedule.planned_utc_time) <= now:
                issues.append(_warning("publish_overdue", "排期时间已过，本次视频仍未公开，请检查"))
            selectable = bool(current and not occupied and not identity_conflict and language_check not in {"mismatch", "conflict"}
                              and video.privacy_status != "public" and not was_public and state in {"private", "unlisted", "scheduled"} and not video.is_blocked and not youtube_blocked)
            candidates.append({"video_id": video.youtube_video_id, "title": video.title,
                "file_name": video.original_file_name, "url": video.url,
                "thumbnail_url": f"https://i.ytimg.com/vi/{video.youtube_video_id}/default.jpg",
                "language": language, "language_check": language_check, "state": state,
                "youtube_blocked": youtube_blocked,
                "uploaded_at": video.uploaded_at, "scheduled_at": video.scheduled_publish_at,
                "published_at": video.published_at, "previously_public": was_public,
                "occupied_schedule_ids": occupied, "selected": bound,
                "selectable": selectable, "warnings": issues})
        candidates.sort(key=lambda v: (utc(v["uploaded_at"]) or datetime.max.replace(tzinfo=timezone.utc), v["video_id"]))
        public_count = sum(v["state"] == "public" or v["previously_public"] for v in candidates)
        eligible = [v for v in candidates if v["selectable"]]
        if public_count:
            warnings.append(_warning("public_history", f"该剧在本频道已有 {public_count} 个视频公开过"))
        if sum(s.drama_id == schedule.drama_id and not s.source_video_id and s.status not in {"cancelled", "replaced", "published"} for s in channel_schedules) > 1:
            warnings.append(_warning("multiple_schedules", "同一剧目有多条待绑定排期，请分别选择视频"))
        if len([v for v in candidates if v["state"] not in {"public", "unavailable"} and not v["previously_public"]]) > 1:
            warnings.append(_warning("multiple_candidates", "存在多个未公开视频，请核对本次使用的视频"))
        selected = next((v for v in candidates if v["selected"]), None)
        if schedule.source_video_id and not selected:
            warnings.append(_warning("bound_unavailable", "当前绑定ID未在本频道同步结果中找到，保留ID，请核对频道和视频"))
        if not schedule.source_video_id and complete and candidates and not eligible:
            warnings.append(_warning("no_eligible_video", "发现相关视频，但没有符合本次排期的可用新视频"))
        for video in candidates:
            warnings.extend(video["warnings"])
        warning_level = "error" if any(w["severity"] == "error" for w in warnings) else "warning" if warnings else None
        result[schedule.id] = {"videos": candidates, "warnings": warnings, "public_count": public_count,
            "warning_level": warning_level,
            "selected": selected, "sync_complete": complete,
            "last_synced_at": watermark.data_through_at if watermark else None,
            "channel_language": channel.default_language, "channel_timezone": channel.timezone,
            "planned_at": utc(schedule.planned_utc_time),
            "empty_label": "本次未上传" if complete and not eligible else "待选择视频" if eligible else "尚未确认上传状态"}
    return result


def _bind(session, schedule, video_id, *, manual):
    old_id = schedule.source_video_id
    if old_id and old_id != video_id:
        old = session.scalar(select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == old_id, YoutubeVideo.channel_id == schedule.channel_id))
        if old and old.schedule_id == schedule.id and old.operation_package_id is None:
            old.schedule_id = None
    video = session.scalar(select(YoutubeVideo).where(YoutubeVideo.youtube_video_id == video_id, YoutubeVideo.channel_id == schedule.channel_id))
    if video:
        video.schedule_id, video.drama_id = schedule.id, schedule.drama_id
    schedule.source_video_id = video_id
    schedule.source_video_url = f"https://www.youtube.com/watch?v={video_id}"
    schedule.source_video_overridden = manual
    for task in session.scalars(select(OperationTask).where(OperationTask.schedule_id == schedule.id)):
        task.source_video_id, task.source_video_url = schedule.source_video_id, schedule.source_video_url


def reconcile_channel_schedules(session, channel_id, *, now=None):
    require_tenant_entity(session, Channel, channel_id, lock=True)
    schedules = list(session.scalars(select(ChannelScheduleEntry).where(ChannelScheduleEntry.channel_id == channel_id).with_for_update()))
    reviews = schedule_video_reviews(session, schedules, now=now)
    assigned = {s.source_video_id for s in schedules if s.source_video_id}
    for schedule in schedules:
        review = reviews[schedule.id]
        if not review["sync_complete"]:
            continue
        if not schedule.source_video_id and not schedule.source_video_overridden and schedule.status not in {"cancelled", "replaced", "published"}:
            same_drama = [s for s in schedules if s.drama_id == schedule.drama_id and s.status not in {"cancelled", "replaced", "published"} and not s.source_video_id]
            options = [v for v in review["videos"] if v["selectable"] and v["language_check"] == "match" and v["video_id"] not in assigned]
            if len(same_drama) == 1 and options and (len(options) == 1 or all(v["uploaded_at"] for v in options)):
                _bind(session, schedule, options[0]["video_id"], manual=False)
                assigned.add(options[0]["video_id"])
                _audit(session, "schedule.youtube_auto_selected", "channel_schedule_entry", schedule.id)
        selected = next((v for v in review["videos"] if v["video_id"] == schedule.source_video_id), None)
        if selected and selected["state"] not in {"unavailable", "unknown"}:
            schedule.is_uploaded = selected["state"] not in {"error", "processing", "deleted"}
            schedule.is_published = selected["state"] == "public"
        elif selected and review["sync_complete"] and selected["state"] == "unavailable":
            schedule.is_uploaded = schedule.is_published = False
        elif not schedule.source_video_id:
            schedule.is_uploaded = schedule.is_published = False
    session.commit()


def select_schedule_video(session, schedule_id, video_id, *, confirm_unknown=False):
    schedule = require_tenant_entity(session, ChannelScheduleEntry, schedule_id)
    require_tenant_entity(session, Channel, schedule.channel_id)
    session.scalar(select(Channel).where(Channel.id == schedule.channel_id).with_for_update())
    if schedule.status in {"cancelled", "replaced", "published"}:
        raise ConflictError("已取消、替换或上线的排期不能分配新的未公开视频")
    review = schedule_video_reviews(session, [schedule])[schedule.id]
    candidate = next((v for v in review["videos"] if v["video_id"] == video_id), None)
    if not candidate or not candidate["selectable"]:
        raise ConflictError("视频语言、剧目、占用或同步状态不符合本次排期，不能绑定")
    if candidate["language_check"] == "unknown" and not confirm_unknown:
        raise ConflictError("文件名语言未知，请先人工确认语言")
    _bind(session, schedule, video_id, manual=True)
    schedule.is_uploaded = True
    schedule.is_published = False
    _audit(session, "schedule.youtube_selected", "channel_schedule_entry", schedule.id)
    session.commit()
    return schedule_video_reviews(session, [schedule])[schedule.id]
