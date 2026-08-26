import re
from collections import Counter
from datetime import date, datetime, time, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from zhiju.models import (
    AuditEvent,
    Channel,
    ChannelPlaylist,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    DemoDataBatch,
    DemoDataEntity,
    Drama,
    DramaCoreTerm,
    OperationPackage,
    OperationTask,
    PackageCommunityPost,
    PackageCoverVariant,
    PackageDescription,
    PackagePlaylistAssignment,
    PackageTitle,
    ProductionNodeRun,
    SystemEvent,
    WorkOrder,
    YoutubeVideo,
    YoutubeVideoPlaylistMembership,
)
from zhiju.schemas.demo import DemoDataImportRequest
from zhiju.services.identity import ConflictError
from zhiju.services.operations import normalize_drama_title


BATCH_CODE = "feishu-first20-20260824"
SOURCE_LABEL = "飞书《频道相关》工单表与任务表前20条"
NODE_SEQUENCE = ("search", "title", "cover", "description", "community", "merge")
LANGUAGE_HINTS = {
    "英语": "en", "阿拉伯": "ar", "孟加拉": "bn", "印尼": "id", "西班牙": "es",
    "巴葡": "pt-BR", "葡萄牙": "pt-BR", "印地": "hi", "俄语": "ru", "菲律宾": "fil", "土耳其": "tr",
}


def _text(row: dict[str, str | None], key: str) -> str:
    return str(row.get(key) or "").strip()


