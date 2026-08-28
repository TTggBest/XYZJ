from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.operations import (
    CadenceTemplateRead,
    CadenceTemplateUpdate,
    ChannelCadenceOverview,
    ChannelCadenceUpdate,
    ChannelSchedulePage,
    CommunitySlotCreate,
    CommunitySlotRead,
    CommunitySlotStatusChange,
    DramaCreate,
    DramaRead,
    DramaTranslationRead,
    DramaTranslationMatrixRow,
    DramaTranslationUpsert,
    LanguageCreate,
    LanguageRead,
    PlaylistCreate,
    PlaylistRead,
    PublishSlotChannelOverview,
    PublishSlotCreate,
    PublishSlotRead,
    ScheduleCreate,
    ScheduleOverview,
    ScheduleCandidateCreate,
    ScheduleCandidateRead,
    ScheduleCandidateSelect,
    ScheduleRead,
    ScheduleStatusChange,
)
from zhiju.services.channel import NotFoundError
from zhiju.services.identity import ConflictError
from zhiju.services.operations import (
    change_community_slot_status,
    change_schedule_status,
    create_community_slot,
    create_drama,
    create_language,
    create_playlist,
    create_publish_slot,
    create_schedule,
    create_schedule_candidate,
    list_community_slots,
    list_cadence_overview,
    list_cadence_templates,
    list_dramas,
    list_drama_translations,
    list_drama_translation_matrix,
    list_languages,
    list_playlists,
    list_publish_slot_overview,
    list_publish_slots,
    list_schedulable_dramas,
    list_schedules,
    list_schedule_overview,
    list_channel_schedule_page,
    list_schedule_candidates,
    match_drama,
    select_schedule_candidate,
    replace_cadence_template,
    update_channel_cadence,
    upsert_drama_translation,
    update_publish_slot,
)


router = APIRouter(prefix="/v3", tags=["operations"])


def _raise(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, NotFoundError) else 409, detail=str(exc))


@router.get("/cadence-templates", response_model=list[CadenceTemplateRead])
def get_cadence_templates(session: Session = Depends(get_db)) -> list[CadenceTemplateRead]:
    return list_cadence_templates(session)


@router.put(
    "/cadence-templates/{daily_publish_count}",
    response_model=CadenceTemplateRead,
)
def put_cadence_template(
    daily_publish_count: int,
    payload: CadenceTemplateUpdate,
    session: Session = Depends(get_db),
) -> CadenceTemplateRead:
    try:
        return replace_cadence_template(session, daily_publish_count, payload)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.patch("/channels/{channel_id}/cadence", response_model=dict)
