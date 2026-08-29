from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.channel import (
    ChannelAnalysisReportCreate,
    ChannelAnalysisReportDetailRead,
    ChannelDetailRead,
    ChannelDnaVersionCreate,
    ChannelDnaVersionRead,
    ChannelHubUpdate,
    ChannelKeywordCreate,
    ChannelKeywordRead,
    ChannelPinnedCommentTemplateCreate,
    ChannelPinnedCommentTemplateRead,
    ChannelProfileRead,
    ChannelProfileUpsert,
    MediaAssetCreate,
    MediaAssetMetadataUpdate,
    MediaAssetRead,
    MediaAssetStatusChange,
)
from zhiju.services.channel import (
    NotFoundError,
    add_keyword,
    activate_pinned_comment_template,
    create_pinned_comment_template,
    create_dna_version,
    create_report,
    get_channel_detail,
    get_report_detail,
    get_media_asset,
    list_dna_versions,
    list_pinned_comment_templates,
    list_reports,
    list_media_assets,
    register_media_asset,
    update_media_asset_metadata,
    change_media_asset_status,
    delete_media_asset,
    upsert_profile,
    update_channel_hub,
)
from zhiju.services.identity import ConflictError


router = APIRouter(prefix="/v3", tags=["channel-center"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/channels/{channel_id}", response_model=ChannelDetailRead)
def get_channel(channel_id: str, session: Session = Depends(get_db)) -> ChannelDetailRead:
    try:
        return get_channel_detail(session, channel_id)
    except NotFoundError as exc:
        raise _http_error(exc) from exc


@router.put("/channels/{channel_id}/hub", response_model=ChannelDetailRead)
def put_channel_hub(
    channel_id: str, payload: ChannelHubUpdate, session: Session = Depends(get_db)
) -> ChannelDetailRead:
    try:
        return update_channel_hub(session, channel_id, payload)
    except NotFoundError as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/channels/{channel_id}/profile", response_model=ChannelProfileRead)
def put_channel_profile(
    channel_id: str, payload: ChannelProfileUpsert, session: Session = Depends(get_db)
) -> ChannelProfileRead:
    try:
        return upsert_profile(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/channels/{channel_id}/keywords",
    response_model=ChannelKeywordRead,
    status_code=status.HTTP_201_CREATED,
)
def post_channel_keyword(
    channel_id: str, payload: ChannelKeywordCreate, session: Session = Depends(get_db)
) -> ChannelKeywordRead:
    try:
        return add_keyword(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/channels/{channel_id}/pinned-comment-templates",
    response_model=list[ChannelPinnedCommentTemplateRead],
)
def get_pinned_comment_templates(
    channel_id: str,
    language: str | None = None,
    template_status: str | None = Query(default=None, alias="status"),
    session: Session = Depends(get_db),
) -> list[ChannelPinnedCommentTemplateRead]:
    try:
        return list_pinned_comment_templates(
            session,
            channel_id,
            language=language,
            status=template_status,
        )
    except NotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/channels/{channel_id}/pinned-comment-templates",
    response_model=ChannelPinnedCommentTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
def post_pinned_comment_template(
    channel_id: str,
    payload: ChannelPinnedCommentTemplateCreate,
    session: Session = Depends(get_db),
) -> ChannelPinnedCommentTemplateRead:
    try:
        return create_pinned_comment_template(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/channels/{channel_id}/pinned-comment-templates/{template_id}/activate",
    response_model=ChannelPinnedCommentTemplateRead,
)
def post_activate_pinned_comment_template(
    channel_id: str,
    template_id: str,
    session: Session = Depends(get_db),
) -> ChannelPinnedCommentTemplateRead:
    try:
        return activate_pinned_comment_template(session, channel_id, template_id)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/channels/{channel_id}/analysis-reports",
    response_model=ChannelAnalysisReportDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def post_analysis_report(
    channel_id: str,
    payload: ChannelAnalysisReportCreate,
    session: Session = Depends(get_db),
) -> ChannelAnalysisReportDetailRead:
    try:
        return create_report(session, channel_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/channels/{channel_id}/analysis-reports",
    response_model=list[ChannelAnalysisReportDetailRead],
)
def get_analysis_reports(
    channel_id: str, session: Session = Depends(get_db)
) -> list[ChannelAnalysisReportDetailRead]:
    try:
        return list_reports(session, channel_id)
    except NotFoundError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/channels/{channel_id}/analysis-reports/{report_id}",
    response_model=ChannelAnalysisReportDetailRead,
)
def get_analysis_report(
    channel_id: str, report_id: str, session: Session = Depends(get_db)
) -> ChannelAnalysisReportDetailRead:
    try:
        return get_report_detail(session, channel_id, report_id)
    except NotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/channels/{channel_id}/dna-versions", response_model=list[ChannelDnaVersionRead])
def get_dna_versions(channel_id: str, session: Session = Depends(get_db)) -> list[ChannelDnaVersionRead]:
    try:
        return list_dna_versions(session, channel_id)
    except NotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/channels/{channel_id}/dna-versions",
    response_model=ChannelDnaVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def post_dna_version(
    channel_id: str,
    payload: ChannelDnaVersionCreate,
    session: Session = Depends(get_db),
) -> ChannelDnaVersionRead:
    try:
        version, signals = create_dna_version(session, channel_id, payload)
        return {**version.__dict__, "signals": signals}
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.post("/media-assets", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
def post_media_asset(payload: MediaAssetCreate, session: Session = Depends(get_db)) -> MediaAssetRead:
    try:
        return register_media_asset(session, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.get("/media-assets", response_model=list[MediaAssetRead])
def get_media_assets(
    channel_id: str | None = None,
    operation_package_id: str | None = None,
    asset_type: str | None = None,
    asset_role: str | None = None,
    asset_status: str | None = Query(default=None, alias="status"),
    sha256: str | None = Query(default=None, pattern=r"^[0-9a-fA-F]{64}$"),
    include_deleted: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_db),
) -> list[MediaAssetRead]:
    return list_media_assets(
        session,
        channel_id=channel_id,
        operation_package_id=operation_package_id,
        asset_type=asset_type,
        asset_role=asset_role,
        status=asset_status,
        sha256=sha256,
        include_deleted=include_deleted,
        limit=limit,
    )


@router.get("/media-assets/{asset_id}", response_model=MediaAssetRead)
def get_media_asset_detail(
    asset_id: str, session: Session = Depends(get_db)
) -> MediaAssetRead:
    try:
        return get_media_asset(session, asset_id)
    except NotFoundError as exc:
        raise _http_error(exc) from exc


@router.patch("/media-assets/{asset_id}", response_model=MediaAssetRead)
def patch_media_asset_metadata(
    asset_id: str,
    payload: MediaAssetMetadataUpdate,
    session: Session = Depends(get_db),
) -> MediaAssetRead:
    try:
        return update_media_asset_metadata(session, asset_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.patch("/media-assets/{asset_id}/status", response_model=MediaAssetRead)
def patch_media_asset_status(
    asset_id: str,
    payload: MediaAssetStatusChange,
    session: Session = Depends(get_db),
) -> MediaAssetRead:
    try:
        return change_media_asset_status(session, asset_id, payload)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc


@router.delete("/media-assets/{asset_id}", response_model=MediaAssetRead)
def delete_media_asset_record(
    asset_id: str, session: Session = Depends(get_db)
) -> MediaAssetRead:
    try:
        return delete_media_asset(session, asset_id)
    except (NotFoundError, ConflictError) as exc:
        raise _http_error(exc) from exc
