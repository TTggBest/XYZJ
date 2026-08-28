import csv
import io
import re
from datetime import datetime, time, timedelta, timezone
from math import ceil

from sqlalchemy import Integer, cast, distinct, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import (
    Channel,
    Drama,
    DramaAlias,
    DramaCoreTerm,
    DramaProductionState,
    DramaTranslation,
    Language,
    YoutubeVideo,
)
from zhiju.schemas.drama_library import (
    DramaLibraryBulkRequest,
    DramaLanguageCoverageUpdate,
    DramaLibraryUpdate,
    DramaLibraryWrite,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.drama_sequence import drama_sequence_subquery
from zhiju.services.drama_progress import production_state_payload
from zhiju.services.identity import ConflictError, _audit
from zhiju.services.operations import normalize_drama_title


def _summary(session: Session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=30)
    total, active, expiring, archived = session.execute(
        select(
            func.count(Drama.id),
            func.sum(cast(Drama.status == "active", Integer)),
            func.sum(cast(
                (Drama.status == "active")
                & Drama.expires_at.is_not(None)
                & (Drama.expires_at >= now)
                & (Drama.expires_at <= soon),
                Integer,
            )),
            func.sum(cast(Drama.status == "archived", Integer)),
        )
    ).one()
    return {
        "total": int(total or 0),
        "active": int(active or 0),
        "expiring": int(expiring or 0),
        "archived": int(archived or 0),
    }


def list_drama_library(
    session: Session,
    *,
    page: int,
    page_size: int,
    sort_order: str = "asc",
    search: str | None = None,
    status: str | None = None,
    batch_name: str | None = None,
    expires_from: datetime | None = None,
    expires_to: datetime | None = None,
) -> dict[str, object]:
    language_counts = (
        select(
            DramaTranslation.drama_id.label("drama_id"),
            func.count(DramaTranslation.id).label("language_count"),
        )
        .group_by(DramaTranslation.drama_id)
        .subquery()
    )
    channel_counts = (
        select(
            YoutubeVideo.drama_id.label("drama_id"),
            func.count(distinct(YoutubeVideo.channel_id)).label("published_channel_count"),
        )
        .where(YoutubeVideo.drama_id.is_not(None))
        .group_by(YoutubeVideo.drama_id)
        .subquery()
    )
    sequence_numbers = drama_sequence_subquery()
    filters = []
    if search:
        normalized = normalize_drama_title(search)
        filters.append(or_(Drama.normalized_title.contains(normalized), Drama.drama_code.contains(search.strip())))
    if status:
        filters.append(Drama.status == status)
    if batch_name:
        filters.append(Drama.batch_name == batch_name)
    if expires_from:
        filters.append(Drama.expires_at >= expires_from)
    if expires_to:
        filters.append(Drama.expires_at <= expires_to)

    total = int(session.scalar(select(func.count(Drama.id)).where(*filters)) or 0)
    statement = (
        select(
            Drama,
            sequence_numbers.c.sequence_number,
            func.coalesce(language_counts.c.language_count, 0),
            func.coalesce(channel_counts.c.published_channel_count, 0),
        )
        .join(sequence_numbers, sequence_numbers.c.drama_id == Drama.id)
        .outerjoin(language_counts, language_counts.c.drama_id == Drama.id)
        .outerjoin(channel_counts, channel_counts.c.drama_id == Drama.id)
        .where(*filters)
        .order_by(
            sequence_numbers.c.sequence_number.asc()
            if sort_order == "asc"
            else sequence_numbers.c.sequence_number.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        {
            **drama.__dict__,
            "sequence_number": int(sequence_number),
            "language_count": int(language_count),
            "published_channel_count": int(channel_count),
        }
        for drama, sequence_number, language_count, channel_count in session.execute(statement)
    ]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": ceil(total / page_size) if total else 0,
        "summary": _summary(session),
    }


def _require_drama(session: Session, drama_id: str) -> Drama:
    drama = session.get(Drama, drama_id)
    if drama is None:
        raise NotFoundError("剧目不存在")
    return drama


def get_drama_library_detail(session: Session, drama_id: str) -> dict[str, object]:
    drama = _require_drama(session, drama_id)
    aliases = list(session.scalars(select(DramaAlias).where(DramaAlias.drama_id == drama.id).order_by(DramaAlias.alias)))
    core_terms = list(session.scalars(select(DramaCoreTerm).where(DramaCoreTerm.drama_id == drama.id).order_by(DramaCoreTerm.term_type, DramaCoreTerm.term)))
    language_rows = session.execute(
        select(Language, DramaTranslation)
        .outerjoin(
            DramaTranslation,
            (DramaTranslation.language_id == Language.id) & (DramaTranslation.drama_id == drama.id),
        )
        .where(Language.status == "active")
        .order_by(Language.name_zh, Language.code)
    ).all()
    languages = [
        {
            "language_id": language.id,
            "language_code": language.code,
            "language_name_zh": language.name_zh,
            "priority_tier": language.priority_tier,
            "translated_title": translation.translated_title if translation else None,
            "translation_status": translation.translation_status if translation else "missing",
            "asset_status": translation.asset_status if translation else "missing",
            "source_type": translation.source_type if translation else None,
            "source_synced_at": translation.source_synced_at if translation else None,
        }
        for language, translation in language_rows
    ]
    channel_rows = session.execute(
        select(YoutubeVideo, Channel)
        .join(Channel, Channel.id == YoutubeVideo.channel_id)
        .where(YoutubeVideo.drama_id == drama.id)
        .order_by(YoutubeVideo.published_at.desc(), Channel.original_name)
    ).all()
    channels = [
        {
            "channel_id": channel.id,
            "channel_name": channel.original_name,
            "youtube_video_id": video.youtube_video_id,
            "video_title": video.title,
            "url": video.url,
            "publish_status": video.publish_status,
            "published_at": video.published_at,
        }
        for video, channel in channel_rows
    ]
    production_state = session.scalar(
        select(DramaProductionState).where(DramaProductionState.drama_id == drama.id)
    )
    return {
        **drama.__dict__,
        "aliases": aliases,
        "core_terms": core_terms,
        "languages": languages,
        "channels": channels,
        "production_state": production_state_payload(production_state, drama.id),
        "language_count": sum(item["translation_status"] != "missing" or item["asset_status"] != "missing" for item in languages),
        "published_channel_count": len({item["channel_id"] for item in channels}),
    }


def upsert_drama_language(
    session: Session,
    drama_id: str,
    language_id: str,
    payload: DramaLanguageCoverageUpdate,
) -> dict[str, object]:
    _require_drama(session, drama_id)
    language = session.get(Language, language_id)
    if language is None or language.status != "active":
        raise NotFoundError("语言不存在")
    translation = session.scalar(select(DramaTranslation).where(
        DramaTranslation.drama_id == drama_id,
        DramaTranslation.language_id == language_id,
    ))
    values = payload.model_dump()
    if translation is None:
        translation = DramaTranslation(
            drama_id=drama_id,
            language_id=language_id,
            source_type="manual",
            **values,
        )
        session.add(translation)
    else:
        for field, value in values.items():
            setattr(translation, field, value)
        translation.source_type = "manual"
        translation.source_synced_at = None
    _audit(session, "drama.language_updated", "drama", drama_id, f"language={language.code}")
    session.commit()
    return {
        "language_id": language.id,
        "language_code": language.code,
        "language_name_zh": language.name_zh,
        "priority_tier": language.priority_tier,
        "translated_title": translation.translated_title,
        "translation_status": translation.translation_status,
        "asset_status": translation.asset_status,
        "source_type": translation.source_type,
        "source_synced_at": translation.source_synced_at,
    }


def delete_drama_language(session: Session, drama_id: str, language_id: str) -> None:
    _require_drama(session, drama_id)
    language = session.get(Language, language_id)
    if language is None:
        raise NotFoundError("语言不存在")
    translation = session.scalar(select(DramaTranslation).where(
        DramaTranslation.drama_id == drama_id,
        DramaTranslation.language_id == language_id,
    ))
    if translation is not None:
        if translation.source_type != "manual":
            raise ConflictError("飞书同步的语言覆盖不能人工删除，请在飞书语言表修改")
        session.delete(translation)
        _audit(session, "drama.language_deleted", "drama", drama_id, f"language={language.code}")
        session.commit()


def _assert_title_available(session: Session, normalized_title: str, drama_id: str | None = None) -> None:
    drama_statement = select(Drama.id).where(Drama.normalized_title == normalized_title)
    alias_statement = select(DramaAlias.id).where(DramaAlias.normalized_alias == normalized_title)
    if drama_id:
        drama_statement = drama_statement.where(Drama.id != drama_id)
        alias_statement = alias_statement.where(DramaAlias.drama_id != drama_id)
    if session.scalar(drama_statement.limit(1)) or session.scalar(alias_statement.limit(1)):
        raise ConflictError("剧名或别名已存在于本地剧库")


def _apply_write(drama: Drama, payload: DramaLibraryWrite) -> bool:
    values = payload.model_dump()
    values["normalized_title"] = normalize_drama_title(payload.chinese_title)
    changed = False
    for field, value in values.items():
        if getattr(drama, field) != value:
            setattr(drama, field, value)
            changed = True
    return changed


def update_drama_library_item(
    session: Session,
    drama_id: str,
    payload: DramaLibraryUpdate,
) -> dict[str, object]:
    drama = _require_drama(session, drama_id)
    normalized = normalize_drama_title(payload.chinese_title)
    _assert_title_available(session, normalized, drama.id)
    _apply_write(drama, DramaLibraryWrite.model_validate(payload.model_dump(exclude={"aliases", "core_terms"})))
    if payload.aliases is not None:
        normalized_aliases = [(alias.strip(), normalize_drama_title(alias)) for alias in payload.aliases if alias.strip()]
        if len({normalized, *(value for _, value in normalized_aliases)}) != len(normalized_aliases) + 1:
            raise ConflictError("主剧名和别名存在重复")
        for _, normalized_alias in normalized_aliases:
            _assert_title_available(session, normalized_alias, drama.id)
        session.query(DramaAlias).filter(DramaAlias.drama_id == drama.id).delete()
        session.add_all(DramaAlias(drama_id=drama.id, alias=alias, normalized_alias=value, source="manual") for alias, value in normalized_aliases)
    if payload.core_terms is not None:
        session.query(DramaCoreTerm).filter(DramaCoreTerm.drama_id == drama.id).delete()
        session.add_all(DramaCoreTerm(drama_id=drama.id, **term.model_dump()) for term in payload.core_terms)
    _audit(session, "drama.updated", "drama", drama.id)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("剧目、别名或核心词数据冲突") from exc
    return get_drama_library_detail(session, drama.id)


def bulk_upsert_dramas(session: Session, payload: DramaLibraryBulkRequest) -> dict[str, object]:
    normalized_titles = [normalize_drama_title(row.chinese_title) for row in payload.rows]
    if len(set(normalized_titles)) != len(normalized_titles):
        raise ConflictError("批量数据中存在重复剧名")
    existing = {
        drama.normalized_title: drama
        for drama in session.scalars(select(Drama).where(Drama.normalized_title.in_(normalized_titles)))
    }
    results = []
    inserted = updated = skipped = 0
    for row_number, (row, normalized) in enumerate(zip(payload.rows, normalized_titles, strict=True), start=2):
        drama = existing.get(normalized)
        if drama is None:
            _assert_title_available(session, normalized)
            drama = Drama(
                drama_code=f"DRM-{datetime.now(timezone.utc):%Y%m%d}-{__import__('uuid').uuid4().hex[:8].upper()}",
                normalized_title=normalized,
                source_type="manual",
                **row.model_dump(),
            )
            session.add(drama)
            session.flush()
            inserted += 1
            action = "inserted"
        elif _apply_write(drama, row):
            updated += 1
            action = "updated"
        else:
            skipped += 1
            action = "skipped"
        results.append({"row_number": row_number, "chinese_title": row.chinese_title, "action": action, "drama_id": drama.id})
    try:
        _audit(session, "drama.bulk_upserted", "drama", "bulk", f"rows={len(payload.rows)}")
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("批量剧目数据冲突") from exc
    return {
        "rows_read": len(payload.rows),
        "rows_inserted": inserted,
        "rows_updated": updated,
        "rows_skipped": skipped,
        "rows_conflicted": 0,
        "results": results,
    }


def parse_drama_csv(content: str) -> DramaLibraryBulkRequest:
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames or "作品名称" not in reader.fieldnames:
        raise ConflictError("CSV 缺少必要列：作品名称")
    rows = []
    for row_number, row in enumerate(reader, start=2):
        title = (row.get("作品名称") or "").strip()
        if not title:
            raise ConflictError(f"CSV 第 {row_number} 行缺少作品名称")
        expiry_text = (row.get("到期时间") or "").strip()
        expires_at = None
        if expiry_text:
            normalized = re.sub(r"\D", "", expiry_text)
            if len(normalized) < 8:
                raise ConflictError(f"CSV 第 {row_number} 行到期时间格式不正确")
            expires_at = datetime.combine(
                datetime.strptime(normalized[:8], "%Y%m%d").date(),
                time(23, 59, 59),
            )
        source_status = (row.get("状态") or "").strip()
        status_map = {"": "active", "制作": "active", "已删": "archived", "启用": "active", "到期": "expired", "禁用": "blocked", "归档": "archived"}
        status = status_map.get(source_status, source_status)
        if status not in {"active", "expired", "blocked", "archived"}:
            raise ConflictError(f"CSV 第 {row_number} 行状态不正确：{source_status}")
        rows.append(DramaLibraryWrite(
            chinese_title=title,
            baidu_cloud_url=(row.get("百度网盘链接") or "").strip() or None,
            content_summary=(row.get("内容概述") or "").strip() or None,
            plot_archive=(row.get("剧情档案") or "").strip() or None,
            plot_pattern=(row.get("剧情套路") or "").strip() or None,
            core_personas=(row.get("核心人设") or "").strip() or None,
            expires_at=expires_at,
            batch_name=(row.get("批次") or "").strip() or None,
            status=status,
        ))
    if not rows:
        raise ConflictError("CSV 没有可录入的数据")
    return DramaLibraryBulkRequest(rows=rows)