def patch_channel_cadence(
    channel_id: str,
    payload: ChannelCadenceUpdate,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        channel = update_channel_cadence(
            session,
            channel_id,
            payload.daily_publish_count,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc
    return {
        "channel_id": channel.id,
        "daily_publish_count": channel.daily_publish_count,
    }


@router.get("/cadence-overview", response_model=list[ChannelCadenceOverview])
def get_cadence_overview(
    on_date: date,
    session: Session = Depends(get_db),
) -> list[ChannelCadenceOverview]:
    try:
        return list_cadence_overview(session, on_date=on_date)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.get("/dramas", response_model=list[DramaRead])
def get_dramas(session: Session = Depends(get_db)) -> list[DramaRead]:
    return list_dramas(session)


@router.post("/dramas", response_model=DramaRead, status_code=status.HTTP_201_CREATED)
def post_drama(payload: DramaCreate, session: Session = Depends(get_db)) -> DramaRead:
    try:
        return create_drama(session, payload)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.get("/dramas/match", response_model=DramaRead | None)
def get_drama_match(title: str = Query(min_length=1), session: Session = Depends(get_db)) -> DramaRead | None:
    return match_drama(session, title)


@router.get(
    "/dramas/{drama_id}/translations",
    response_model=list[DramaTranslationRead],
)
def get_drama_translations(
    drama_id: str,
    session: Session = Depends(get_db),
) -> list[DramaTranslationRead]:
    try:
        return list_drama_translations(session, drama_id=drama_id)
    except NotFoundError as exc:
        raise _raise(exc) from exc


@router.put(
    "/dramas/{drama_id}/translations/{language_id}",
    response_model=DramaTranslationRead,
)
def put_drama_translation(
    drama_id: str,
    language_id: str,
    payload: DramaTranslationUpsert,
    session: Session = Depends(get_db),
) -> DramaTranslationRead:
    try:
        return upsert_drama_translation(
            session,
            drama_id,
            language_id,
            payload,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/drama-translations", response_model=list[DramaTranslationRead])
def get_translation_matrix(
    language_id: str | None = None,
    translation_status: str | None = None,
    asset_status: str | None = None,
    session: Session = Depends(get_db),
) -> list[DramaTranslationRead]:
    return list_drama_translations(
        session,
        language_id=language_id,
        translation_status=translation_status,
        asset_status=asset_status,
    )


@router.get(
    "/drama-translations/matrix",
    response_model=list[DramaTranslationMatrixRow],
)
def get_translation_matrix_view(
    drama_status: str | None = None,
    language_code: list[str] | None = Query(default=None),
    include_inactive_languages: bool = False,
    session: Session = Depends(get_db),
) -> list[DramaTranslationMatrixRow]:
    return list_drama_translation_matrix(
        session,
        drama_status=drama_status,
        language_codes=language_code,
        include_inactive_languages=include_inactive_languages,
    )


@router.get("/languages", response_model=list[LanguageRead])
def get_languages(session: Session = Depends(get_db)) -> list[LanguageRead]:
    return list_languages(session)


@router.post("/languages", response_model=LanguageRead, status_code=status.HTTP_201_CREATED)
def post_language(payload: LanguageCreate, session: Session = Depends(get_db)) -> LanguageRead:
    try:
        return create_language(session, payload)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.get("/channels/{channel_id}/playlists", response_model=list[PlaylistRead])
def get_playlists(channel_id: str, session: Session = Depends(get_db)) -> list[PlaylistRead]:
    try:
        return list_playlists(session, channel_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/channels/{channel_id}/playlists",
    response_model=PlaylistRead,
    status_code=status.HTTP_201_CREATED,
)
def post_playlist(channel_id: str, payload: PlaylistCreate, session: Session = Depends(get_db)) -> PlaylistRead:
    try:
        return create_playlist(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/channels/{channel_id}/publish-slots", response_model=list[PublishSlotRead])
def get_publish_slots(channel_id: str, session: Session = Depends(get_db)) -> list[PublishSlotRead]:
    try:
        return list_publish_slots(session, channel_id)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/publish-slots/overview",
    response_model=list[PublishSlotChannelOverview],
)
def get_publish_slot_overview(
    session: Session = Depends(get_db),
) -> list[PublishSlotChannelOverview]:
    return list_publish_slot_overview(session)


@router.post(
    "/channels/{channel_id}/publish-slots",
    response_model=PublishSlotRead,
    status_code=status.HTTP_201_CREATED,
)
def post_publish_slot(
    channel_id: str, payload: PublishSlotCreate, session: Session = Depends(get_db)
) -> PublishSlotRead:
    try:
        return create_publish_slot(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch(
    "/channels/{channel_id}/publish-slots/{publish_slot_id}",
    response_model=PublishSlotRead,
)
def patch_publish_slot(
    channel_id: str,
    publish_slot_id: str,
    payload: PublishSlotCreate,
    session: Session = Depends(get_db),
) -> PublishSlotRead:
    try:
        return update_publish_slot(session, channel_id, publish_slot_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/channels/{channel_id}/community-slots",
    response_model=list[CommunitySlotRead],
)
def get_community_slots(
    channel_id: str,
    include_archived: bool = False,
    session: Session = Depends(get_db),
) -> list[CommunitySlotRead]:
    try:
        return list_community_slots(
            session,
            channel_id,
            include_archived=include_archived,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/channels/{channel_id}/community-slots",
    response_model=CommunitySlotRead,
    status_code=status.HTTP_201_CREATED,
)
def post_community_slot(
    channel_id: str,
    payload: CommunitySlotCreate,
    session: Session = Depends(get_db),
) -> CommunitySlotRead:
    try:
        return create_community_slot(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch(
    "/community-slots/{community_slot_id}/status",
    response_model=CommunitySlotRead,
)
def patch_community_slot_status(
    community_slot_id: str,
    payload: CommunitySlotStatusChange,
    session: Session = Depends(get_db),
) -> CommunitySlotRead:
    try:
        return change_community_slot_status(
            session,
            community_slot_id,
            payload.status,
            payload.reason,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get("/schedules", response_model=list[ScheduleRead])
def get_schedules(
    channel_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    schedule_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> list[ScheduleRead]:
    return list_schedules(
        session,
        channel_id=channel_id,
        publish_date_from=date_from,
        publish_date_to=date_to,
        status=schedule_status,
    )


@router.get("/schedules/eligible-dramas", response_model=list[DramaRead])
def get_schedulable_dramas(session: Session = Depends(get_db)) -> list[DramaRead]:
    return list_schedulable_dramas(session)


@router.get("/schedules/channel-view", response_model=ChannelSchedulePage)
def get_channel_schedule_page(
    channel_id: str,
    query: str | None = None,
    sort_order: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50),
    session: Session = Depends(get_db),
) -> ChannelSchedulePage:
    if page_size not in {50, 100, 150}:
        raise HTTPException(
            status_code=422,
            detail="每页条数仅支持 50、100、150",
        )
    return list_channel_schedule_page(
        session,
        channel_id=channel_id,
        query=query,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get("/schedules/overview", response_model=list[ScheduleOverview])
def get_schedule_overview(
    channel_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    schedule_status: str | None = Query(default=None, alias="status"),
    has_task: bool | None = None,
    session: Session = Depends(get_db),
) -> list[ScheduleOverview]:
    return list_schedule_overview(
        session,
        channel_id=channel_id,
        publish_date_from=date_from,
        publish_date_to=date_to,
        status=schedule_status,
        has_task=has_task,
    )


@router.post(
    "/channels/{channel_id}/schedules",
    response_model=ScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def post_schedule(channel_id: str, payload: ScheduleCreate, session: Session = Depends(get_db)) -> ScheduleRead:
    try:
        return create_schedule(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.patch("/schedules/{schedule_id}/status", response_model=ScheduleRead)
def patch_schedule_status(
    schedule_id: str,
    payload: ScheduleStatusChange,
    session: Session = Depends(get_db),
) -> ScheduleRead:
    try:
        return change_schedule_status(session, schedule_id, payload.status, payload.reason)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/schedules/{schedule_id}/candidates",
    response_model=list[ScheduleCandidateRead],
)
def get_schedule_candidates(
    schedule_id: str,
    session: Session = Depends(get_db),
) -> list[ScheduleCandidateRead]:
    try:
        return list_schedule_candidates(session, schedule_id)
    except NotFoundError as exc:
        raise _raise(exc) from exc


@router.post(
    "/schedules/{schedule_id}/candidates",
    response_model=ScheduleCandidateRead,
    status_code=status.HTTP_201_CREATED,
)
def post_schedule_candidate(
    schedule_id: str,
    payload: ScheduleCandidateCreate,
    session: Session = Depends(get_db),
) -> ScheduleCandidateRead:
    try:
        return create_schedule_candidate(session, schedule_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/schedules/{schedule_id}/candidates/{candidate_id}/select",
    response_model=ScheduleRead,
)
def post_select_schedule_candidate(
    schedule_id: str,
    candidate_id: str,
    payload: ScheduleCandidateSelect,
    session: Session = Depends(get_db),
) -> ScheduleRead:
    try:
        return select_schedule_candidate(
            session,
            schedule_id,
            candidate_id,
            payload.reason,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc
    create_community_slot,
    list_community_slots,
