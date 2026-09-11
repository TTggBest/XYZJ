from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.image_processing import (
    ChannelLogoProfileRead,
    ImageAssetReconcileRead,
    ImageProcessingBatchRead,
    ImageProcessingRunPageRead,
    ImageProcessingRunRead,
    ImageWorkspaceRead,
    ImageWorkspaceWrite,
    MediaAssetContextRead,
    MediaAssetCoverageRead,
)
from zhiju.services.image_processing import (
    generate_logos,
    get_workspace,
    import_images,
    list_media_asset_contexts,
    list_batch_media_coverage,
    list_channel_logo_profiles,
    list_processing_batches,
    list_processing_run_page,
    list_processing_runs,
    reconcile_processing_assets,
    reveal_media_asset_folder,
    render_media_asset_thumbnail,
    resolve_media_asset_file,
    save_channel_logo_profile,
    save_workspace,
)


router = APIRouter(prefix="/v3", tags=["image-processing"])


@router.get("/settings/image-workspace", response_model=ImageWorkspaceRead | None)
def get_image_workspace(session: Session = Depends(get_db)) -> ImageWorkspaceRead | None:
    try:
        return get_workspace(session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/settings/image-workspace", response_model=ImageWorkspaceRead)
def put_image_workspace(payload: ImageWorkspaceWrite, session: Session = Depends(get_db)) -> ImageWorkspaceRead:
    try:
        return save_workspace(session, payload.root_path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/channels/logo-profiles", response_model=list[ChannelLogoProfileRead])
def get_logo_profiles(session: Session = Depends(get_db)) -> list[ChannelLogoProfileRead]:
    return list_channel_logo_profiles(session)


@router.put("/channels/{channel_id}/logo-profile", response_model=ChannelLogoProfileRead)
async def put_logo_profile(
    channel_id: str,
    left_logo: UploadFile = File(...),
    right_logo: UploadFile = File(...),
    template: UploadFile = File(...),
    session: Session = Depends(get_db),
) -> ChannelLogoProfileRead:
    try:
        return save_channel_logo_profile(
            session,
            channel_id,
            left_logo.filename or "left-logo",
            await left_logo.read(),
            right_logo.filename or "right-logo",
            await right_logo.read(),
            template.filename or "tem",
            await template.read(),
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/image-processing/batches", response_model=list[ImageProcessingBatchRead])
def get_processing_batches(session: Session = Depends(get_db)) -> list[ImageProcessingBatchRead]:
    return list_processing_batches(session)


@router.get(
    "/image-processing/batches/{batch_id}/asset-coverage",
    response_model=list[MediaAssetCoverageRead],
)
def get_batch_asset_coverage(
    batch_id: str, session: Session = Depends(get_db)
) -> list[MediaAssetCoverageRead]:
    try:
        return list_batch_media_coverage(session, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/image-processing/runs", response_model=list[ImageProcessingRunRead])
def get_image_processing_runs(session: Session = Depends(get_db)) -> list[ImageProcessingRunRead]:
    return list_processing_runs(session)


@router.get("/image-processing/runs/history", response_model=ImageProcessingRunPageRead)
def get_image_processing_run_history(
    batch_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ImageProcessingRunPageRead:
    return list_processing_run_page(
        session,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )


@router.post("/image-processing/import", response_model=ImageProcessingRunRead, status_code=201)
async def post_image_import(
    batch_id: str = Form(...),
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_db),
) -> ImageProcessingRunRead:
    try:
        uploads = [(upload.filename or "image", await upload.read()) for upload in files]
        return import_images(session, batch_id, uploads)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/image-processing/runs/{run_id}/generate-logo", response_model=ImageProcessingRunRead)
def post_generate_logo(run_id: str, session: Session = Depends(get_db)) -> ImageProcessingRunRead:
    try:
        return generate_logos(session, run_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/image-processing/assets/reconcile", response_model=ImageAssetReconcileRead)
def post_reconcile_processing_assets(
    session: Session = Depends(get_db),
) -> ImageAssetReconcileRead:
    try:
        return reconcile_processing_assets(session)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/media-assets/contexts", response_model=list[MediaAssetContextRead])
def get_media_asset_contexts(
    session: Session = Depends(get_db),
) -> list[MediaAssetContextRead]:
    return list_media_asset_contexts(session)


@router.get("/media-assets/{asset_id}/thumbnail")
def get_media_asset_thumbnail(
    asset_id: str, session: Session = Depends(get_db)
) -> Response:
    try:
        _, path = resolve_media_asset_file(session, asset_id)
        content, media_type = render_media_asset_thumbnail(path)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/media-assets/{asset_id}/reveal")
def post_reveal_media_asset_folder(
    asset_id: str, session: Session = Depends(get_db)
) -> dict[str, str]:
    try:
        folder = reveal_media_asset_folder(session, asset_id)
        return {"folder": str(folder)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
