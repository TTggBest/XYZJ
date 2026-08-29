import re
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import (
    Channel,
    ChannelCommunitySlot,
    ChannelPlaylist,
    ChannelPublishSlot,
    ChannelScheduleEntry,
    Drama,
    DramaAlias,
    DramaCoreTerm,
    DramaProductionState,
    DramaTranslation,
    Language,
    OperationTask,
    PublishCadenceTemplateSlot,
    ScheduleCandidate,
    ScheduleChangeHistory,
    SystemEvent,
    WorkOrder,
)
from zhiju.schemas.operations import (
    CommunitySlotCreate,
    CadenceTemplateUpdate,
    DramaCreate,
    DramaTranslationUpsert,
    LanguageCreate,
    PlaylistCreate,
    PlaylistUpdate,
    PublishSlotCreate,
    ScheduleCandidateCreate,
    ScheduleCreate,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError, _audit


def normalize_drama_title(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _drama_payload(session: Session, drama: Drama) -> dict[str, object]:
    aliases = list(session.scalars(select(DramaAlias).where(DramaAlias.drama_id == drama.id).order_by(DramaAlias.alias)))
    terms = list(
        session.scalars(
            select(DramaCoreTerm)
            .where(DramaCoreTerm.drama_id == drama.id)
            .order_by(DramaCoreTerm.term_type, DramaCoreTerm.weight.desc(), DramaCoreTerm.term)
        )
    )
    return {**drama.__dict__, "aliases": aliases, "core_terms": terms}


def create_drama(session: Session, payload: DramaCreate) -> dict[str, object]:
    normalized_title = normalize_drama_title(payload.chinese_title)
    aliases = [(alias.strip(), normalize_drama_title(alias)) for alias in payload.aliases if alias.strip()]
    normalized_values = {normalized_title, *(item[1] for item in aliases)}
    if len(normalized_values) != len(aliases) + 1:
        raise ConflictError("主剧名和别名存在重复")
    existing = session.scalar(
        select(Drama.id).where(
            or_(Drama.normalized_title.in_(normalized_values))
        ).limit(1)
    )
    alias_existing = session.scalar(
        select(DramaAlias.id).where(DramaAlias.normalized_alias.in_(normalized_values)).limit(1)
    )
    if existing or alias_existing:
        raise ConflictError("剧名或别名已存在于本地剧库")
    drama = Drama(
        drama_code=f"DRM-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
        chinese_title=payload.chinese_title.strip(),
        normalized_title=normalized_title,
        **payload.model_dump(exclude={"chinese_title", "aliases", "core_terms"}),
    )
    session.add(drama)
    try:
        session.flush()
        session.add_all(
            [DramaAlias(drama_id=drama.id, alias=alias, normalized_alias=normalized, source="manual") for alias, normalized in aliases]
        )
        session.add_all([DramaCoreTerm(drama_id=drama.id, **term.model_dump()) for term in payload.core_terms])
        _audit(session, "drama.created", "drama", drama.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("剧目、别名或核心词数据冲突") from exc
    session.refresh(drama)
    return _drama_payload(session, drama)


def list_dramas(session: Session) -> list[dict[str, object]]:
    dramas = list(session.scalars(select(Drama).order_by(Drama.created_at.desc())))
    return [_drama_payload(session, drama) for drama in dramas]


SCHEDULABLE_PRODUCTION_FIELDS = (
    "cloud_download_status",
    "parameter_normalization_status",
    "youtube_upload_status",
    "copyright_verification_status",
    "subtitle_extraction_status",
    "guishou_upload_status",
    "role_extraction_status",
    "tts_status",
    "production_completion_status",
)


def _is_schedulable_drama(drama: Drama, production_state: DramaProductionState | None) -> bool:
    expires_at = drama.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return bool(
        drama.status == "active"
        and (expires_at is None or expires_at > datetime.now(timezone.utc))
        and production_state is not None
        and not production_state.is_production_excluded
        and all(getattr(production_state, field) == "completed" for field in SCHEDULABLE_PRODUCTION_FIELDS)
    )


def list_schedulable_dramas(session: Session) -> list[dict[str, object]]:
    rows = session.execute(
        select(Drama, DramaProductionState)
        .join(DramaProductionState, DramaProductionState.drama_id == Drama.id)
        .where(
            Drama.status == "active",
            DramaProductionState.is_production_excluded.is_(False),
            *(getattr(DramaProductionState, field) == "completed" for field in SCHEDULABLE_PRODUCTION_FIELDS),
        )
        .order_by(Drama.drama_number)
    ).all()
    return [_drama_payload(session, drama) for drama, state in rows if _is_schedulable_drama(drama, state)]


def _require_schedulable_drama(session: Session, drama_id: str, *, missing_message: str = "剧目不存在") -> Drama:
    drama = session.get(Drama, drama_id)
    if drama is None:
        raise NotFoundError(missing_message)
    production_state = session.scalar(
        select(DramaProductionState).where(DramaProductionState.drama_id == drama.id)
    )
    if not _is_schedulable_drama(drama, production_state):
        raise ConflictError("只有制剧全部完成且未标记不制作的剧目才能排期")
    return drama


def match_drama(session: Session, title: str) -> dict[str, object] | None:
    normalized = normalize_drama_title(title)
    drama = session.scalar(select(Drama).where(Drama.normalized_title == normalized))
    if drama is None:
        drama = session.scalar(
            select(Drama).join(DramaAlias, DramaAlias.drama_id == Drama.id).where(DramaAlias.normalized_alias == normalized)
        )
    return _drama_payload(session, drama) if drama else None


def create_language(session: Session, payload: LanguageCreate) -> Language:
    language = Language(code=payload.code.lower(), name_zh=payload.name_zh.strip(), native_name=payload.native_name)
    session.add(language)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("语言代码已存在") from exc
    session.refresh(language)
    return language


def list_languages(session: Session) -> list[Language]:
    return list(session.scalars(select(Language).where(Language.status == "active").order_by(Language.code)))


def _translation_payload(
    translation: DramaTranslation,
    drama: Drama,
    language: Language,
) -> dict[str, object]:
    return {
        **translation.__dict__,
        "drama_code": drama.drama_code,
        "chinese_title": drama.chinese_title,
        "language_code": language.code,
        "language_name_zh": language.name_zh,
    }


def upsert_drama_translation(
    session: Session,
    drama_id: str,
    language_id: str,
    payload: DramaTranslationUpsert,
) -> dict[str, object]:
    drama = session.get(Drama, drama_id)
    if drama is None:
        raise NotFoundError("剧目不存在")
    language = session.get(Language, language_id)
    if language is None:
        raise NotFoundError("语言不存在")
    if language.status != "active":
        raise ConflictError("停用语言不能登记剧目翻译")
    translation = session.scalar(
        select(DramaTranslation)
        .where(
            DramaTranslation.drama_id == drama_id,
            DramaTranslation.language_id == language_id,
        )
        .with_for_update()
    )
    old_status = None
    values = payload.model_dump(exclude={"reason"})
    if translation is None:
        translation = DramaTranslation(
            drama_id=drama_id,
            language_id=language_id,
            **values,
        )
        session.add(translation)
        action = "drama_translation.created"
    else:
        old_status = f"{translation.translation_status}/{translation.asset_status}"
        for field, value in values.items():
            setattr(translation, field, value)
        action = "drama_translation.updated"
    new_status = f"{translation.translation_status}/{translation.asset_status}"
    try:
        session.flush()
        if old_status != new_status:
            session.add(
                SystemEvent(
                    entity_type="drama_translation",
                    entity_id=translation.id,
                    old_status=old_status,
                    new_status=new_status,
                    reason=payload.reason,
                    actor_type="system",
                    occurred_at=datetime.now(timezone.utc),
                )
            )
        _audit(session, action, "drama_translation", translation.id, payload.reason)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("剧目与语言翻译关系冲突") from exc
    session.refresh(translation)
    return _translation_payload(translation, drama, language)


def list_drama_translations(
    session: Session,
    *,
    drama_id: str | None = None,
    language_id: str | None = None,
    translation_status: str | None = None,
    asset_status: str | None = None,
) -> list[dict[str, object]]:
    if drama_id and session.get(Drama, drama_id) is None:
        raise NotFoundError("剧目不存在")
    statement = (
        select(DramaTranslation, Drama, Language)
        .join(Drama, Drama.id == DramaTranslation.drama_id)
        .join(Language, Language.id == DramaTranslation.language_id)
    )
    if drama_id:
        statement = statement.where(DramaTranslation.drama_id == drama_id)
    if language_id:
        statement = statement.where(DramaTranslation.language_id == language_id)
    if translation_status:
        statement = statement.where(DramaTranslation.translation_status == translation_status)
    if asset_status:
        statement = statement.where(DramaTranslation.asset_status == asset_status)
    rows = session.execute(
        statement.order_by(Drama.chinese_title, Language.code)
    ).all()
    return [
        _translation_payload(translation, drama, language)
        for translation, drama, language in rows
    ]


def list_drama_translation_matrix(
    session: Session,
    *,
    drama_status: str | None = None,
    language_codes: list[str] | None = None,
    include_inactive_languages: bool = False,
) -> list[dict[str, object]]:
    drama_statement = select(Drama)
    if drama_status:
        drama_statement = drama_statement.where(Drama.status == drama_status)
    dramas = list(
        session.scalars(
            drama_statement.order_by(Drama.chinese_title, Drama.drama_code)
        )
    )

    language_statement = select(Language)
    if not include_inactive_languages:
        language_statement = language_statement.where(Language.status == "active")
    normalized_codes = sorted(
        {code.strip().lower() for code in language_codes or [] if code.strip()}
    )
    if normalized_codes:
        language_statement = language_statement.where(Language.code.in_(normalized_codes))
    languages = list(
        session.scalars(language_statement.order_by(Language.code, Language.name_zh))
    )

    drama_ids = [drama.id for drama in dramas]
    language_ids = [language.id for language in languages]
    translation_rows = (
        list(
            session.scalars(
                select(DramaTranslation).where(
                    DramaTranslation.drama_id.in_(drama_ids),
                    DramaTranslation.language_id.in_(language_ids),
                )
            )
        )
        if drama_ids and language_ids
        else []
    )
    translations = {
        (translation.drama_id, translation.language_id): translation
        for translation in translation_rows
    }

    result = []
    for drama in dramas:
        cells = []
        for language in languages:
            translation = translations.get((drama.id, language.id))
            cells.append(
                {
                    "language_id": language.id,
                    "language_code": language.code,
                    "language_name_zh": language.name_zh,
                    "language_native_name": language.native_name,
                    "language_status": language.status,
                    "translation_id": translation.id if translation else None,
                    "translated_title": translation.translated_title if translation else None,
                    "translation_status": translation.translation_status if translation else "missing",
                    "asset_status": translation.asset_status if translation else "missing",
                    "resource_uri": translation.resource_uri if translation else None,
                    "created_at": translation.created_at if translation else None,
                    "updated_at": translation.updated_at if translation else None,
                }
            )
        result.append(
            {
                "drama_id": drama.id,
                "drama_code": drama.drama_code,
                "chinese_title": drama.chinese_title,
                "drama_status": drama.status,
                "drama_resource_url": drama.baidu_cloud_url,
                "language_count": len(cells),
                "translation_ready_count": sum(
                    cell["translation_status"] == "ready" for cell in cells
                ),
                "asset_ready_count": sum(
                    cell["asset_status"] == "ready" for cell in cells
                ),
                "cells": cells,
                "created_at": drama.created_at,
                "updated_at": drama.updated_at,
            }
        )
    return result


def _active_channel(session: Session, channel_id: str, *, lock: bool = False) -> Channel:
    statement = select(Channel).where(Channel.id == channel_id, Channel.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    channel = session.scalar(statement)
    if channel is None:
        raise NotFoundError("频道不存在")
    if channel.status in {"paused", "archived", "deleted"}:
        raise ConflictError("暂停、归档或删除的频道不能建立新运营计划")
    return channel


def create_playlist(session: Session, channel_id: str, payload: PlaylistCreate) -> ChannelPlaylist:
    _active_channel(session, channel_id)
    playlist = ChannelPlaylist(channel_id=channel_id, **payload.model_dump())
    session.add(playlist)
    try:
        session.flush()
        _audit(session, "playlist.created", "channel_playlist", playlist.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("频道内播放列表名称或YouTube播放列表ID重复") from exc
    session.refresh(playlist)
    return playlist


def list_playlists(session: Session, channel_id: str) -> list[ChannelPlaylist]:
    _active_channel(session, channel_id)
    return list(
        session.scalars(
            select(ChannelPlaylist)
            .where(ChannelPlaylist.channel_id == channel_id, ChannelPlaylist.status != "deleted")
            .order_by(ChannelPlaylist.sort_order, ChannelPlaylist.created_at)
        )
    )


def update_playlist(
    session: Session,
    channel_id: str,
    playlist_id: str,
    payload: PlaylistUpdate,
) -> ChannelPlaylist:
    _active_channel(session, channel_id, lock=True)
    playlist = session.scalar(
        select(ChannelPlaylist)
        .where(
            ChannelPlaylist.id == playlist_id,
            ChannelPlaylist.channel_id == channel_id,
            ChannelPlaylist.status != "deleted",
        )
        .with_for_update()
    )
    if playlist is None:
        raise NotFoundError("播放列表不存在")
    values = payload.model_dump(exclude_unset=True)
    if values.get("url") and "youtube_playlist_id" not in values:
        match = re.search(r"[?&]list=([^&]+)", values["url"])
        if match:
            values["youtube_playlist_id"] = match.group(1)
    for field, value in values.items():
        setattr(playlist, field, value)
    try:
        session.flush()
        _audit(session, "playlist.updated", "channel_playlist", playlist.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("频道内播放列表名称或YouTube播放列表ID重复") from exc
    session.refresh(playlist)
    return playlist


def create_publish_slot(session: Session, channel_id: str, payload: PublishSlotCreate) -> ChannelPublishSlot:
    channel = _active_channel(session, channel_id)
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConflictError("不是有效的IANA时区") from exc
    if payload.timezone != channel.timezone:
        raise ConflictError("发布时间档位时区必须与频道时区一致")
    slot = ChannelPublishSlot(channel_id=channel_id, **payload.model_dump())
    session.add(slot)
    try:
        session.flush()
        _audit(session, "publish_slot.created", "channel_publish_slot", slot.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("相同频道档位已经存在") from exc
    session.refresh(slot)
    return slot


def list_publish_slots(session: Session, channel_id: str) -> list[ChannelPublishSlot]:
    _active_channel(session, channel_id)
    return list(
        session.scalars(
            select(ChannelPublishSlot)
            .where(ChannelPublishSlot.channel_id == channel_id, ChannelPublishSlot.status != "archived")
            .order_by(ChannelPublishSlot.slot_type, ChannelPublishSlot.slot_number)
        )
    )


def list_publish_slot_overview(session: Session) -> list[dict[str, object]]:
    channels = list(
        session.scalars(
            select(Channel)
            .where(Channel.deleted_at.is_(None))
            .order_by(Channel.operational_name, Channel.original_name)
        )
    )
    slots = list(
        session.scalars(
            select(ChannelPublishSlot)
            .where(ChannelPublishSlot.status != "archived")
        )
    )
    slots_by_channel: dict[str, list[ChannelPublishSlot]] = {}
    for slot in slots:
        slots_by_channel.setdefault(slot.channel_id, []).append(slot)
    for channel_slots in slots_by_channel.values():
        channel_slots.sort(
            key=lambda slot: (
                0 if slot.slot_type == "main" else 1,
                slot.slot_number,
                slot.local_time,
            )
        )
    return [
        {
            "channel_id": channel.id,
            "youtube_channel_id": channel.youtube_channel_id,
            "original_name": channel.original_name,
            "operational_name": channel.operational_name,
            "display_name": channel.operational_name or channel.original_name,
            "timezone": channel.timezone,
            "daily_publish_count": channel.daily_publish_count,
            "channel_status": channel.status,
            "slots": slots_by_channel.get(channel.id, []),
        }
        for channel in channels
    ]


def build_cadence_time_projection(
    *,
    on_date: date,
    local_video_time: time,
    channel_timezone: str,
    engagement_offset_minutes: int,
) -> dict[str, object]:
    try:
        local_zone = ZoneInfo(channel_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConflictError("频道时区不是有效的IANA时区") from exc
    local_video_at = datetime.combine(on_date, local_video_time, tzinfo=local_zone)
    local_engagement_at = local_video_at + timedelta(minutes=engagement_offset_minutes)
    beijing_zone = ZoneInfo("Asia/Shanghai")
    beijing_video_at = local_video_at.astimezone(beijing_zone)
    beijing_engagement_at = local_engagement_at.astimezone(beijing_zone)
    return {
        "local_video_date": local_video_at.date(),
        "local_video_time": local_video_at.strftime("%H:%M"),
        "beijing_video_date": beijing_video_at.date(),
        "beijing_video_time": beijing_video_at.strftime("%H:%M"),
        "local_engagement_date": local_engagement_at.date(),
        "local_engagement_time": local_engagement_at.strftime("%H:%M"),
        "beijing_engagement_date": beijing_engagement_at.date(),
        "beijing_engagement_time": beijing_engagement_at.strftime("%H:%M"),
    }


def list_cadence_templates(session: Session) -> list[dict[str, object]]:
    slots = list(
        session.scalars(
            select(PublishCadenceTemplateSlot).order_by(
                PublishCadenceTemplateSlot.daily_publish_count,
                PublishCadenceTemplateSlot.slot_number,
            )
        )
    )
    grouped = {count: [] for count in range(1, 6)}
    for slot in slots:
        grouped[slot.daily_publish_count].append(slot)
    return [
        {"daily_publish_count": count, "slots": grouped[count]}
        for count in range(1, 6)
    ]


def replace_cadence_template(
    session: Session,
    daily_publish_count: int,
    payload: CadenceTemplateUpdate,
) -> dict[str, object]:
    if daily_publish_count not in range(1, 6):
        raise ConflictError("只支持1更、2更、3更、4更或5更模板")
    if len(payload.slots) != daily_publish_count:
        raise ConflictError(f"{daily_publish_count}更模板必须包含{daily_publish_count}个档位")
    numbers = {slot.slot_number for slot in payload.slots}
    if numbers != set(range(1, daily_publish_count + 1)):
        raise ConflictError("档位序号必须从1开始连续排列")
    if sum(slot.slot_type == "main" for slot in payload.slots) != 1:
        raise ConflictError("每套档期模板必须且只能有一个主档")
    existing = list(
        session.scalars(
            select(PublishCadenceTemplateSlot).where(
                PublishCadenceTemplateSlot.daily_publish_count == daily_publish_count
            )
        )
    )
    by_number = {slot.slot_number: slot for slot in existing}
    for slot_input in payload.slots:
        slot = by_number.pop(slot_input.slot_number, None)
        if slot is None:
            slot = PublishCadenceTemplateSlot(
                daily_publish_count=daily_publish_count,
                **slot_input.model_dump(),
            )
            session.add(slot)
        else:
            for key, value in slot_input.model_dump().items():
                setattr(slot, key, value)
    for slot in by_number.values():
        session.delete(slot)
    _audit(
        session,
        "cadence_template.updated",
        "publish_cadence_template",
        str(daily_publish_count),
    )
    session.commit()
    return next(
        template
        for template in list_cadence_templates(session)
        if template["daily_publish_count"] == daily_publish_count
    )


def update_channel_cadence(
    session: Session,
    channel_id: str,
    daily_publish_count: int,
) -> Channel:
    channel = _active_channel(session, channel_id)
    template_exists = session.scalar(
        select(PublishCadenceTemplateSlot.id).where(
            PublishCadenceTemplateSlot.daily_publish_count == daily_publish_count
        ).limit(1)
    )
    if template_exists is None:
        raise ConflictError("对应日更模板尚未配置")
    channel.daily_publish_count = daily_publish_count
    _audit(session, "channel.cadence_updated", "channel", channel.id)
    session.commit()
    session.refresh(channel)
    return channel


def list_cadence_overview(
    session: Session,
    *,
    on_date: date,
) -> list[dict[str, object]]:
    channels = list(
        session.scalars(
            select(Channel)
            .where(Channel.deleted_at.is_(None))
            .order_by(
                Channel.country_name_zh,
                Channel.display_order,
                Channel.operational_name,
                Channel.original_name,
            )
        )
    )
    template_slots = list(
        session.scalars(
            select(PublishCadenceTemplateSlot).order_by(
                PublishCadenceTemplateSlot.daily_publish_count,
                PublishCadenceTemplateSlot.slot_number,
            )
        )
    )
    by_count: dict[int, list[PublishCadenceTemplateSlot]] = {}
    for slot in template_slots:
        by_count.setdefault(slot.daily_publish_count, []).append(slot)
    result = []
    for channel in channels:
        projections = []
        for slot in by_count.get(channel.daily_publish_count, []):
            projections.append(
                {
                    "template_slot_id": slot.id,
                    "slot_number": slot.slot_number,
                    "slot_type": slot.slot_type,
                    "engagement_offset_minutes": slot.engagement_offset_minutes,
                    **build_cadence_time_projection(
                        on_date=on_date,
                        local_video_time=slot.local_video_time,
                        channel_timezone=channel.timezone,
                        engagement_offset_minutes=slot.engagement_offset_minutes,
                    ),
                }
            )
        result.append(
            {
                "channel_id": channel.id,
                "youtube_channel_id": channel.youtube_channel_id,
                "original_name": channel.original_name,
                "operational_name": channel.operational_name,
                "display_name": channel.operational_name or channel.original_name,
                "country_code": channel.country_code,
                "country_name_zh": channel.country_name_zh,
                "default_language": channel.default_language,
                "timezone": channel.timezone,
                "daily_publish_count": channel.daily_publish_count,
                "channel_status": channel.status,
                "slots": projections,
            }
        )
    return result


def update_publish_slot(
    session: Session,
    channel_id: str,
    publish_slot_id: str,
    payload: PublishSlotCreate,
) -> ChannelPublishSlot:
    channel = _active_channel(session, channel_id)
    slot = session.scalar(
        select(ChannelPublishSlot).where(
            ChannelPublishSlot.id == publish_slot_id,
            ChannelPublishSlot.channel_id == channel_id,
        )
    )
    if slot is None:
        raise NotFoundError("频道档期不存在")
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConflictError("不是有效的IANA时区") from exc
    if payload.timezone != channel.timezone:
        raise ConflictError("发布时间档位时区必须与频道时区一致")
    for key, value in payload.model_dump().items():
        setattr(slot, key, value)
    try:
        session.flush()
        _audit(session, "publish_slot.updated", "channel_publish_slot", slot.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("相同频道档位已经存在") from exc
    session.refresh(slot)
    return slot


COMMUNITY_SLOT_TRANSITIONS = {
    "active": {"inactive", "archived"},
    "inactive": {"active", "archived"},
    "archived": set(),
}


def create_community_slot(
    session: Session,
    channel_id: str,
    payload: CommunitySlotCreate,
) -> ChannelCommunitySlot:
    channel = _active_channel(session, channel_id)
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConflictError("不是有效的IANA时区") from exc
    if payload.timezone != channel.timezone:
        raise ConflictError("Community档位时区必须与频道时区一致")
    if payload.schedule_mode == "relative":
        publish_slot = session.get(ChannelPublishSlot, payload.publish_slot_id)
        if (
            publish_slot is None
            or publish_slot.channel_id != channel_id
            or publish_slot.status != "active"
        ):
            raise ConflictError("相对模式的视频发布时间档位无效或不属于当前频道")
        if publish_slot.timezone != payload.timezone:
            raise ConflictError("Community档位与视频档位时区不一致")
    slot = ChannelCommunitySlot(channel_id=channel_id, **payload.model_dump())
    session.add(slot)
    try:
        session.flush()
        _audit(session, "community_slot.created", "channel_community_slot", slot.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("相同Community发布时间规则已经存在") from exc
    session.refresh(slot)
    return slot


def list_community_slots(
    session: Session,
    channel_id: str,
    *,
    include_archived: bool = False,
) -> list[ChannelCommunitySlot]:
    if session.get(Channel, channel_id) is None:
        raise NotFoundError("频道不存在")
    statement = select(ChannelCommunitySlot).where(
        ChannelCommunitySlot.channel_id == channel_id
    )
    if not include_archived:
        statement = statement.where(ChannelCommunitySlot.status != "archived")
    return list(
        session.scalars(
            statement.order_by(
                ChannelCommunitySlot.schedule_mode,
                ChannelCommunitySlot.local_time,
                ChannelCommunitySlot.offset_minutes,
                ChannelCommunitySlot.created_at,
            )
        )
    )


def change_community_slot_status(
    session: Session,
    community_slot_id: str,
    new_status: str,
    reason: str,
) -> ChannelCommunitySlot:
    slot = session.scalar(
        select(ChannelCommunitySlot)
        .where(ChannelCommunitySlot.id == community_slot_id)
        .with_for_update()
    )
    if slot is None:
        raise NotFoundError("Community发布时间规则不存在")
    _active_channel(session, slot.channel_id)
    if new_status not in COMMUNITY_SLOT_TRANSITIONS.get(slot.status, set()):
        raise ConflictError(f"Community档位不能从 {slot.status} 变更为 {new_status}")
    old_status = slot.status
    slot.status = new_status
    session.add(
        SystemEvent(
            entity_type="channel_community_slot",
            entity_id=slot.id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            actor_type="system",
            occurred_at=datetime.now(timezone.utc),
        )
    )
    _audit(session, "community_slot.status_changed", "channel_community_slot", slot.id, reason)
    session.commit()
    session.refresh(slot)
    return slot


def create_schedule(session: Session, channel_id: str, payload: ScheduleCreate) -> ChannelScheduleEntry:
    existing = session.scalar(
        select(ChannelScheduleEntry).where(ChannelScheduleEntry.idempotency_key == payload.idempotency_key)
    )
    if existing is not None:
        if existing.channel_id != channel_id:
            raise ConflictError("幂等键已被其他频道使用")
        return existing
    _active_channel(session, channel_id, lock=True)
    drama = _require_schedulable_drama(session, payload.drama_id)
    slot = session.get(ChannelPublishSlot, payload.publish_slot_id)
    if slot is None or slot.channel_id != channel_id or slot.status != "active":
        raise ConflictError("发布时间档位无效或不属于当前频道")
    if payload.playlist_id:
        playlist = session.get(ChannelPlaylist, payload.playlist_id)
        if playlist is None or playlist.channel_id != channel_id or playlist.status not in {"draft", "active"}:
            raise ConflictError("播放列表无效或不属于当前频道")
    local_zone = ZoneInfo(slot.timezone)
    local_aware = datetime.combine(payload.publish_date, slot.local_time, tzinfo=local_zone)
    utc_aware = local_aware.astimezone(timezone.utc)
    beijing_aware = utc_aware.astimezone(ZoneInfo("Asia/Shanghai"))
    schedule = ChannelScheduleEntry(
        channel_id=channel_id,
        **payload.model_dump(),
        planned_local_time=local_aware.replace(tzinfo=None),
        planned_beijing_time=beijing_aware.replace(tzinfo=None),
        planned_utc_time=utc_aware.replace(tzinfo=None),
        status="planned",
    )
    session.add(schedule)
    try:
        session.flush()
        session.add(
            ScheduleCandidate(
                schedule_id=schedule.id,
                drama_id=schedule.drama_id,
                candidate_type="primary",
                rank_number=1,
                reason="创建排期时采用的主选剧目",
                status="selected",
            )
        )
        session.add(
            ScheduleChangeHistory(
                schedule_id=schedule.id,
                new_drama_id=schedule.drama_id,
                new_planned_utc_time=schedule.planned_utc_time,
                new_status="planned",
                reason="创建排期",
                actor_type="system",
                changed_at=datetime.now(timezone.utc),
            )
        )
        _audit(session, "schedule.created", "channel_schedule_entry", schedule.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该频道日期档位已有排期") from exc
    session.refresh(schedule)
    return schedule


def list_schedule_overview(
    session: Session,
    *,
    channel_id: str | None = None,
    publish_date_from=None,
    publish_date_to=None,
    status: str | None = None,
    has_task: bool | None = None,
) -> list[dict[str, object]]:
    statement = (
        select(
            ChannelScheduleEntry,
            Channel,
            Drama,
            ChannelPublishSlot,
            ChannelPlaylist,
            OperationTask,
            WorkOrder,
        )
        .join(Channel, Channel.id == ChannelScheduleEntry.channel_id)
        .join(Drama, Drama.id == ChannelScheduleEntry.drama_id)
        .join(ChannelPublishSlot, ChannelPublishSlot.id == ChannelScheduleEntry.publish_slot_id)
        .outerjoin(ChannelPlaylist, ChannelPlaylist.id == ChannelScheduleEntry.playlist_id)
        .outerjoin(OperationTask, OperationTask.schedule_id == ChannelScheduleEntry.id)
        .outerjoin(WorkOrder, WorkOrder.task_id == OperationTask.id)
    )
    if channel_id:
        statement = statement.where(ChannelScheduleEntry.channel_id == channel_id)
    if publish_date_from:
        statement = statement.where(ChannelScheduleEntry.publish_date >= publish_date_from)
    if publish_date_to:
        statement = statement.where(ChannelScheduleEntry.publish_date <= publish_date_to)
    if status:
        statement = statement.where(ChannelScheduleEntry.status == status)
    if has_task is True:
        statement = statement.where(OperationTask.id.is_not(None))
    elif has_task is False:
        statement = statement.where(OperationTask.id.is_(None))
    rows = list(
        session.execute(
            statement.order_by(
                ChannelScheduleEntry.publish_date,
                ChannelScheduleEntry.planned_utc_time,
                ChannelScheduleEntry.priority,
                ChannelScheduleEntry.created_at,
            )
        )
    )
    schedule_ids = [schedule.id for schedule, *_ in rows]
    candidate_rows = (
        list(
            session.scalars(
                select(ScheduleCandidate)
                .where(ScheduleCandidate.schedule_id.in_(schedule_ids))
                .order_by(ScheduleCandidate.schedule_id, ScheduleCandidate.rank_number)
            )
        )
        if schedule_ids
        else []
    )
    candidates_by_schedule: dict[str, list[ScheduleCandidate]] = {}
    for candidate in candidate_rows:
        candidates_by_schedule.setdefault(candidate.schedule_id, []).append(candidate)

    result = []
    for schedule, channel, drama, slot, playlist, task, work_order in rows:
        candidates = candidates_by_schedule.get(schedule.id, [])
        selected = next((candidate for candidate in candidates if candidate.status == "selected"), None)
        result.append(
            {
                "schedule_id": schedule.id,
                "publish_date": schedule.publish_date,
                "channel_id": channel.id,
                "youtube_channel_id": channel.youtube_channel_id,
                "channel_name": channel.operational_name or channel.original_name,
                "channel_original_name": channel.original_name,
                "channel_timezone": channel.timezone,
                "drama_id": drama.id,
                "drama_code": drama.drama_code,
                "chinese_title": drama.chinese_title,
                "drama_resource_url": drama.baidu_cloud_url,
                "publish_slot_id": slot.id,
                "slot_type": slot.slot_type,
                "slot_number": slot.slot_number,
                "slot_local_time": slot.local_time,
                "planned_local_time": schedule.planned_local_time,
                "planned_beijing_time": schedule.planned_beijing_time,
                "planned_utc_time": schedule.planned_utc_time,
                "playlist_id": playlist.id if playlist else None,
                "playlist_name": playlist.local_name if playlist else None,
                "playlist_url": playlist.url if playlist else None,
                "community_count": schedule.community_count,
                "priority": schedule.priority,
                "schedule_status": schedule.status,
                "candidate_count": len(candidates),
                "available_candidate_count": sum(
                    candidate.status == "available" for candidate in candidates
                ),
                "selected_candidate_id": selected.id if selected else None,
                "task_id": task.id if task else None,
                "task_status": task.status if task else None,
                "work_order_id": work_order.id if work_order else None,
                "work_order_status": work_order.status if work_order else None,
                "replaced_by_schedule_id": schedule.replaced_by_schedule_id,
                "created_at": schedule.created_at,
                "updated_at": schedule.updated_at,
            }
        )
    return result


def list_channel_schedule_page(
    session: Session,
    *,
    channel_id: str,
    query: str | None = None,
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, object]:
    filters = [ChannelScheduleEntry.channel_id == channel_id]
    normalized_query = (query or "").strip()
    if normalized_query:
        filters.append(or_(
            Drama.chinese_title.contains(normalized_query),
            Drama.drama_code.contains(normalized_query),
            ChannelScheduleEntry.source_video_id.contains(normalized_query),
        ))
    total = session.scalar(
        select(func.count(ChannelScheduleEntry.id))
        .join(Drama, Drama.id == ChannelScheduleEntry.drama_id)
        .where(*filters)
    ) or 0
    order_columns = (
        ChannelScheduleEntry.planned_beijing_time,
        ChannelScheduleEntry.created_at,
    )
    if sort_order == "desc":
        ordering = tuple(column.desc() for column in order_columns)
    else:
        ordering = order_columns
    statement = (
        select(
            ChannelScheduleEntry,
            Channel,
            Drama,
            ChannelPublishSlot,
            OperationTask,
        )
        .join(Channel, Channel.id == ChannelScheduleEntry.channel_id)
        .join(Drama, Drama.id == ChannelScheduleEntry.drama_id)
        .join(ChannelPublishSlot, ChannelPublishSlot.id == ChannelScheduleEntry.publish_slot_id)
        .outerjoin(OperationTask, OperationTask.schedule_id == ChannelScheduleEntry.id)
        .where(*filters)
        .order_by(*ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for schedule, channel, drama, slot, task in session.execute(statement):
        items.append({
            "schedule_id": schedule.id,
            "channel_id": channel.id,
            "channel_name": channel.operational_name or channel.original_name,
            "channel_timezone": channel.timezone,
            "drama_id": drama.id,
            "drama_code": drama.drama_code,
            "chinese_title": drama.chinese_title,
            "publish_date": schedule.publish_date,
            "planned_local_time": schedule.planned_local_time,
            "planned_beijing_time": schedule.planned_beijing_time,
            "slot_type": slot.slot_type,
            "slot_number": slot.slot_number,
            "schedule_status": schedule.status,
            "source_type": schedule.source_type,
            "source_sheet_id": schedule.source_sheet_id,
            "source_row_number": schedule.source_row_number,
            "source_synced_at": schedule.source_synced_at,
            "source_video_id": schedule.source_video_id,
            "source_video_url": schedule.source_video_url,
            "is_uploaded": schedule.is_uploaded,
            "is_published": schedule.is_published,
            "is_task_written": schedule.is_task_written,
            "task_id": task.id if task else None,
            "task_status": task.status if task else None,
        })
    return {"page": page, "page_size": page_size, "total": total, "items": items}


def _candidate_payload(
    candidate: ScheduleCandidate,
    drama: Drama,
) -> dict[str, object]:
    return {
        **candidate.__dict__,
        "drama_code": drama.drama_code,
        "chinese_title": drama.chinese_title,
    }


def _require_open_schedule(session: Session, schedule_id: str) -> ChannelScheduleEntry:
    schedule = session.scalar(
        select(ChannelScheduleEntry)
        .where(ChannelScheduleEntry.id == schedule_id)
        .with_for_update()
    )
    if schedule is None:
        raise NotFoundError("排期不存在")
    if schedule.status not in {"planned", "reserved", "confirmed"}:
        raise ConflictError("只有未发布且未取消的排期可以管理候选剧目")
    _active_channel(session, schedule.channel_id)
    if session.scalar(
        select(OperationTask.id)
        .where(OperationTask.schedule_id == schedule.id)
        .limit(1)
    ):
        raise ConflictError("排期已经生成任务，不能再调整候选或替换剧目")
    return schedule


def create_schedule_candidate(
    session: Session,
    schedule_id: str,
    payload: ScheduleCandidateCreate,
) -> dict[str, object]:
    _require_open_schedule(session, schedule_id)
    drama = _require_schedulable_drama(
        session,
        payload.drama_id,
        missing_message="候选剧目不存在",
    )
    candidate = ScheduleCandidate(
        schedule_id=schedule_id,
        drama_id=payload.drama_id,
        candidate_type="backup",
        rank_number=payload.rank_number,
        score=payload.score,
        reason=payload.reason,
        status="available",
    )
    session.add(candidate)
    try:
        session.flush()
        _audit(session, "schedule_candidate.created", "schedule_candidate", candidate.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("候选剧目或候选排序已经存在") from exc
    session.refresh(candidate)
    return _candidate_payload(candidate, drama)


def list_schedule_candidates(
    session: Session,
    schedule_id: str,
) -> list[dict[str, object]]:
    if session.get(ChannelScheduleEntry, schedule_id) is None:
        raise NotFoundError("排期不存在")
    rows = session.execute(
        select(ScheduleCandidate, Drama)
        .join(Drama, Drama.id == ScheduleCandidate.drama_id)
        .where(ScheduleCandidate.schedule_id == schedule_id)
        .order_by(ScheduleCandidate.rank_number)
    ).all()
    return [_candidate_payload(candidate, drama) for candidate, drama in rows]


def select_schedule_candidate(
    session: Session,
    schedule_id: str,
    candidate_id: str,
    reason: str,
) -> ChannelScheduleEntry:
    schedule = _require_open_schedule(session, schedule_id)
    candidates = list(
        session.scalars(
            select(ScheduleCandidate)
            .where(ScheduleCandidate.schedule_id == schedule_id)
            .with_for_update()
        )
    )
    selected = next((item for item in candidates if item.id == candidate_id), None)
    if selected is None:
        raise NotFoundError("排期候选剧目不存在")
    if selected.status != "available":
        raise ConflictError("只有可用候选剧目可以被选择")
    drama = _require_schedulable_drama(
        session,
        selected.drama_id,
        missing_message="候选剧目不存在",
    )
    now = datetime.now(timezone.utc)
    previous = next((item for item in candidates if item.status == "selected"), None)
    old_drama_id = schedule.drama_id
    if previous is not None:
        previous.status = "available"
        session.add(
            SystemEvent(
                entity_type="schedule_candidate",
                entity_id=previous.id,
                old_status="selected",
                new_status="available",
                reason=reason,
                actor_type="system",
                occurred_at=now,
            )
        )
    selected.status = "selected"
    schedule.drama_id = selected.drama_id
    session.add(
        SystemEvent(
            entity_type="schedule_candidate",
            entity_id=selected.id,
            old_status="available",
            new_status="selected",
            reason=reason,
            actor_type="system",
            occurred_at=now,
        )
    )
    session.add(
        ScheduleChangeHistory(
            schedule_id=schedule.id,
            old_drama_id=old_drama_id,
            new_drama_id=schedule.drama_id,
            old_planned_utc_time=schedule.planned_utc_time,
            new_planned_utc_time=schedule.planned_utc_time,
            old_status=schedule.status,
            new_status=schedule.status,
            reason=reason,
            actor_type="system",
            changed_at=now,
        )
    )
    _audit(session, "schedule.candidate_selected", "channel_schedule_entry", schedule.id, reason)
    session.commit()
    session.refresh(schedule)
    return schedule


def list_schedules(
    session: Session,
    *,
    channel_id: str | None = None,
    publish_date_from=None,
    publish_date_to=None,
    status: str | None = None,
) -> list[ChannelScheduleEntry]:
    statement = select(ChannelScheduleEntry)
    if channel_id:
        statement = statement.where(ChannelScheduleEntry.channel_id == channel_id)
    if publish_date_from:
        statement = statement.where(ChannelScheduleEntry.publish_date >= publish_date_from)
    if publish_date_to:
        statement = statement.where(ChannelScheduleEntry.publish_date <= publish_date_to)
    if status:
        statement = statement.where(ChannelScheduleEntry.status == status)
    return list(
        session.scalars(statement.order_by(ChannelScheduleEntry.publish_date, ChannelScheduleEntry.planned_utc_time))
    )


ALLOWED_SCHEDULE_TRANSITIONS = {
    "planned": {"reserved", "confirmed", "cancelled"},
    "reserved": {"confirmed", "cancelled"},
    "confirmed": {"cancelled", "published"},
}


def change_schedule_status(
    session: Session, schedule_id: str, new_status: str, reason: str
) -> ChannelScheduleEntry:
    schedule = session.scalar(
        select(ChannelScheduleEntry).where(ChannelScheduleEntry.id == schedule_id).with_for_update()
    )
    if schedule is None:
        raise NotFoundError("排期不存在")
    if new_status not in ALLOWED_SCHEDULE_TRANSITIONS.get(schedule.status, set()):
        raise ConflictError(f"排期不能从 {schedule.status} 变更为 {new_status}")
    old_status = schedule.status
    schedule.status = new_status
    session.add(
        ScheduleChangeHistory(
            schedule_id=schedule.id,
            old_drama_id=schedule.drama_id,
            new_drama_id=schedule.drama_id,
            old_planned_utc_time=schedule.planned_utc_time,
            new_planned_utc_time=schedule.planned_utc_time,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            actor_type="system",
            changed_at=datetime.now(timezone.utc),
        )
    )
    _audit(session, "schedule.status_changed", "channel_schedule_entry", schedule.id)
    session.commit()
    session.refresh(schedule)
    return schedule
