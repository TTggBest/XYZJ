import platform
import socket
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.identity import DeviceRead, DeviceRegister
from zhiju.schemas.settings import AppIconSettingRead, AppIconUpload, RuntimeOverview, RuntimePackageBuildRead
from zhiju.services.identity import list_devices, register_device
from zhiju.services.settings import build_runtime_package, get_app_icon_setting, get_current_runtime_package, list_runtime_packages, restore_default_app_icon, runtime_overview, stream_runtime_package, upload_app_icon


router = APIRouter(prefix="/v3", tags=["settings"])


@router.get("/settings/runtime", response_model=RuntimeOverview)
def get_runtime_settings(session: Session = Depends(get_db)) -> RuntimeOverview:
    return RuntimeOverview.model_validate(runtime_overview(session))


@router.get("/devices", response_model=list[DeviceRead])
def get_devices(session: Session = Depends(get_db)) -> list[DeviceRead]:
    return list_devices(session)


@router.post("/devices/register-current", response_model=DeviceRead)
def post_current_device(session: Session = Depends(get_db)) -> DeviceRead:
    hostname = socket.gethostname()
    payload = DeviceRegister(
        device_key=f"{platform.system().lower()}:{hostname}",
        name=hostname,
        alias="当前智矩设备",
        hostname=hostname,
        device_role="builder",
        login_user=Path.home().name,
        os_type=f"{platform.system()} {platform.release()}",
        purpose="智矩开发与运营",
    )
    return register_device(session, payload)


@router.get("/runtime-packages", response_model=list[RuntimePackageBuildRead])
def get_runtime_packages(session: Session = Depends(get_db)) -> list[RuntimePackageBuildRead]:
    return list_runtime_packages(session)


@router.post(
    "/runtime-packages/build",
    response_model=RuntimePackageBuildRead,
    status_code=status.HTTP_201_CREATED,
)
def post_runtime_package(session: Session = Depends(get_db)) -> RuntimePackageBuildRead:
    return build_runtime_package(session)


@router.get("/runtime-packages/{build_id}/download")
def download_runtime_package(build_id: str, session: Session = Depends(get_db)) -> StreamingResponse:
    try:
        build = get_current_runtime_package(session, build_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename = f"zhiju-runtime-{build.version}.tar.gz"
    return StreamingResponse(
        stream_runtime_package(build),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/settings/app-icon", response_model=AppIconSettingRead)
def get_app_icon(session: Session = Depends(get_db)) -> AppIconSettingRead:
    return get_app_icon_setting(session)


@router.put("/settings/app-icon", response_model=AppIconSettingRead)
def put_app_icon(payload: AppIconUpload, session: Session = Depends(get_db)) -> AppIconSettingRead:
    try:
        return upload_app_icon(session, payload.filename, payload.data_url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/settings/app-icon/restore-default", response_model=AppIconSettingRead)
def post_restore_app_icon(session: Session = Depends(get_db)) -> AppIconSettingRead:
    return restore_default_app_icon(session)
