from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from zhiju.config import APP_ROOT, get_settings
from zhiju.models import (
    Channel,
    ChannelKeyword,
    ChannelPinnedCommentTemplate,
    ChannelPlaylist,
    ChannelProfile,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    Drama,
    FeishuSyncRun,
    OperationPackage,
    OperationTask,
    PackageCommunityPost,
    PackageCoverVariant,
    PackageDescription,
    PackagePlaylistAssignment,
    PackageTitle,
    ProductionBatch,
    ProductionNodeRun,
    WorkOrder,
)
from zhiju.services.operations import normalize_drama_title


NODE_SEQUENCE = ("search", "title", "cover", "description", "community", "merge")
OPERATION_PACKAGE_LAST_COLUMN = "S"
LANGUAGE_HINTS = {
    "英语": "en", "阿拉伯": "ar", "孟加拉": "bn", "印尼": "id", "西班牙": "es",
    "巴葡": "pt-BR", "葡萄牙": "pt-BR", "印地": "hi", "俄语": "ru", "菲律宾": "fil", "土耳其": "tr",
}
CHANNEL_LANGUAGE_CONFIG = {
    "印地语": ("hi", "IN", "印度", "Asia/Kolkata"),
    "孟加拉语": ("bn", "BD", "孟加拉国", "Asia/Dhaka"),
    "印尼语": ("id", "ID", "印度尼西亚", "Asia/Jakarta"),
    "菲律宾语": ("fil", "PH", "菲律宾", "Asia/Manila"),
    "西班牙语": ("es", "ES", "西班牙", "Europe/Madrid"),
    "巴西葡萄牙语": ("pt-BR", "BR", "巴西", "America/Sao_Paulo"),
    "土耳其语": ("tr", "TR", "土耳其", "Europe/Istanbul"),
    "阿拉伯语": ("ar", "SA", "沙特阿拉伯", "Asia/Riyadh"),
    "英语": ("en", "US", "美国", "America/New_York"),
    "俄语": ("ru", "RU", "俄罗斯", "Europe/Moscow"),
}


class FeishuSyncError(RuntimeError):
    pass


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("link") or item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    return str(value).strip()


def video_id_from_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/", 1)[0]
    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parsed.path == "/watch":
            return (parse_qs(parsed.query).get("v") or [""])[0]
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
    return ""


def youtube_channel_id_from_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower().endswith("youtube.com") and len(parts) >= 2 and parts[0] == "channel":
        return parts[1]
    return ""


def youtube_channel_id_from_page(value: str) -> str:
    match = re.search(r"https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})", value)
    return match.group(1) if match else ""


