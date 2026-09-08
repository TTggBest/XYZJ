from fastapi import HTTPException

from zhiju.config import get_settings


def require_builder_device() -> None:
    if get_settings().device_role != "builder":
        raise HTTPException(status_code=403, detail="仅代码机可以查看 Skills 和系统日志")
