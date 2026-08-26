from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.image_processing import (
    ChannelLogoProfileRead,
    ImageProcessingBatchRead,
    ImageProcessingRunRead,
    ImageWorkspaceRead,
    ImageWorkspaceWrite,
)
from zhiju.services.image_processing import (
    generate_logos,
    get_workspace,
    import_images,
    list_channel_logo_profiles,
    list_processing_batches,
    list_processing_runs,
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


@router.get("/image-processing/runs", response_model=list[ImageProcessingRunRead])
def get_image_processing_runs(session: Session = Depends(get_db)) -> list[ImageProcessingRunRead]:
    return list_processing_runs(session)


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