def resolve_youtube_channel_id(value: str) -> str:
    channel_id = youtube_channel_id_from_url(value)
    if channel_id:
        return channel_id
    try:
        with urlopen(Request(value, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
            return youtube_channel_id_from_page(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise FeishuSyncError(f"无法读取YouTube频道地址：{value}") from exc


def youtube_playlist_id_from_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    query_id = (parse_qs(parsed.query).get("list") or [""])[0]
    if query_id:
        return query_id
    parts = [part for part in parsed.path.split("/") if part]
    if "playlist" in parts:
        index = parts.index("playlist")
        if len(parts) > index + 1:
            return parts[index + 1]
    return ""


def business_drama_identifier(video_id: str | None, drama_number: int) -> str:
    return (video_id or "").strip() or str(drama_number)


def normalized_video_id(video_url: str, explicit_video_id: str) -> str:
    linked_video_id = video_id_from_url(video_url)
    if linked_video_id:
        return linked_video_id
    explicit_video_id = explicit_video_id.strip()
    return explicit_video_id if re.fullmatch(r"[A-Za-z0-9_-]{11}", explicit_video_id) else ""


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        if not app_id or not app_secret:
            raise FeishuSyncError("未配置飞书 App ID 或 App Secret")
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"

    def _request(self, method: str, path: str, *, token: str = "", payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urlopen(Request(self.base_url + path, data=body, headers=headers, method=method), timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise FeishuSyncError(f"连接飞书失败：{exc}") from exc
        if result.get("code") not in (None, 0):
            raise FeishuSyncError(f"飞书接口失败：{result.get('msg') or result.get('code')}")
        return result

    def rows(self, wiki_token: str, sheet_id: str, last_column: str) -> list[dict[str, str]]:
        auth = self._request("POST", "/auth/v3/tenant_access_token/internal", payload={
            "app_id": self.app_id, "app_secret": self.app_secret,
        })
        token = auth.get("tenant_access_token") or ""
        node = self._request("GET", f"/wiki/v2/spaces/get_node?token={quote(wiki_token)}", token=token)
        spreadsheet_token = ((node.get("data") or {}).get("node") or {}).get("obj_token")
        if not spreadsheet_token:
            raise FeishuSyncError("未能解析飞书表格标识")
        cell_range = quote(f"{sheet_id}!A1:{last_column}5000", safe="!")
        values = self._request(
            "GET",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/values/{cell_range}?valueRenderOption=FormattedValue",
            token=token,
        )
        matrix = (((values.get("data") or {}).get("valueRange") or {}).get("values") or [])
        if not matrix:
            return []
        headers = [cell_text(value).strip() for value in matrix[0]]
        rows = []
        for source_row_number, raw in enumerate(matrix[1:], start=2):
            row = {header: cell_text(raw[index]) if index < len(raw) else "" for index, header in enumerate(headers) if header}
            if any(row.values()):
                row["__source_row_number"] = str(source_row_number)
                rows.append(row)
        return rows


def _parse_date(value: str) -> date:
    normalized = re.sub(r"\D", "", value)
    if len(normalized) < 8:
        raise FeishuSyncError(f"日期格式不正确：{value}")
    return datetime.strptime(normalized[:8], "%Y%m%d").date()


def _parse_slot(value: str) -> tuple[date, time]:
    normalized = re.sub(r"\D", "", value)
    if len(normalized) < 10:
        raise FeishuSyncError(f"档期格式不正确：{value}")
    return datetime.strptime(normalized[:8], "%Y%m%d").date(), time(int(normalized[8:10]), 0)


def publish_datetime(publish_date: date, slot_time: time) -> datetime:
    return datetime.combine(publish_date, slot_time)


def community_planned_time(sequence_number: int, drama_publish_time: datetime) -> datetime | None:
    return drama_publish_time + timedelta(hours=2) if sequence_number == 1 else None


def _language(value: str) -> str:
    for hint, code in LANGUAGE_HINTS.items():
        if hint in value:
            return code
    return "und"


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _split_terms(value: str) -> list[str]:
    return list(dict.fromkeys(term.strip() for term in re.split(r"[,，;；\n]+", value) if term.strip()))


def _split_cover_blocks(value: str) -> list[str]:
    blocks = re.split(r"(?=标题[123][：:])", value.strip())
    return [block.strip() for block in blocks if re.match(r"标题[123][：:]", block.strip())]


def operation_package_completeness(row: dict[str, str]) -> tuple[bool, str | None]:
    counts = {
        "标题": len(_split_lines(row.get("标题", ""))[:3]),
        "标题翻译": len(_split_lines(row.get("标题翻译", ""))[:3]),
        "封面4：5": len(_split_cover_blocks(row.get("封面4：5", ""))),
        "封面16：9": len(_split_cover_blocks(row.get("封面16：9", ""))),
    }
    missing = [f"{name}需要3组，当前{count}组" for name, count in counts.items() if count != 3]
    return (not missing, "；".join(missing) or None)


def _cover_prompt(block: str) -> str:
    lines = block.splitlines()
    return "\n".join(lines[2:]).strip() if len(lines) > 2 else block


def _core_phrase(block: str) -> str | None:
    match = re.search(r"核心词[：:]\s*(.+)", block)
    return match.group(1).strip()[:255] if match else None


def _playlist_url(value: str) -> str | None:
    match = re.search(r"https://www\.youtube\.com/playlist\?list=[^\s]+", value)
    return match.group(0).rstrip(".,，。") if match else None


def _batch(session: Session, production_date: date) -> ProductionBatch:
    batch_number = f"FS-{production_date:%Y%m%d}"
    batch = session.scalar(select(ProductionBatch).where(ProductionBatch.batch_number == batch_number))
    if batch is None:
        batch = ProductionBatch(batch_number=batch_number, production_date=production_date, source="feishu", status="active")
        session.add(batch)
        session.flush()
    return batch


def _channel(session: Session, name: str, nickname: str = "") -> Channel:
    channel = session.scalar(select(Channel).where(
        Channel.deleted_at.is_(None),
        or_(Channel.original_name == name, Channel.operational_name == name, Channel.operational_name == nickname),
    ))
    if channel is None:
        channel = Channel(
            youtube_channel_id=f"FEISHU-{uuid.uuid4()}", original_name=name,
            operational_name=nickname or name, default_language=_language(nickname or name),
            timezone="Asia/Shanghai", daily_publish_count=0, status="new",
        )
        session.add(channel)
        session.flush()
    elif nickname and channel.operational_name != nickname:
        channel.operational_name = nickname
    return channel


def _drama(session: Session, title: str) -> Drama:
    normalized = normalize_drama_title(title)
    drama = session.scalar(select(Drama).where(Drama.normalized_title == normalized))
    if drama is None:
        drama = Drama(
            drama_code=f"DRM-{uuid.uuid4().hex[:12].upper()}", chinese_title=title,
            normalized_title=normalized, status="active",
        )
        session.add(drama)
        session.flush()
    return drama


def _slot(session: Session, channel: Channel, slot_time: time) -> ChannelPublishSlot:
    slot = session.scalar(select(ChannelPublishSlot).where(
        ChannelPublishSlot.channel_id == channel.id, ChannelPublishSlot.local_time == slot_time,
    ))
    if slot is None:
        count = len(list(session.scalars(select(ChannelPublishSlot.id).where(ChannelPublishSlot.channel_id == channel.id))))
        slot = ChannelPublishSlot(
            channel_id=channel.id, slot_type="main" if count == 0 else "aux", slot_number=count + 1,
            local_time=slot_time, timezone="Asia/Shanghai", status="active",
        )
        session.add(slot)
        session.flush()
    return slot


def _source_key(channel: Channel, drama: Drama, video_id: str, slot_value: str) -> str:
    identity = video_id or f"drama-{drama.drama_number}"
    return f"feishu:{identity}:{channel.id}:{slot_value}"


def _ensure_task(session: Session, row: dict[str, str], *, completed: bool) -> tuple[OperationTask, Channel, Drama, ProductionBatch, bool]:
    title = row.get("剧名", "").strip()
    channel_name = row.get("频道", "").strip()
    slot_value = row.get("档期", "").strip()
    if not title or not channel_name or not slot_value:
        raise FeishuSyncError("飞书行缺少剧名、频道或档期")
    video_url = (row.get("剧目地址") or row.get("地址") or "").strip()
    video_id = normalized_video_id(video_url, row.get("剧id", ""))
    publish_date, slot_time = _parse_slot(slot_value)
    task_date = _parse_date(row.get("日期", "")) if row.get("日期") else publish_date
    channel = _channel(session, channel_name, row.get("频道昵称", "").strip())
    drama = _drama(session, title)
    batch = _batch(session, task_date)
    publish_slot = _slot(session, channel, slot_time)
    key = _source_key(channel, drama, video_id, slot_value)
    task = session.scalar(select(OperationTask).where(OperationTask.idempotency_key == key))
    inserted = task is None
    if task is None:
        task = OperationTask(
            batch_id=batch.id, channel_id=channel.id, drama_id=drama.id, publish_slot_id=publish_slot.id,
            task_date=task_date, target_publish_date=publish_date,
            community_count=int(row.get("是否需要社区") or 0), source="import",
            status="completed" if completed else "pending_dispatch", idempotency_key=key,
            source_video_id=video_id or None, source_video_url=video_url or None,
            source_row_number=int(row["__source_row_number"]) if row.get("__source_row_number") else None,
        )
        session.add(task)
        session.flush()
    else:
        task.batch_id = batch.id
        task.task_date = task_date
        task.target_publish_date = publish_date
        task.community_count = int(row.get("是否需要社区") or 0)
        task.source_video_id = video_id or None
        task.source_video_url = video_url or None
        task.source_row_number = int(row["__source_row_number"]) if row.get("__source_row_number") else None
        if completed:
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
    return task, channel, drama, batch, inserted


def _playlist(session: Session, channel: Channel, name: str, description: str) -> ChannelPlaylist | None:
    if not name:
        return None
    playlist = session.scalar(select(ChannelPlaylist).where(
        ChannelPlaylist.channel_id == channel.id, ChannelPlaylist.local_name == name,
    ))
    if playlist is None:
        playlist = ChannelPlaylist(
            channel_id=channel.id, local_name=name, chinese_name=name, url=_playlist_url(description),
            sort_order=0, status="active",
        )
        session.add(playlist)
        session.flush()
    return playlist


def _replace_package_outputs(
    session: Session,
    package: OperationPackage,
    channel: Channel,
    row: dict[str, str],
    drama_publish_time: datetime,
) -> None:
    title_lines = _split_lines(row.get("标题", ""))[:3]
    translation_lines = _split_lines(row.get("标题翻译", ""))[:3]
    cover45 = _split_cover_blocks(row.get("封面4：5", ""))
    cover169 = _split_cover_blocks(row.get("封面16：9", ""))
    existing_titles = {
        title.variant_number: title
        for title in session.scalars(select(PackageTitle).where(
            PackageTitle.package_id == package.id,
            PackageTitle.generation_number == 1,
        ))
    }
    for index, localized_title in enumerate(title_lines):
        variant_number = index + 1
        title = existing_titles.get(variant_number)
        if title is None:
            title = PackageTitle(
                package_id=package.id, variant_number=variant_number, generation_number=1,
                localized_title=localized_title[:500], selected=True, status="selected",
            )
            session.add(title)
        title.localized_title = localized_title[:500]
        title.chinese_translation = translation_lines[index][:1000] if index < len(translation_lines) else None
        title.core_phrase = _core_phrase(cover45[index]) if index < len(cover45) else None
        session.flush()
        existing_covers = {
            cover.aspect_ratio: cover
            for cover in session.scalars(select(PackageCoverVariant).where(
                PackageCoverVariant.title_id == title.id,
                PackageCoverVariant.generation_number == 1,
            ))
        }
        for ratio, blocks in (("4:5", cover45), ("16:9", cover169)):
            if index >= len(blocks):
                continue
            cover = existing_covers.get(ratio)
            if cover is None:
                cover = PackageCoverVariant(
                    package_id=package.id, title_id=title.id, aspect_ratio=ratio, generation_number=1,
                    selected=True, status="selected",
                )
                session.add(cover)
            cover.creative_prompt = _cover_prompt(blocks[index])
    description_text = row.get("说明", "")
    description = session.scalar(select(PackageDescription).where(
        PackageDescription.package_id == package.id,
        PackageDescription.version_number == 1,
    ))
    if description is None:
        description = PackageDescription(
            package_id=package.id, version_number=1, language=channel.default_language or "und",
            localized_text=description_text, selected=True, status="selected",
        )
        session.add(description)
    description.localized_text = description_text
    description.chinese_translation = row.get("说明翻译") or None
    playlist = _playlist(session, channel, row.get("播放列表", ""), description_text)
    assignment = session.scalar(select(PackagePlaylistAssignment).where(
        PackagePlaylistAssignment.package_id == package.id,
    ))
    if playlist:
        if assignment is None:
            assignment = PackagePlaylistAssignment(
                package_id=package.id, playlist_id=playlist.id, rank_number=1,
                rationale="飞书任务表同步", status="selected",
            )
            session.add(assignment)
        else:
            assignment.playlist_id = playlist.id
    elif assignment is not None:
        session.delete(assignment)
    community_count = int(row.get("是否需要社区") or 0)
    existing_posts = {
        post.sequence_number: post
        for post in session.scalars(select(PackageCommunityPost).where(
            PackageCommunityPost.package_id == package.id,
            PackageCommunityPost.version_number == 1,
        ))
    }
    for sequence in range(1, community_count + 1):
        post = existing_posts.get(sequence)
        if post is None:
            post = PackageCommunityPost(
                package_id=package.id, sequence_number=sequence, version_number=1,
                language=channel.default_language or "und", localized_text="",
                selected=True, status="selected",
            )
            session.add(post)
        post.localized_text = row.get(f"社群文案{sequence}", "")
        post.planned_time = community_planned_time(sequence, drama_publish_time)
        post.image_prompt = row.get(f"社群图描述{sequence}") or None


def _package_outputs_match(
    session: Session,
    package: OperationPackage,
    row: dict[str, str],
    drama_publish_time: datetime,
) -> bool:
    title_lines = _split_lines(row.get("标题", ""))[:3]
    translation_lines = _split_lines(row.get("标题翻译", ""))[:3]
    cover45 = _split_cover_blocks(row.get("封面4：5", ""))
    cover169 = _split_cover_blocks(row.get("封面16：9", ""))
    if len(title_lines) != 3 or len(translation_lines) != 3 or len(cover45) != 3 or len(cover169) != 3:
        return False
    titles = list(session.scalars(
        select(PackageTitle).where(PackageTitle.package_id == package.id).order_by(PackageTitle.variant_number)
    ))
    if len(titles) != 3:
        return False
    for index, title in enumerate(titles):
        if (
            title.localized_title != title_lines[index]
            or (title.chinese_translation or "") != translation_lines[index]
            or (title.core_phrase or "") != (_core_phrase(cover45[index]) or "")
        ):
            return False
        covers = {
            cover.aspect_ratio: cover
            for cover in session.scalars(select(PackageCoverVariant).where(PackageCoverVariant.title_id == title.id))
        }
        if (
            set(covers) != {"4:5", "16:9"}
            or covers["4:5"].creative_prompt != _cover_prompt(cover45[index])
            or covers["16:9"].creative_prompt != _cover_prompt(cover169[index])
        ):
            return False
    description = session.scalar(select(PackageDescription).where(PackageDescription.package_id == package.id))
    if (
        description is None
        or description.localized_text != row.get("说明", "")
        or (description.chinese_translation or "") != row.get("说明翻译", "")
    ):
        return False
    playlist_name = row.get("播放列表", "")
    assignment = session.scalar(select(PackagePlaylistAssignment).where(PackagePlaylistAssignment.package_id == package.id))
    if playlist_name:
        playlist = session.get(ChannelPlaylist, assignment.playlist_id) if assignment else None
        if playlist is None or playlist.local_name != playlist_name:
            return False
    elif assignment is not None:
        return False
    expected_community = int(row.get("是否需要社区") or 0)
    posts = list(session.scalars(
        select(PackageCommunityPost).where(PackageCommunityPost.package_id == package.id).order_by(PackageCommunityPost.sequence_number)
    ))
    if len(posts) != expected_community:
        return False
    return all(
        post.localized_text == row.get(f"社群文案{post.sequence_number}", "")
        and (post.image_prompt or "") == row.get(f"社群图描述{post.sequence_number}", "")
        and post.planned_time == community_planned_time(post.sequence_number, drama_publish_time)
        for post in posts
    )


def _sync_rows(session: Session, sync_type: str, rows: list[dict[str, str]], sheet_id: str) -> dict[str, object]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    run = FeishuSyncRun(
        sync_type=sync_type, sheet_id=sheet_id, environment=settings.env,
        device_key=settings.device_key or settings.device_id or None, status="running", started_at=now,
    )
    session.add(run)
    session.commit()
    inserted = updated = skipped = 0
    affected_dates: list[date] = []
    try:
        for row in rows:
            if not row.get("剧名"):
                skipped += 1
                continue
            task, channel, drama, batch, was_inserted = _ensure_task(
                session, row, completed=sync_type == "operation_packages",
            )
            inserted += int(was_inserted)
            updated += int(not was_inserted)
            affected_dates.append(task.task_date)
            if sync_type == "work_orders":
                continue
            source_complete, incomplete_reason = operation_package_completeness(row)
            publish_slot = session.get(ChannelPublishSlot, task.publish_slot_id) if task.publish_slot_id else None
            if publish_slot is None:
                raise FeishuSyncError(f"飞书行缺少可用档期：{row.get('剧名', '')}")
            drama_publish_time = publish_datetime(task.target_publish_date, publish_slot.local_time)
            completed_at = datetime.now(timezone.utc)
            work_order = session.scalar(select(WorkOrder).where(WorkOrder.task_id == task.id))
            if work_order is None:
                work_order = WorkOrder(
                    task_id=task.id, batch_id=batch.id, channel_id=channel.id, drama_id=drama.id,
                    publish_slot_id=task.publish_slot_id, production_date=task.task_date,
                    target_publish_date=task.target_publish_date, community_count=task.community_count,
                    status="completed", attempt_count=1, started_at=completed_at, completed_at=completed_at,
                )
                session.add(work_order)
                session.flush()
            else:
                work_order.batch_id = batch.id
                work_order.status = "completed"
                work_order.completed_at = completed_at
                work_order.community_count = task.community_count
            package = session.scalar(select(OperationPackage).where(
                OperationPackage.work_order_id == work_order.id, OperationPackage.version_number == 1,
            ))
            if package is None:
                package = OperationPackage(
                    work_order_id=work_order.id, batch_id=batch.id, channel_id=channel.id, drama_id=drama.id,
                    version_number=1, status="review_pending", ready_at=completed_at, review_note="飞书结果同步",
                )
                session.add(package)
                session.flush()
                session.add_all([
                    ProductionNodeRun(
                        work_order_id=work_order.id, package_id=package.id, node_type=node_type,
                        sequence_number=sequence, attempt_number=1, status="completed",
                        idempotency_key=f"{work_order.id}:{node_type}:1", worker_key="feishu-sync",
                        started_at=completed_at, completed_at=completed_at,
                    )
                    for sequence, node_type in enumerate(NODE_SEQUENCE, start=1)
                ])
            else:
                package.batch_id = batch.id
                package.ready_at = completed_at
                if package.source_complete and source_complete:
                    skipped += 1
                    updated -= 1
                    continue
                if package.source_complete and not source_complete:
                    package.source_complete = False
                    package.source_incomplete_reason = incomplete_reason
                    continue
            if not source_complete or not _package_outputs_match(session, package, row, drama_publish_time):
                _replace_package_outputs(session, package, channel, row, drama_publish_time)
            package.source_complete = source_complete
            package.source_incomplete_reason = incomplete_reason
            if source_complete:
                package.status = "review_pending"
        run = session.get(FeishuSyncRun, run.id)
        run.status = "completed"
        run.rows_read = len(rows)
        run.rows_inserted = inserted
        run.rows_updated = updated
        run.rows_skipped = skipped
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
        return {
            "sync_type": sync_type, "environment": settings.env, "rows_read": len(rows),
            "rows_inserted": inserted, "rows_updated": updated, "rows_skipped": skipped,
            "latest_date": max(affected_dates) if affected_dates else None,
            "completed_at": run.completed_at,
        }
    except Exception as exc:
        session.rollback()
        failed_run = session.get(FeishuSyncRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.rows_read = len(rows)
            failed_run.rows_inserted = inserted
            failed_run.rows_updated = updated
            failed_run.rows_skipped = skipped
            failed_run.error_message = str(exc)[:2000]
            failed_run.completed_at = datetime.now(timezone.utc)
            session.commit()
        if isinstance(exc, FeishuSyncError):
            raise
        raise FeishuSyncError(f"同步写入失败：{exc}") from exc


def _client_rows(sheet_id: str, last_column: str) -> list[dict[str, str]]:
    settings = get_settings()
    app_id, app_secret = settings.feishu_app_id, settings.feishu_app_secret
    if settings.env == "development" and (not app_id or not app_secret):
        config_path = APP_ROOT.parent / "tools" / "feishu_sync" / "feishu_sync_config.json"
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            app_id = str(config.get("app_id") or "")
            app_secret = str(config.get("app_secret") or "")
    return FeishuClient(app_id, app_secret).rows(
        settings.feishu_wiki_token, sheet_id, last_column,
    )


def sync_work_orders(session: Session) -> dict[str, object]:
    settings = get_settings()
    rows = _client_rows(settings.feishu_work_order_sheet_id, "F")
    return _sync_rows(session, "work_orders", rows, settings.feishu_work_order_sheet_id)


def sync_operation_packages(session: Session) -> dict[str, object]:
    settings = get_settings()
    rows = _client_rows(settings.feishu_operation_package_sheet_id, OPERATION_PACKAGE_LAST_COLUMN)
    return _sync_rows(session, "operation_packages", rows, settings.feishu_operation_package_sheet_id)


def _sync_channel_profile(session: Session, channel: Channel, row: dict[str, str], branding: dict[str, str]) -> None:
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel.id))
    if profile is None:
        profile = ChannelProfile(channel_id=channel.id)
        session.add(profile)
    profile.description = branding.get("说明") or None
    profile.language = channel.default_language
    profile.positioning = channel.channel_type
    profile.popup_scheme = row.get("弹框") or None
    profile.title_template = row.get("标题模版") or None
    profile.fixed_symbol = row.get("固定符号") or None
    profile.status = "active"


def _sync_channel_terms(session: Session, channel: Channel, branding: dict[str, str]) -> None:
    language = channel.default_language or "und"
    desired = {
        (keyword_type, term)
        for keyword_type, column in (("keyword", "关键词"), ("tag", "标签"))
        for term in _split_terms(branding.get(column, ""))
    }
    existing = list(session.scalars(select(ChannelKeyword).where(
        ChannelKeyword.channel_id == channel.id,
        ChannelKeyword.source == "feishu_channel_branding",
    )))
    by_identity = {(item.keyword_type, item.keyword): item for item in existing}
    for item in existing:
        item.status = "active" if (item.keyword_type, item.keyword) in desired else "archived"
    for keyword_type, term in desired:
        item = by_identity.get((keyword_type, term))
        if item is None:
            session.add(ChannelKeyword(
                channel_id=channel.id,
                keyword=term,
                keyword_type=keyword_type,
                language=language,
                source="feishu_channel_branding",
                status="active",
            ))
        else:
            item.language = language


def _sync_pinned_template(session: Session, channel: Channel, language: str, body: str) -> None:
    body = body.strip()
    if not body:
        return
    rows = list(session.scalars(select(ChannelPinnedCommentTemplate).where(
        ChannelPinnedCommentTemplate.channel_id == channel.id,
        ChannelPinnedCommentTemplate.language == language,
    ).order_by(ChannelPinnedCommentTemplate.version_number.desc())))
    if rows and rows[0].body == body:
        rows[0].status = "active"
        return
    for row in rows:
        if row.status == "active":
            row.status = "superseded"
    session.add(ChannelPinnedCommentTemplate(
        channel_id=channel.id,
        language=language,
        version_number=(rows[0].version_number + 1) if rows else 1,
        body=body,
        status="active",
        effective_from=datetime.now(timezone.utc),
    ))


def _sync_channel_playlists(session: Session, channel: Channel, row: dict[str, str]) -> None:
    desired_names: set[str] = set()
    for sequence in range(1, 6):
        name = row.get(f"播放列表{sequence}", "").strip()
        if not name:
            continue
        desired_names.add(name)
        url = row.get(f"列表地址{sequence}", "").strip()
        playlist_id = youtube_playlist_id_from_url(url) or None
        playlist = session.scalar(select(ChannelPlaylist).where(
            ChannelPlaylist.channel_id == channel.id,
            ChannelPlaylist.local_name == name,
        ))
        if playlist is None and playlist_id:
            playlist = session.scalar(select(ChannelPlaylist).where(
                ChannelPlaylist.youtube_playlist_id == playlist_id,
            ))
        if playlist is None:
            playlist = ChannelPlaylist(channel_id=channel.id, local_name=name)
            session.add(playlist)
        playlist.youtube_playlist_id = playlist_id
        playlist.local_name = name
        playlist.local_description = row.get(f"播放列表说明{sequence}") or None
        playlist.url = url or None
        playlist.sort_order = sequence
        playlist.status = "active"
    for playlist in session.scalars(select(ChannelPlaylist).where(ChannelPlaylist.channel_id == channel.id)):
        if playlist.local_name not in desired_names:
            playlist.status = "archived"


def sync_channels(session: Session) -> dict[str, object]:
    settings = get_settings()
    master_rows = [
        row for row in _client_rows(settings.feishu_channel_master_sheet_id, "N")
        if row.get("申请成功日期")
    ]
    info_rows = _client_rows(settings.feishu_channel_info_sheet_id, "AA")
    branding_rows = _client_rows(settings.feishu_channel_branding_sheet_id, "G")
    info_by_name = {row.get("频道名", "").strip(): row for row in info_rows if row.get("频道名")}
    branding_by_name = {row.get("频道名", "").strip(): row for row in branding_rows if row.get("频道名")}
    master_names = [row.get("频道名", "").strip() for row in master_rows]
    if len(master_names) != len(set(master_names)):
        raise FeishuSyncError("频道总表存在重复频道名，已停止同步")
    missing_info = sorted(set(master_names) - set(info_by_name))
    missing_branding = sorted(set(master_names) - set(branding_by_name))
    if missing_info or missing_branding:
        raise FeishuSyncError(
            f"频道资料未完整对应：频道信息缺少{missing_info}；频道装修缺少{missing_branding}"
        )

    run = FeishuSyncRun(
        sync_type="channels",
        sheet_id=settings.feishu_channel_master_sheet_id,
        environment=settings.env,
        device_key=settings.device_key or settings.device_id or None,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.commit()
    inserted = updated = skipped = 0
    try:
        for master in master_rows:
            name = master.get("频道名", "").strip()
            info = info_by_name[name]
            branding = branding_by_name[name]
            channel_url = info.get("频道地址", "").strip()
            youtube_channel_id = resolve_youtube_channel_id(channel_url)
            if not youtube_channel_id:
                raise FeishuSyncError(f"频道地址无法解析YouTube Channel ID：{name}")
            language_name = master.get("语言", "").strip()
            if language_name not in CHANNEL_LANGUAGE_CONFIG:
                raise FeishuSyncError(f"未配置频道语言对应国家：{language_name}")
            language, country_code, country_name, channel_timezone = CHANNEL_LANGUAGE_CONFIG[language_name]
            by_external_id = session.scalar(select(Channel).where(Channel.youtube_channel_id == youtube_channel_id))
            by_name = session.scalar(select(Channel).where(Channel.original_name == name))
            if by_external_id is not None and by_name is not None and by_external_id.id != by_name.id:
                raise FeishuSyncError(f"频道名与YouTube Channel ID指向不同记录：{name}")
            channel = by_external_id or by_name
            if channel is None:
                channel = Channel(youtube_channel_id=youtube_channel_id, original_name=name)
                session.add(channel)
                session.flush()
                inserted += 1
            else:
                updated += 1
            channel.youtube_channel_id = youtube_channel_id
            channel.youtube_channel_url = channel_url
            channel.original_name = name
            channel.operational_name = info.get("本地昵称") or name
            channel.country_code = country_code
            channel.country_name_zh = country_name
            channel.default_language = language
            channel.channel_type = master.get("频道类型") or None
            channel.drama_type = master.get("短剧类型") or None
            channel.default_genre = channel.channel_type
            channel.application_success_date = _parse_date(master.get("申请成功日期", ""))
            channel.display_order = int(master.get("序号") or 0) or None
            channel.timezone = channel_timezone
            _sync_channel_profile(session, channel, info, branding)
            _sync_channel_terms(session, channel, branding)
            _sync_pinned_template(session, channel, language, info.get("置顶回复", ""))
            _sync_pinned_template(session, channel, "zh-CN", info.get("置顶回复中文", ""))
            _sync_channel_playlists(session, channel, info)

        run = session.get(FeishuSyncRun, run.id)
        run.status = "completed"
        run.rows_read = len(master_rows)
        run.rows_inserted = inserted
        run.rows_updated = updated
        run.rows_skipped = skipped
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
        latest_date = max(
            (channel.application_success_date for channel in session.scalars(
                select(Channel).where(Channel.original_name.in_(master_names))
            ) if channel.application_success_date),
            default=None,
        )
        return {
            "sync_type": "channels",
            "environment": settings.env,
            "rows_read": len(master_rows),
            "rows_inserted": inserted,
            "rows_updated": updated,
            "rows_skipped": skipped,
            "latest_date": latest_date,
            "completed_at": run.completed_at,
        }
    except Exception as exc:
        session.rollback()
        failed_run = session.get(FeishuSyncRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.rows_read = len(master_rows)
            failed_run.rows_inserted = inserted
            failed_run.rows_updated = updated
            failed_run.rows_skipped = skipped
            failed_run.error_message = str(exc)[:2000]
            failed_run.completed_at = datetime.now(timezone.utc)
            session.commit()
        if isinstance(exc, FeishuSyncError):
            raise
        raise FeishuSyncError(f"频道同步写入失败：{exc}") from exc
