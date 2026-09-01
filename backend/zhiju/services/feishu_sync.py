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
    DramaAlias,
    DramaProductionState,
    DramaTranslation,
    FeishuSyncRun,
    Language,
    OperationPackage,
    OperationTask,
    PackageCommunityPost,
    PackageCoverVariant,
    PackageDescription,
    PackagePlaylistAssignment,
    PackageTitle,
    ProductionBatch,
    ProductionNodeRun,
    ScheduleCandidate,
    ScheduleChangeHistory,
    WorkOrder,
)
from zhiju.services.operations import normalize_drama_title


NODE_SEQUENCE = ("search", "title", "cover", "description", "community", "merge")
OPERATION_PACKAGE_LAST_COLUMN = "S"
CHANNEL_SCHEDULE_HEADERS = (
    "剧名",
    "videoId",
    "链接",
    "档期",
    "档期时间",
    "是否上传",
    "是否上线",
    "是否写入任务",
)
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
DRAMA_LANGUAGE_COLUMNS = {
    "印地语 Hindi": ("hi", "印地语", "Hindi"),
    "孟加拉语 Bengali": ("bn", "孟加拉语", "Bengali"),
    "印尼语 Indonesian": ("id", "印度尼西亚语", "Indonesian"),
    "菲律宾语 Filipino / Tagalog": ("fil", "菲律宾语", "Filipino / Tagalog"),
    "西班牙语 Spanish": ("es", "西班牙语", "Spanish"),
    "葡萄牙语 Brazilian Portuguese": ("pt-BR", "巴西葡萄牙语", "Brazilian Portuguese"),
    "土耳其语 Turkish": ("tr", "土耳其语", "Turkish"),
    "阿拉伯语 Arabic": ("ar", "阿拉伯语", "Arabic"),
    "英语 English": ("en", "英语", "English"),
    "俄语 Russian": ("ru", "俄语", "Russian"),
    "泰语 Thai": ("th", "泰语", "Thai"),
    "越南语 Vietnamese": ("vi", "越南语", "Vietnamese"),
    "法语 French": ("fr", "法语", "French"),
    "马来语 Malay": ("ms", "马来语", "Malay"),
    "德语 German": ("de", "德语", "German"),
    "乌尔都语 Urdu": ("ur", "乌尔都语", "Urdu"),
    "意大利语 Italian": ("it", "意大利语", "Italian"),
    "韩语 Korean": ("ko", "韩语", "Korean"),
    "日语 Japanese": ("ja", "日语", "Japanese"),
    "波兰语 Polish": ("pl", "波兰语", "Polish"),
    "希腊语": ("el", "希腊语", None),
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


def parse_feishu_schedule_datetime(
    value: str,
    *,
    sheet_title: str,
    row_number: int,
) -> tuple[datetime, bool]:
    normalized = value.strip()
    corrected = False
    if normalized == "2026-08-010 12:00":
        normalized = "2026-08-10 12:00"
        corrected = True
    for pattern in (
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(normalized, pattern), corrected
        except ValueError:
            continue
    raise FeishuSyncError(
        f"飞书频道排期表 {sheet_title} 第 {row_number} 行档期时间格式不正确：{value}"
    )


def parse_feishu_schedule_flag(
    value: str,
    *,
    field_name: str,
    sheet_title: str,
    row_number: int,
) -> bool:
    normalized = value.strip()
    if normalized in {"", "0"}:
        return False
    if normalized == "1":
        return True
    raise FeishuSyncError(
        f"飞书频道排期表 {sheet_title} 第 {row_number} 行{field_name}只能为 1、0 或空"
    )


def feishu_sheet_id_from_url(value: str) -> str:
    return (parse_qs(urlparse(value.strip()).query).get("sheet") or [""])[0].strip()


def _unique_channel_for_directory(
    channels: list[Channel],
    *,
    channel_name: str,
    channel_nickname: str,
    row_number: int,
) -> Channel:
    names = {name for name in (channel_name, channel_nickname) if name}
    matches = [
        channel
        for channel in channels
        if channel.original_name in names or (channel.operational_name or "") in names
    ]
    if len(matches) != 1:
        detail = "未匹配智矩频道" if not matches else "匹配到多个智矩频道"
        raise FeishuSyncError(
            f"飞书频道目录第 {row_number} 行{detail}：{channel_nickname or channel_name}"
        )
    return matches[0]


def prepare_channel_schedule_rows(
    session: Session,
    *,
    directory_rows: list[dict[str, str]],
    sheet_rows: list[tuple[str, str, list[dict[str, str]]]],
    as_of_date: date | None = None,
) -> tuple[list[dict[str, object]], int]:
    as_of_date = as_of_date or date.today()
    channels = list(session.scalars(select(Channel).where(Channel.deleted_at.is_(None))))
    directory_by_sheet: dict[str, Channel] = {}
    for row in directory_rows:
        row_number = int(row.get("__source_row_number") or 0)
        sheet_id = feishu_sheet_id_from_url(row.get("链接", ""))
        if not sheet_id:
            raise FeishuSyncError(f"飞书频道目录第 {row_number} 行缺少频道工作表链接")
        if sheet_id in directory_by_sheet:
            raise FeishuSyncError(f"飞书频道目录第 {row_number} 行工作表重复：{sheet_id}")
        directory_by_sheet[sheet_id] = _unique_channel_for_directory(
            channels,
            channel_name=row.get("频道名", "").strip(),
            channel_nickname=row.get("频道昵称", "").strip(),
            row_number=row_number,
        )

    dramas = list(session.scalars(select(Drama)))
    dramas_by_title = {drama.normalized_title: drama for drama in dramas}
    aliases_by_title = {
        alias.normalized_alias: drama
        for alias, drama in session.execute(
            select(DramaAlias, Drama).join(Drama, Drama.id == DramaAlias.drama_id)
        )
    }
    channel_ids = {channel.id for channel in directory_by_sheet.values()}
    slots = list(
        session.scalars(
            select(ChannelPublishSlot).where(
                ChannelPublishSlot.channel_id.in_(channel_ids),
            )
        )
    ) if channel_ids else []

    prepared: list[dict[str, object]] = []
    used_schedule_keys: dict[tuple[str, date, str], tuple[str, int]] = {}
    used_schedule_times: dict[tuple[str, date, str, time], tuple[str, int]] = {}
    corrected_count = 0
    beijing_zone = ZoneInfo("Asia/Shanghai")
    for sheet_id, sheet_title, rows in sheet_rows:
        channel = directory_by_sheet.get(sheet_id)
        if channel is None:
            raise FeishuSyncError(f"飞书频道工作表不在频道目录中：{sheet_title}")
        for row in rows:
            row_number = int(row.get("__source_row_number") or 0)
            drama_title = row.get("剧名", "").strip()
            if not drama_title:
                raise FeishuSyncError(
                    f"飞书频道排期表 {sheet_title} 第 {row_number} 行缺少剧名"
                )
            normalized_title = normalize_drama_title(drama_title)
            drama = dramas_by_title.get(normalized_title) or aliases_by_title.get(normalized_title)
            if drama is None:
                raise FeishuSyncError(
                    f"飞书频道排期表 {sheet_title} 第 {row_number} 行剧目不在公共剧库：{drama_title}"
                )
            beijing_datetime, corrected = parse_feishu_schedule_datetime(
                row.get("档期时间", ""),
                sheet_title=sheet_title,
                row_number=row_number,
            )
            corrected_count += int(corrected)
            beijing_aware = beijing_datetime.replace(tzinfo=beijing_zone)
            utc_aware = beijing_aware.astimezone(timezone.utc)
            local_aware = utc_aware.astimezone(ZoneInfo(channel.timezone))
            slot_label = row.get("档期", "").strip()
            slot_type = {"主档": "main", "辅档": "aux"}.get(slot_label)
            if slot_type is None:
                raise FeishuSyncError(
                    f"飞书频道排期表 {sheet_title} 第 {row_number} 行档期必须为主档或辅档：{slot_label}"
                )
            matching_slots = sorted([
                slot
                for slot in slots
                if slot.channel_id == channel.id
                and slot.slot_type == slot_type
                and slot.local_time == local_aware.time().replace(tzinfo=None)
            ], key=lambda slot: (slot.status != "active", slot.slot_number))
            schedule_time_key = (
                channel.id,
                local_aware.date(),
                slot_type,
                local_aware.time().replace(tzinfo=None),
            )
            first_time_source = used_schedule_times.get(schedule_time_key)
            if first_time_source is not None and local_aware.date() >= as_of_date:
                first_sheet, first_row = first_time_source
                raise FeishuSyncError(
                    f"飞书频道排期重复：{sheet_title} 第 {row_number} 行与"
                    f"{first_sheet} 第 {first_row} 行使用同一频道、日期和档位"
                )
            selected_slot = next(
                (
                    slot for slot in matching_slots
                    if (channel.id, local_aware.date(), slot.id) not in used_schedule_keys
                ),
                None,
            )
            if selected_slot is None:
                slot_number = 1 + max(
                    (
                        slot.slot_number
                        for slot in slots
                        if slot.channel_id == channel.id and slot.slot_type == slot_type
                    ),
                    default=0,
                )
                historical_slot = ChannelPublishSlot(
                    channel_id=channel.id,
                    slot_type=slot_type,
                    slot_number=slot_number,
                    local_time=local_aware.time().replace(tzinfo=None),
                    timezone=channel.timezone,
                    status="archived",
                )
                session.add(historical_slot)
                session.flush()
                slots.append(historical_slot)
                selected_slot = historical_slot
            schedule_key = (channel.id, local_aware.date(), selected_slot.id)
            first_source = used_schedule_keys.get(schedule_key)
            if first_source is not None:
                first_sheet, first_row = first_source
                raise FeishuSyncError(
                    f"飞书频道排期重复：{sheet_title} 第 {row_number} 行与"
                    f"{first_sheet} 第 {first_row} 行使用同一频道、日期和档位"
                )
            used_schedule_keys[schedule_key] = (sheet_title, row_number)
            used_schedule_times.setdefault(schedule_time_key, (sheet_title, row_number))
            video_url = row.get("链接", "").strip()
            explicit_video_id = row.get("videoId", "").strip()
            video_id = (
                video_id_from_url(video_url)
                or video_id_from_url(explicit_video_id)
                or normalized_video_id(video_url, explicit_video_id)
            )
            prepared.append({
                "channel_id": channel.id,
                "drama_id": drama.id,
                "publish_slot_id": selected_slot.id,
                "publish_date": local_aware.date(),
                "planned_local_time": local_aware.replace(tzinfo=None),
                "planned_beijing_time": beijing_aware.replace(tzinfo=None),
                "planned_utc_time": utc_aware.replace(tzinfo=None),
                "source_type": "feishu",
                "source_sheet_id": sheet_id,
                "source_sheet_title": sheet_title,
                "source_row_number": row_number,
                "source_video_id": video_id or None,
                "source_video_url": video_url or (explicit_video_id if video_id_from_url(explicit_video_id) else None),
                "is_uploaded": parse_feishu_schedule_flag(
                    row.get("是否上传", ""),
                    field_name="是否上传",
                    sheet_title=sheet_title,
                    row_number=row_number,
                ),
                "is_published": parse_feishu_schedule_flag(
                    row.get("是否上线", ""),
                    field_name="是否上线",
                    sheet_title=sheet_title,
                    row_number=row_number,
                ),
                "is_task_written": parse_feishu_schedule_flag(
                    row.get("是否写入任务", ""),
                    field_name="是否写入任务",
                    sheet_title=sheet_title,
                    row_number=row_number,
                ),
            })
    return prepared, corrected_count


def upsert_channel_schedule_rows(
    session: Session,
    rows: list[dict[str, object]],
    *,
    now: datetime,
) -> dict[str, int]:
    row_keys: set[tuple[str, date, str]] = set()
    for row in rows:
        key = (str(row["channel_id"]), row["publish_date"], str(row["publish_slot_id"]))
        if key in row_keys:
            raise FeishuSyncError(
                f"飞书频道排期存在重复频道日期档位：{row['source_sheet_title']} "
                f"第 {row['source_row_number']} 行"
            )
        row_keys.add(key)

    channel_ids = {str(row["channel_id"]) for row in rows}
    publish_dates = {row["publish_date"] for row in rows}
    existing_rows = list(session.scalars(select(ChannelScheduleEntry).where(
        ChannelScheduleEntry.channel_id.in_(channel_ids),
        ChannelScheduleEntry.publish_date.in_(publish_dates),
    ))) if rows else []
    existing_by_key = {
        (schedule.channel_id, schedule.publish_date, schedule.publish_slot_id): schedule
        for schedule in existing_rows
    }
    inserted = updated = skipped = 0
    synced_fields = (
        "drama_id",
        "planned_local_time",
        "planned_beijing_time",
        "planned_utc_time",
        "source_type",
        "source_sheet_id",
        "source_row_number",
        "source_video_id",
        "source_video_url",
        "is_uploaded",
        "is_published",
        "is_task_written",
    )
    for row in rows:
        key = (str(row["channel_id"]), row["publish_date"], str(row["publish_slot_id"]))
        status = "published" if row["is_published"] else (
            "confirmed" if row["is_uploaded"] else "planned"
        )
        schedule = existing_by_key.get(key)
        if schedule is None:
            schedule = ChannelScheduleEntry(
                channel_id=key[0],
                drama_id=str(row["drama_id"]),
                publish_slot_id=key[2],
                publish_date=key[1],
                planned_local_time=row["planned_local_time"],
                planned_beijing_time=row["planned_beijing_time"],
                planned_utc_time=row["planned_utc_time"],
                community_count=0,
                status=status,
                priority=100,
                idempotency_key=f"feishu-schedule:{key[0]}:{key[1].isoformat()}:{key[2]}",
                source_type="feishu",
                source_sheet_id=str(row["source_sheet_id"]),
                source_row_number=int(row["source_row_number"]),
                source_synced_at=now,
                source_video_id=row["source_video_id"],
                source_video_url=row["source_video_url"],
                is_uploaded=bool(row["is_uploaded"]),
                is_published=bool(row["is_published"]),
                is_task_written=bool(row["is_task_written"]),
            )
            session.add(schedule)
            session.flush()
            session.add_all([
                ScheduleCandidate(
                    schedule_id=schedule.id,
                    drama_id=schedule.drama_id,
                    candidate_type="primary",
                    rank_number=1,
                    reason="飞书频道排期同步",
                    status="selected",
                ),
                ScheduleChangeHistory(
                    schedule_id=schedule.id,
                    new_drama_id=schedule.drama_id,
                    new_planned_utc_time=schedule.planned_utc_time,
                    new_status=status,
                    reason="飞书频道排期同步",
                    actor_type="system",
                    changed_at=now,
                ),
            ])
            existing_by_key[key] = schedule
            inserted += 1
            continue

        values = {field: row[field] for field in synced_fields}
        changed = schedule.status != status or any(
            getattr(schedule, field) != value for field, value in values.items()
        )
        if not changed:
            schedule.source_synced_at = now
            skipped += 1
            continue
        old_drama_id = schedule.drama_id
        old_utc_time = schedule.planned_utc_time
        old_status = schedule.status
        for field, value in values.items():
            setattr(schedule, field, value)
        schedule.status = status
        schedule.source_synced_at = now
        selected = session.scalar(select(ScheduleCandidate).where(
            ScheduleCandidate.schedule_id == schedule.id,
            ScheduleCandidate.status == "selected",
        ))
        if selected is None:
            session.add(ScheduleCandidate(
                schedule_id=schedule.id,
                drama_id=schedule.drama_id,
                candidate_type="primary",
                rank_number=1,
                reason="飞书频道排期同步",
                status="selected",
            ))
        elif selected.drama_id != schedule.drama_id:
            selected.drama_id = schedule.drama_id
        session.add(ScheduleChangeHistory(
            schedule_id=schedule.id,
            old_drama_id=old_drama_id,
            new_drama_id=schedule.drama_id,
            old_planned_utc_time=old_utc_time,
            new_planned_utc_time=schedule.planned_utc_time,
            old_status=old_status,
            new_status=status,
            reason="飞书频道排期同步更新",
            actor_type="system",
            changed_at=now,
        ))
        updated += 1
    session.flush()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


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

    def _spreadsheet_access(self, wiki_token: str) -> tuple[str, str]:
        auth = self._request("POST", "/auth/v3/tenant_access_token/internal", payload={
            "app_id": self.app_id, "app_secret": self.app_secret,
        })
        token = auth.get("tenant_access_token") or ""
        node = self._request("GET", f"/wiki/v2/spaces/get_node?token={quote(wiki_token)}", token=token)
        spreadsheet_token = ((node.get("data") or {}).get("node") or {}).get("obj_token")
        if not spreadsheet_token:
            raise FeishuSyncError("未能解析飞书表格标识")
        return token, spreadsheet_token

    def sheet_id_by_title(self, wiki_token: str, title: str) -> str:
        token, spreadsheet_token = self._spreadsheet_access(wiki_token)
        result = self._request(
            "GET",
            f"/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query?page_size=100",
            token=token,
        )
        matches = [
            sheet.get("sheet_id")
            for sheet in ((result.get("data") or {}).get("sheets") or [])
            if str(sheet.get("title") or "").strip() == title.strip()
        ]
        if len(matches) != 1 or not matches[0]:
            raise FeishuSyncError(f"未找到唯一的飞书工作表：{title}")
        return str(matches[0])

    def workbook_sheets(self, wiki_token: str) -> tuple[str, str, list[dict[str, object]]]:
        token, spreadsheet_token = self._spreadsheet_access(wiki_token)
        result = self._request(
            "GET",
            f"/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query?page_size=100",
            token=token,
        )
        sheets = list((result.get("data") or {}).get("sheets") or [])
        return token, spreadsheet_token, sheets

    def _rows_from_sheet(
        self,
        token: str,
        spreadsheet_token: str,
        sheet_id: str,
        last_column: str,
    ) -> list[dict[str, str]]:
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

    def rows(self, wiki_token: str, sheet_id: str, last_column: str) -> list[dict[str, str]]:
        token, spreadsheet_token = self._spreadsheet_access(wiki_token)
        return self._rows_from_sheet(token, spreadsheet_token, sheet_id, last_column)

    def rows_from_workbook(
        self,
        token: str,
        spreadsheet_token: str,
        sheet_id: str,
        last_column: str,
    ) -> list[dict[str, str]]:
        return self._rows_from_sheet(token, spreadsheet_token, sheet_id, last_column)

    def rows_by_title(
        self,
        wiki_token: str,
        title: str,
        last_column: str,
    ) -> tuple[str, list[dict[str, str]]]:
        token, spreadsheet_token = self._spreadsheet_access(wiki_token)
        result = self._request(
            "GET",
            f"/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query?page_size=100",
            token=token,
        )
        matches = [
            sheet.get("sheet_id")
            for sheet in ((result.get("data") or {}).get("sheets") or [])
            if str(sheet.get("title") or "").strip() == title.strip()
        ]
        if len(matches) != 1 or not matches[0]:
            raise FeishuSyncError(f"未找到唯一的飞书工作表：{title}")
        sheet_id = str(matches[0])
        return sheet_id, self._rows_from_sheet(token, spreadsheet_token, sheet_id, last_column)

    def matrix_by_title(
        self,
        wiki_token: str,
        title: str,
        last_column: str,
    ) -> tuple[str, list[list[str]]]:
        token, spreadsheet_token = self._spreadsheet_access(wiki_token)
        result = self._request(
            "GET",
            f"/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query?page_size=100",
            token=token,
        )
        matches = [
            sheet.get("sheet_id")
            for sheet in ((result.get("data") or {}).get("sheets") or [])
            if str(sheet.get("title") or "").strip() == title.strip()
        ]
        if len(matches) != 1 or not matches[0]:
            raise FeishuSyncError(f"未找到唯一的飞书工作表：{title}")
        sheet_id = str(matches[0])
        cell_range = quote(f"{sheet_id}!A1:{last_column}5000", safe="!")
        values = self._request(
            "GET",
            f"/sheets/v2/spreadsheets/{spreadsheet_token}/values/{cell_range}?valueRenderOption=FormattedValue",
            token=token,
        )
        matrix = (((values.get("data") or {}).get("valueRange") or {}).get("values") or [])
        return sheet_id, [[cell_text(value) for value in row] for row in matrix]


def parse_language_matrix(matrix: list[list[str]]) -> dict[str, object]:
    if len(matrix) < 2:
        raise FeishuSyncError("飞书语言表缺少两行表头")
    tiers, names = matrix[0], matrix[1]
    languages = []
    language_columns: list[tuple[int, str]] = []
    seen_codes: set[str] = set()
    for column_index in range(3, max(len(tiers), len(names))):
        name = cell_text(names[column_index] if column_index < len(names) else "").strip()
        if not name:
            continue
        definition = DRAMA_LANGUAGE_COLUMNS.get(name)
        if definition is None:
            raise FeishuSyncError(f"未知语言列：{name}")
        code, name_zh, native_name = definition
        if code in seen_codes:
            raise FeishuSyncError(f"飞书语言表存在重复语言列：{name}")
        tier = cell_text(tiers[column_index] if column_index < len(tiers) else "").strip()
        if tier not in {"S", "A", "B", "C"}:
            raise FeishuSyncError(f"语言 {name} 的优先级不正确：{tier or '空'}")
        seen_codes.add(code)
        language_columns.append((column_index, code))
        languages.append({
            "code": code,
            "name_zh": name_zh,
            "native_name": native_name,
            "priority_tier": tier,
        })
    expected_codes = {definition[0] for definition in DRAMA_LANGUAGE_COLUMNS.values()}
    if seen_codes != expected_codes:
        missing = ", ".join(sorted(expected_codes - seen_codes))
        raise FeishuSyncError(f"飞书语言表缺少语言列：{missing}")

    dramas = []
    seen_titles: dict[str, int] = {}
    for source_row_number, raw in enumerate(matrix[2:], start=3):
        if not any(cell_text(value).strip() for value in raw):
            continue
        title = cell_text(raw[0] if raw else "").strip()
        if not title:
            raise FeishuSyncError(f"飞书语言表第 {source_row_number} 行缺少作品名称")
        normalized_title = normalize_drama_title(title)
        previous_row = seen_titles.get(normalized_title)
        if previous_row is not None:
            raise FeishuSyncError(f"飞书语言表第 {previous_row}、{source_row_number} 行作品名称重复：{title}")
        seen_titles[normalized_title] = source_row_number
        covered_codes = set()
        for column_index, code in language_columns:
            value = cell_text(raw[column_index] if column_index < len(raw) else "").strip()
            if value == "1":
                covered_codes.add(code)
            elif value:
                raise FeishuSyncError(
                    f"飞书语言表第 {source_row_number} 行语言 {code} 的值必须为 1 或空"
                )
        dramas.append({
            "source_row_number": source_row_number,
            "chinese_title": title,
            "normalized_title": normalized_title,
            "batch_name": cell_text(raw[2] if len(raw) > 2 else "").strip() or None,
            "covered_codes": covered_codes,
        })
    return {"languages": languages, "dramas": dramas}


def _parse_date(value: str) -> date:
    separated = re.match(r"^\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})(?:\D|$)", value)
    if separated:
        year, month, day = (int(part) for part in separated.groups())
        return date(year, month, day)
    normalized = re.sub(r"\D", "", value)
    if len(normalized) < 8:
        raise FeishuSyncError(f"日期格式不正确：{value}")
    return datetime.strptime(normalized[:8], "%Y%m%d").date()


def parse_drama_expiry(value: str) -> datetime | None:
    if not value.strip():
        return None
    return datetime.combine(_parse_date(value), time(23, 59, 59))


def map_drama_status(value: str) -> str:
    normalized = value.strip()
    if normalized in {"", "制作"}:
        return "active"
    if normalized == "已删":
        return "archived"
    raise FeishuSyncError(f"未知剧库状态：{value}")


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
    for field in ("播放列表", "说明", "说明翻译"):
        if not row.get(field, "").strip():
            missing.append(f"{field}不能为空")
    community_count = int(row.get("是否需要社区") or 0)
    for sequence in range(1, community_count + 1):
        for field in (f"社群文案{sequence}", f"社群图描述{sequence}"):
            if not row.get(field, "").strip():
                missing.append(f"{field}不能为空")
    return (not missing, "；".join(missing) or None)


def operation_package_sync_decision(
    *,
    existing_source_complete: bool,
    incoming_source_complete: bool,
    outputs_match: bool,
) -> str:
    if existing_source_complete and incoming_source_complete and outputs_match:
        return "skip"
    return "refresh"


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
                outputs_match = False
            else:
                package.batch_id = batch.id
                package.ready_at = completed_at
                outputs_match = _package_outputs_match(session, package, row, drama_publish_time)
                if operation_package_sync_decision(
                    existing_source_complete=package.source_complete,
                    incoming_source_complete=source_complete,
                    outputs_match=outputs_match,
                ) == "skip":
                    skipped += 1
                    updated -= 1
                    continue
            if not source_complete or not outputs_match:
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


def feishu_fallback_config_paths(app_root: Path = APP_ROOT) -> tuple[Path, ...]:
    paths = [app_root.parent / "tools" / "feishu_sync" / "feishu_sync_config.json"]
    if app_root.parent.name == ".worktrees":
        paths.append(app_root.parents[2] / "tools" / "feishu_sync" / "feishu_sync_config.json")
    return tuple(paths)


def _client() -> FeishuClient:
    settings = get_settings()
    app_id, app_secret = settings.feishu_app_id, settings.feishu_app_secret
    if settings.env == "development" and (not app_id or not app_secret):
        for config_path in feishu_fallback_config_paths():
            if config_path.is_file():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                app_id = str(config.get("app_id") or "")
                app_secret = str(config.get("app_secret") or "")
                break
    return FeishuClient(app_id, app_secret)


def sync_channel_schedules(session: Session) -> dict[str, object]:
    settings = get_settings()
    client = _client()
    token, spreadsheet_token, sheets = client.workbook_sheets(
        settings.feishu_channel_schedule_wiki_token
    )
    directory_sheet_id = settings.feishu_channel_schedule_directory_sheet_id
    if not any(str(sheet.get("sheet_id") or "") == directory_sheet_id for sheet in sheets):
        raise FeishuSyncError("飞书频道排期工作簿缺少频道目录")
    directory_rows = client.rows_from_workbook(
        token,
        spreadsheet_token,
        directory_sheet_id,
        "D",
    )
    schedule_sheets = [
        (str(sheet.get("sheet_id") or ""), str(sheet.get("title") or "").strip())
        for sheet in sheets
        if str(sheet.get("sheet_id") or "") != directory_sheet_id
    ]
    if any(not sheet_id or not title for sheet_id, title in schedule_sheets):
        raise FeishuSyncError("飞书频道排期工作簿存在无标识或无标题的工作表")
    sheet_rows = [
        (
            sheet_id,
            title,
            client.rows_from_workbook(token, spreadsheet_token, sheet_id, "Z"),
        )
        for sheet_id, title in schedule_sheets
    ]
    rows_read = sum(len(rows) for _, _, rows in sheet_rows)
    started_at = datetime.now(timezone.utc)
    run = FeishuSyncRun(
        sync_type="channel_schedules",
        sheet_id=directory_sheet_id,
        environment=settings.env,
        device_key=settings.device_key or None,
        status="running",
        started_at=started_at,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    try:
        prepared, corrections = prepare_channel_schedule_rows(
            session,
            directory_rows=directory_rows,
            sheet_rows=sheet_rows,
        )
        synced_at = datetime.now(timezone.utc)
        counts = upsert_channel_schedule_rows(session, prepared, now=synced_at)
        completed_run = session.get(FeishuSyncRun, run.id)
        completed_run.status = "completed"
        completed_run.rows_read = rows_read
        completed_run.rows_inserted = counts["inserted"]
        completed_run.rows_updated = counts["updated"]
        completed_run.rows_skipped = counts["skipped"]
        completed_run.completed_at = synced_at
        session.commit()
        return {
            "sync_type": "channel_schedules",
            "environment": settings.env,
            "rows_read": rows_read,
            "rows_inserted": counts["inserted"],
            "rows_updated": counts["updated"],
            "rows_skipped": counts["skipped"],
            "sheets_read": len(schedule_sheets),
            "corrections": corrections,
            "latest_date": max((row["publish_date"] for row in prepared), default=None),
            "completed_at": synced_at,
        }
    except Exception as exc:
        session.rollback()
        failed_run = session.get(FeishuSyncRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.rows_read = rows_read
            failed_run.rows_inserted = counts["inserted"]
            failed_run.rows_updated = counts["updated"]
            failed_run.rows_skipped = counts["skipped"]
            failed_run.error_message = str(exc)[:2000]
            failed_run.completed_at = datetime.now(timezone.utc)
            session.commit()
        if isinstance(exc, FeishuSyncError):
            raise
        raise FeishuSyncError(f"频道排期同步写入失败：{exc}") from exc


def _client_rows(sheet_id: str, last_column: str) -> list[dict[str, str]]:
    settings = get_settings()
    return _client().rows(settings.feishu_wiki_token, sheet_id, last_column)


def sync_work_orders(session: Session) -> dict[str, object]:
    settings = get_settings()
    rows = _client_rows(settings.feishu_work_order_sheet_id, "F")
    return _sync_rows(session, "work_orders", rows, settings.feishu_work_order_sheet_id)


def sync_operation_packages(session: Session) -> dict[str, object]:
    settings = get_settings()
    rows = _client_rows(settings.feishu_operation_package_sheet_id, OPERATION_PACKAGE_LAST_COLUMN)
    return _sync_rows(session, "operation_packages", rows, settings.feishu_operation_package_sheet_id)


def new_drama_rows_in_insert_order(
    rows: list[tuple[int, str, dict[str, object]]],
) -> list[tuple[int, str, dict[str, object]]]:
    return list(reversed(rows))


def parse_operation_duration(value: str, *, row_number: int) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    parts = normalized.split(":")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise FeishuSyncError(f"飞书操作表第 {row_number} 行时长格式不正确：{value}")
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes >= 60 or seconds >= 60:
        raise FeishuSyncError(f"飞书操作表第 {row_number} 行时长格式不正确：{value}")
    return hours * 3600 + minutes * 60 + seconds


def sync_drama_operation_metadata(
    session: Session,
    *,
    now: datetime,
) -> dict[str, int]:
    settings = get_settings()
    _, matrix = _client().matrix_by_title(
        settings.feishu_drama_wiki_token,
        "操作表",
        "S",
    )
    if not matrix:
        raise FeishuSyncError("飞书操作表为空")
    header = [cell_text(value).strip() for value in matrix[0]]
    try:
        title_index = header.index("剧名")
        duration_index = header.index("时长")
        episode_index = header.index("集数")
    except ValueError as exc:
        raise FeishuSyncError("飞书操作表缺少剧名、时长或集数列") from exc

    prepared: list[tuple[str, int | None, int | None]] = []
    normalized_seen: dict[str, int] = {}
    rows_read = 0
    for row_number, row in enumerate(matrix[1:], start=2):
        title = cell_text(row[title_index] if title_index < len(row) else "").strip()
        if not title:
            continue
        rows_read += 1
        normalized_title = normalize_drama_title(title)
        previous_row = normalized_seen.get(normalized_title)
        if previous_row is not None:
            raise FeishuSyncError(
                f"飞书操作表第 {previous_row}、{row_number} 行剧名重复：{title}"
            )
        normalized_seen[normalized_title] = row_number
        duration_text = cell_text(
            row[duration_index] if duration_index < len(row) else ""
        )
        episode_text = cell_text(
            row[episode_index] if episode_index < len(row) else ""
        ).strip()
        if episode_text and not episode_text.isdigit():
            raise FeishuSyncError(
                f"飞书操作表第 {row_number} 行集数格式不正确：{episode_text}"
            )
        prepared.append((
            normalized_title,
            int(episode_text) if episode_text else None,
            parse_operation_duration(duration_text, row_number=row_number),
        ))

    dramas = {
        drama.normalized_title: drama
        for drama in session.scalars(
            select(Drama).where(Drama.normalized_title.in_(normalized_seen))
        )
    }
    states = {
        state.drama_id: state
        for state in session.scalars(
            select(DramaProductionState).where(
                DramaProductionState.drama_id.in_([drama.id for drama in dramas.values()])
            )
        )
    }
    inserted = updated = skipped = 0
    for normalized_title, episode_count, duration_seconds in prepared:
        drama = dramas.get(normalized_title)
        if drama is None or (episode_count is None and duration_seconds is None):
            skipped += 1
            continue
        state = states.get(drama.id)
        created = state is None
        if state is None:
            state = DramaProductionState(drama_id=drama.id)
            session.add(state)
            states[drama.id] = state
            inserted += 1
        changed = False
        if episode_count is not None and state.episode_count != episode_count:
            state.episode_count = episode_count
            changed = True
        if duration_seconds is not None and state.total_duration_seconds != duration_seconds:
            state.total_duration_seconds = duration_seconds
            changed = True
        if changed:
            state.source_synced_at = now
            if not created:
                updated += 1
        elif not created:
            skipped += 1

    return {
        "rows_read": rows_read,
        "rows_inserted": inserted,
        "rows_updated": updated,
        "rows_skipped": skipped,
    }


def sync_dramas(session: Session) -> dict[str, object]:
    settings = get_settings()
    sheet_id, rows = _client().rows_by_title(
        settings.feishu_drama_wiki_token,
        settings.feishu_drama_sheet_title,
        "I",
    )
    now = datetime.now(timezone.utc)
    run = FeishuSyncRun(
        sync_type="dramas",
        sheet_id=sheet_id,
        environment=settings.env,
        device_key=settings.device_key or None,
        status="running",
        started_at=now,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    inserted = updated = skipped = 0
    try:
        prepared = []
        normalized_seen: dict[str, int] = {}
        for row in rows:
            row_number = int(row.get("__source_row_number") or 0)
            title = row.get("作品名称", "").strip()
            if not title:
                raise FeishuSyncError(f"飞书剧库第 {row_number} 行缺少作品名称")
            normalized_title = normalize_drama_title(title)
            previous_row = normalized_seen.get(normalized_title)
            if previous_row is not None:
                raise FeishuSyncError(f"飞书剧库第 {previous_row}、{row_number} 行作品名称重复：{title}")
            normalized_seen[normalized_title] = row_number
            prepared.append((row_number, normalized_title, {
                "chinese_title": title,
                "normalized_title": normalized_title,
                "baidu_cloud_url": row.get("百度网盘链接", "").strip() or None,
                "content_summary": row.get("内容概述", "").strip() or None,
                "plot_archive": row.get("剧情档案", "").strip() or None,
                "plot_pattern": row.get("剧情套路", "").strip() or None,
                "core_personas": row.get("核心人设", "").strip() or None,
                "expires_at": parse_drama_expiry(row.get("到期时间", "")),
                "batch_name": row.get("批次", "").strip() or None,
                "status": map_drama_status(row.get("状态", "")),
                "source_type": "feishu",
                "source_sheet_id": sheet_id,
                "source_row_number": row_number,
            }))

        existing = {
            drama.normalized_title: drama
            for drama in session.scalars(select(Drama).where(Drama.normalized_title.in_(normalized_seen)))
        }
        aliases = set(session.scalars(select(DramaAlias.normalized_alias).where(DramaAlias.normalized_alias.in_(normalized_seen))))
        new_rows = []
        for row_number, normalized_title, values in prepared:
            drama = existing.get(normalized_title)
            if drama is None:
                if normalized_title in aliases:
                    raise FeishuSyncError(f"飞书剧库第 {row_number} 行作品名称与现有别名冲突：{values['chinese_title']}")
                new_rows.append((row_number, normalized_title, values))
                continue
            changed = False
            for field, value in values.items():
                if getattr(drama, field) != value:
                    setattr(drama, field, value)
                    changed = True
            if changed:
                drama.source_synced_at = now
                updated += 1
            else:
                skipped += 1

        for _, normalized_title, values in new_drama_rows_in_insert_order(new_rows):
            drama = Drama(
                drama_code=f"DRM-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
                source_synced_at=now,
                **values,
            )
            session.add(drama)
            existing[normalized_title] = drama
            inserted += 1

        session.flush()
        metadata = sync_drama_operation_metadata(session, now=now)

        run = session.get(FeishuSyncRun, run.id)
        run.status = "completed"
        run.rows_read = len(rows)
        run.rows_inserted = inserted
        run.rows_updated = updated
        run.rows_skipped = skipped
        run.completed_at = now
        session.commit()
        return {
            "sync_type": "dramas",
            "environment": settings.env,
            "rows_read": len(rows),
            "rows_inserted": inserted,
            "rows_updated": updated,
            "rows_skipped": skipped,
            "metadata_rows_read": metadata["rows_read"],
            "metadata_rows_inserted": metadata["rows_inserted"],
            "metadata_rows_updated": metadata["rows_updated"],
            "metadata_rows_skipped": metadata["rows_skipped"],
            "latest_date": None,
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
        raise FeishuSyncError(f"剧库同步写入失败：{exc}") from exc


def sync_drama_languages(session: Session) -> dict[str, object]:
    settings = get_settings()
    sheet_id, matrix = _client().matrix_by_title(settings.feishu_drama_wiki_token, "语言", "X")
    started_at = datetime.now(timezone.utc)
    run = FeishuSyncRun(
        sync_type="drama_languages",
        sheet_id=sheet_id,
        environment=settings.env,
        device_key=settings.device_key or None,
        status="running",
        started_at=started_at,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    inserted = updated = skipped = 0
    rows_read = max(len(matrix) - 2, 0)
    try:
        payload = parse_language_matrix(matrix)
        language_payloads = payload["languages"]
        drama_payloads = payload["dramas"]
        rows_read = len(drama_payloads)

        normalized_titles = {item["normalized_title"] for item in drama_payloads}
        dramas = {
            drama.normalized_title: drama
            for drama in session.scalars(select(Drama).where(Drama.normalized_title.in_(normalized_titles)))
        }
        missing = [item for item in drama_payloads if item["normalized_title"] not in dramas]
        if missing:
            first = missing[0]
            raise FeishuSyncError(
                f"飞书语言表第 {first['source_row_number']} 行剧目不在剧库中：{first['chinese_title']}"
            )

        existing_languages = {
            language.code: language
            for language in session.scalars(select(Language))
        }
        languages: dict[str, Language] = {}
        for values in language_payloads:
            code = values["code"]
            language = existing_languages.get(code)
            if language is None:
                language = Language(**values, status="active")
                session.add(language)
            else:
                for field, value in values.items():
                    setattr(language, field, value)
                language.status = "active"
            languages[code] = language
        session.flush()

        drama_ids = [drama.id for drama in dramas.values()]
        language_ids = [language.id for language in languages.values()]
        translations = {
            (translation.drama_id, translation.language_id): translation
            for translation in session.scalars(select(DramaTranslation).where(
                DramaTranslation.drama_id.in_(drama_ids),
                DramaTranslation.language_id.in_(language_ids),
            ))
        }
        synced_at = datetime.now(timezone.utc)
        for drama_values in drama_payloads:
            drama = dramas[drama_values["normalized_title"]]
            covered_codes = drama_values["covered_codes"]
            for code, language in languages.items():
                translation = translations.get((drama.id, language.id))
                if code in covered_codes:
                    if translation is None:
                        session.add(DramaTranslation(
                            drama_id=drama.id,
                            language_id=language.id,
                            translation_status="ready",
                            asset_status="ready",
                            source_type="feishu",
                            source_synced_at=synced_at,
                        ))
                        inserted += 1
                    elif translation.source_type == "manual":
                        skipped += 1
                    elif translation.source_type == "feishu":
                        if translation.translation_status != "ready" or translation.asset_status != "ready":
                            translation.translation_status = "ready"
                            translation.asset_status = "ready"
                            translation.source_synced_at = synced_at
                            updated += 1
                        else:
                            skipped += 1
                elif translation is not None and translation.source_type == "feishu":
                    session.delete(translation)
                    updated += 1
                elif translation is not None and translation.source_type == "manual":
                    skipped += 1

        completed_at = datetime.now(timezone.utc)
        run = session.get(FeishuSyncRun, run.id)
        run.status = "completed"
        run.rows_read = rows_read
        run.rows_inserted = inserted
        run.rows_updated = updated
        run.rows_skipped = skipped
        run.completed_at = completed_at
        session.commit()
        return {
            "sync_type": "drama_languages",
            "environment": settings.env,
            "rows_read": rows_read,
            "rows_inserted": inserted,
            "rows_updated": updated,
            "rows_skipped": skipped,
            "latest_date": None,
            "completed_at": completed_at,
        }
    except Exception as exc:
        session.rollback()
        failed_run = session.get(FeishuSyncRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.rows_read = rows_read
            failed_run.rows_inserted = inserted
            failed_run.rows_updated = updated
            failed_run.rows_skipped = skipped
            failed_run.error_message = str(exc)[:2000]
            failed_run.completed_at = datetime.now(timezone.utc)
            session.commit()
        if isinstance(exc, FeishuSyncError):
            raise
        raise FeishuSyncError(f"剧目语言同步写入失败：{exc}") from exc


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
            channel.chinese_meaning = master.get("中文含义") or None
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