def _video_id(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _parse_date(value: str) -> date:
    normalized = value.replace("-", "").strip()
    return datetime.strptime(normalized[:8], "%Y%m%d").date()


def _parse_slot(value: str) -> tuple[date, time]:
    normalized = value.strip()
    if not re.fullmatch(r"\d{10}", normalized):
        raise ConflictError(f"档期格式不正确：{value}")
    return datetime.strptime(normalized[:8], "%Y%m%d").date(), time(int(normalized[8:10]), 0)


def _language(nickname: str) -> str:
    for hint, code in LANGUAGE_HINTS.items():
        if hint in nickname:
            return code
    return "und"


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _split_cover_blocks(value: str) -> list[str]:
    blocks = re.split(r"(?=标题[123][：:])", value.strip())
    return [block.strip() for block in blocks if re.match(r"标题[123][：:]", block.strip())]


def _cover_prompt(block: str) -> str:
    lines = block.splitlines()
    return "\n".join(lines[2:]).strip() if len(lines) > 2 else block


def _core_phrase(block: str) -> str | None:
    match = re.search(r"核心词[：:]\s*(.+)", block)
    return match.group(1).strip() if match else None


def _playlist_url(description: str) -> str | None:
    match = re.search(r"https://www\.youtube\.com/playlist\?list=[^\s]+", description)
    return match.group(0).rstrip(".,，。") if match else None


def _track(session: Session, batch: DemoDataBatch, entity_type: str, entity_id: str) -> None:
    session.add(DemoDataEntity(batch_id=batch.id, entity_type=entity_type, entity_id=entity_id, owned=True))


def _entity_counts(session: Session, batch_id: str) -> dict[str, int]:
    rows = session.execute(
        select(DemoDataEntity.entity_type, func.count(DemoDataEntity.id))
        .where(DemoDataEntity.batch_id == batch_id, DemoDataEntity.owned.is_(True))
        .group_by(DemoDataEntity.entity_type)
    )
    return {entity_type: count for entity_type, count in rows}


def demo_status(session: Session) -> dict[str, object]:
    batch = session.scalar(
        select(DemoDataBatch).where(DemoDataBatch.batch_code == BATCH_CODE).order_by(DemoDataBatch.created_at.desc())
    )
    return {
        "active": bool(batch and batch.status == "active"),
        "batch": batch,
        "entity_counts": _entity_counts(session, batch.id) if batch and batch.status == "active" else {},
    }


def import_feishu_demo(session: Session, payload: DemoDataImportRequest) -> dict[str, object]:
    existing = session.scalar(select(DemoDataBatch).where(DemoDataBatch.batch_code == BATCH_CODE).with_for_update())
    if existing and existing.status == "active":
        return {"active": True, "batch": existing, "entity_counts": _entity_counts(session, existing.id)}

    task_by_key = {(_text(row, "剧id"), _text(row, "档期")): row for row in payload.task_rows}
    pairs: list[tuple[dict[str, str | None], dict[str, str | None]]] = []
    for work_row in payload.work_rows:
        key = (_video_id(_text(work_row, "地址")), _text(work_row, "档期"))
        task_row = task_by_key.get(key)
        if task_row is None:
            raise ConflictError(f"工单行没有对应任务结果：{_text(work_row, '剧名')} / {key[0]} / {key[1]}")
        pairs.append((work_row, task_row))
    if len(pairs) != len(payload.task_rows):
        raise ConflictError("工单表与任务表样本不能一一对应")

    dates = [_parse_date(_text(task, "日期")) for _, task in pairs]
    if existing:
        session.execute(delete(DemoDataEntity).where(DemoDataEntity.batch_id == existing.id))
        batch = existing
        batch.row_count = len(pairs)
        batch.start_date = min(dates)
        batch.end_date = max(dates)
        batch.status = "active"
        batch.deleted_at = None
    else:
        batch = DemoDataBatch(
            batch_code=BATCH_CODE,
            source_label=SOURCE_LABEL,
            row_count=len(pairs),
            start_date=min(dates),
            end_date=max(dates),
            status="active",
        )
        session.add(batch)
    session.flush()

    channel_cache: dict[str, Channel] = {}
    drama_cache: dict[str, Drama] = {}
    slot_cache: dict[tuple[str, time], ChannelPublishSlot] = {}
    playlist_cache: dict[tuple[str, str], ChannelPlaylist] = {}
    channel_daily_counts = Counter((_text(task, "频道"), _text(task, "日期")) for _, task in pairs)
    ordered_channels: list[str] = []
    for _, task in pairs:
        name = _text(task, "频道")
        if name not in ordered_channels:
            ordered_channels.append(name)

    try:
        for channel_number, channel_name in enumerate(ordered_channels, start=1):
            sample = next(task for _, task in pairs if _text(task, "频道") == channel_name)
            channel = session.scalar(select(Channel).where(Channel.original_name == channel_name, Channel.deleted_at.is_(None)))
            if channel is None:
                nickname = _text(sample, "频道昵称")
                channel = Channel(
                    youtube_channel_id=f"DEMO-CHANNEL-20260824-{channel_number:03d}",
                    original_name=channel_name,
                    operational_name=nickname or channel_name,
                    default_language=_language(nickname),
                    default_genre="短剧演示",
                    timezone="Asia/Shanghai",
                    daily_publish_count=max(count for (name, _), count in channel_daily_counts.items() if name == channel_name),
                    status="active",
                )
                session.add(channel); session.flush(); _track(session, batch, "channel", channel.id)
            channel_cache[channel_name] = channel

        for work_row, task_row in pairs:
            channel = channel_cache[_text(task_row, "频道")]
            drama_title = _text(work_row, "剧名")
            normalized_title = normalize_drama_title(drama_title)
            drama = drama_cache.get(normalized_title) or session.scalar(select(Drama).where(Drama.normalized_title == normalized_title))
            if drama is None:
                drama = Drama(
                    drama_code=f"DEMO-DRM-20260824-{len(drama_cache) + 1:03d}",
                    chinese_title=drama_title,
                    normalized_title=normalized_title,
                    baidu_cloud_url=_text(work_row, "地址"),
                    content_summary=_text(task_row, "说明翻译") or "飞书演示剧目，待补充剧情资料。",
                    status="active",
                )
                session.add(drama); session.flush(); _track(session, batch, "drama", drama.id)
                for phrase in dict.fromkeys(filter(None, (_core_phrase(block) for block in _split_cover_blocks(_text(task_row, "封面4：5"))))):
                    session.add(DramaCoreTerm(drama_id=drama.id, term_type="keyword", term=phrase[:255], weight=0.8, source="feishu_demo"))
            drama_cache[normalized_title] = drama

            publish_date, slot_time = _parse_slot(_text(work_row, "档期"))
            slot_key = (channel.id, slot_time)
            slot = slot_cache.get(slot_key) or session.scalar(
                select(ChannelPublishSlot).where(ChannelPublishSlot.channel_id == channel.id, ChannelPublishSlot.local_time == slot_time)
            )
            if slot is None:
                channel_slots = [key for key in slot_cache if key[0] == channel.id]
                slot = ChannelPublishSlot(
                    channel_id=channel.id,
                    slot_type="main" if not channel_slots else "aux",
                    slot_number=1 if not channel_slots else len(channel_slots),
                    local_time=slot_time,
                    timezone="Asia/Shanghai",
                    status="active",
                )
                session.add(slot); session.flush(); _track(session, batch, "publish_slot", slot.id)
            slot_cache[slot_key] = slot

            playlist_name = _text(task_row, "播放列表") or "演示播放列表"
            playlist_key = (channel.id, playlist_name)
            playlist = playlist_cache.get(playlist_key) or session.scalar(
                select(ChannelPlaylist).where(ChannelPlaylist.channel_id == channel.id, ChannelPlaylist.local_name == playlist_name)
            )
            if playlist is None:
                playlist = ChannelPlaylist(
                    channel_id=channel.id,
                    local_name=playlist_name,
                    chinese_name=playlist_name,
                    url=_playlist_url(_text(task_row, "说明")),
                    sort_order=len([key for key in playlist_cache if key[0] == channel.id]),
                    status="active",
                )
                session.add(playlist); session.flush(); _track(session, batch, "playlist", playlist.id)
            playlist_cache[playlist_key] = playlist

            planned_local = datetime.combine(publish_date, slot_time, tzinfo=ZoneInfo("Asia/Shanghai"))
            planned_utc = planned_local.astimezone(timezone.utc)
            schedule = ChannelScheduleEntry(
                channel_id=channel.id,
                drama_id=drama.id,
                playlist_id=playlist.id,
                publish_slot_id=slot.id,
                publish_date=publish_date,
                planned_local_time=planned_local,
                planned_beijing_time=planned_local,
                planned_utc_time=planned_utc,
                community_count=int(_text(work_row, "是否需要社区") or 0),
                status="confirmed",
                priority=100,
                idempotency_key=f"demo:schedule:{_text(task_row, '剧id')}:{_text(task_row, '档期')}",
            )
            session.add(schedule); session.flush(); _track(session, batch, "schedule", schedule.id)

            completed_at = datetime.now(timezone.utc)
            task = OperationTask(
                schedule_id=schedule.id, channel_id=channel.id, drama_id=drama.id,
                publish_slot_id=slot.id, playlist_id=playlist.id,
                task_date=_parse_date(_text(task_row, "日期")), target_publish_date=publish_date,
                community_count=schedule.community_count, source="import", status="completed",
                idempotency_key=f"demo:task:{_text(task_row, '剧id')}:{_text(task_row, '档期')}",
                dispatched_at=completed_at, completed_at=completed_at,
            )
            session.add(task); session.flush(); _track(session, batch, "task", task.id)
            work_order = WorkOrder(
                task_id=task.id, schedule_id=schedule.id, channel_id=channel.id, drama_id=drama.id,
                publish_slot_id=slot.id, playlist_id=playlist.id,
                production_date=task.task_date, target_publish_date=publish_date,
                community_count=task.community_count, status="completed", attempt_count=1,
                started_at=completed_at, completed_at=completed_at,
            )
            session.add(work_order); session.flush(); _track(session, batch, "work_order", work_order.id)
            package = OperationPackage(
                work_order_id=work_order.id, schedule_id=schedule.id, channel_id=channel.id, drama_id=drama.id,
                version_number=1, status="review_pending", ready_at=completed_at,
                review_note="飞书前20条演示数据",
            )
            session.add(package); session.flush(); _track(session, batch, "package", package.id)
            session.add_all([
                ProductionNodeRun(
                    work_order_id=work_order.id, package_id=package.id, node_type=node_type,
                    sequence_number=sequence, attempt_number=1, status="completed",
                    idempotency_key=f"{work_order.id}:{node_type}:1", worker_key="feishu-demo-import",
                    started_at=completed_at, completed_at=completed_at,
                )
                for sequence, node_type in enumerate(NODE_SEQUENCE, start=1)
            ])

            title_lines = _split_lines(_text(task_row, "标题"))[:3]
            translation_lines = _split_lines(_text(task_row, "标题翻译"))[:3]
            cover45 = _split_cover_blocks(_text(task_row, "封面4：5"))
            cover169 = _split_cover_blocks(_text(task_row, "封面16：9"))
            if len(title_lines) != 3 or len(translation_lines) != 3 or len(cover45) != 3 or len(cover169) != 3:
                raise ConflictError(f"标题或封面不是完整三组：{drama_title}")
            title_models: list[PackageTitle] = []
            for index in range(3):
                title_model = PackageTitle(
                    package_id=package.id, variant_number=index + 1, generation_number=1,
                    localized_title=title_lines[index][:500], chinese_translation=translation_lines[index][:1000],
                    core_phrase=_core_phrase(cover45[index]), selected=True, status="selected",
                )
                session.add(title_model); session.flush(); title_models.append(title_model)
                session.add_all([
                    PackageCoverVariant(
                        package_id=package.id, title_id=title_model.id, aspect_ratio=ratio,
                        generation_number=1, creative_prompt=_cover_prompt(block), selected=True, status="selected",
                    )
                    for ratio, block in (("4:5", cover45[index]), ("16:9", cover169[index]))
                ])
            session.add(PackageDescription(
                package_id=package.id, version_number=1, language=channel.default_language or "und",
                localized_text=_text(task_row, "说明"), chinese_translation=_text(task_row, "说明翻译"),
                selected=True, status="selected",
            ))
            session.add(PackagePlaylistAssignment(
                package_id=package.id, playlist_id=playlist.id, rank_number=1,
                rationale="飞书任务表选定播放列表", status="selected",
            ))
            for sequence in range(1, task.community_count + 1):
                session.add(PackageCommunityPost(
                    package_id=package.id, sequence_number=sequence, version_number=1,
                    language=channel.default_language or "und",
                    localized_text=_text(task_row, f"社群文案{sequence}"),
                    image_prompt=_text(task_row, f"社群图描述{sequence}"),
                    selected=True, status="selected",
                ))
            video = YoutubeVideo(
                youtube_video_id=_text(task_row, "剧id"), channel_id=channel.id,
                operation_package_id=package.id, drama_id=drama.id, schedule_id=schedule.id,
                title=title_lines[0][:500], description=_text(task_row, "说明"), url=_text(task_row, "剧目地址"),
                privacy_status="public", publish_status="published", published_at=planned_utc,
                source="manual", last_synced_at=completed_at,
            )
            session.add(video); session.flush(); _track(session, batch, "youtube_video", video.id)
            session.add(YoutubeVideoPlaylistMembership(
                video_id=video.id, playlist_id=playlist.id, status="active", source="manual", last_synced_at=completed_at,
            ))
            session.add_all([
                SystemEvent(entity_type="work_order", entity_id=work_order.id, old_status=None, new_status="completed", reason="导入飞书演示结果", actor_type="system", occurred_at=completed_at),
                SystemEvent(entity_type="operation_package", entity_id=package.id, old_status=None, new_status="review_pending", reason="导入飞书演示结果", actor_type="system", occurred_at=completed_at),
            ])

        session.add(AuditEvent(
            actor_type="system", action="demo_data.imported", entity_type="demo_data_batch", entity_id=batch.id,
            change_summary=f"导入飞书前 {len(pairs)} 条演示数据", occurred_at=datetime.now(timezone.utc),
        ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(batch)
    return {"active": True, "batch": batch, "entity_counts": _entity_counts(session, batch.id)}


def delete_feishu_demo(session: Session) -> dict[str, object]:
    batch = session.scalar(select(DemoDataBatch).where(DemoDataBatch.batch_code == BATCH_CODE).with_for_update())
    if batch is None or batch.status != "active":
        return {"active": False, "batch": batch, "entity_counts": {}}
    entities = list(session.scalars(select(DemoDataEntity).where(DemoDataEntity.batch_id == batch.id, DemoDataEntity.owned.is_(True))))
    ids_by_type: dict[str, list[str]] = {}
    for entity in entities:
        ids_by_type.setdefault(entity.entity_type, []).append(entity.entity_id)
    all_ids = [entity.entity_id for entity in entities]
    if all_ids:
        session.execute(delete(SystemEvent).where(SystemEvent.entity_id.in_(all_ids)))
        session.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(all_ids)))
    model_order = (
        ("youtube_video", YoutubeVideo), ("package", OperationPackage), ("work_order", WorkOrder),
        ("task", OperationTask), ("schedule", ChannelScheduleEntry), ("playlist", ChannelPlaylist),
        ("publish_slot", ChannelPublishSlot), ("drama", Drama), ("channel", Channel),
    )
    deleted_counts: dict[str, int] = {}
    try:
        for entity_type, model in model_order:
            ids = ids_by_type.get(entity_type, [])
            if ids:
                result = session.execute(delete(model).where(model.id.in_(ids)))
                deleted_counts[entity_type] = result.rowcount or 0
        session.execute(delete(DemoDataEntity).where(DemoDataEntity.batch_id == batch.id))
        batch.status = "deleted"
        batch.deleted_at = datetime.now(timezone.utc)
        session.add(AuditEvent(
            actor_type="system", action="demo_data.deleted", entity_type="demo_data_batch", entity_id=batch.id,
            change_summary=f"一键删除演示数据：{deleted_counts}", occurred_at=batch.deleted_at,
        ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(batch)
    return {"active": False, "batch": batch, "entity_counts": deleted_counts}
