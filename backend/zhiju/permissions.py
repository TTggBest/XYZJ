from collections.abc import Callable

from fastapi import Depends, HTTPException

from zhiju.auth_context import Principal, get_current_principal
from zhiju.config import get_settings


def require_builder_device() -> None:
    if get_settings().device_role != "builder":
        raise HTTPException(status_code=403, detail="仅代码机可以查看 Skills 和系统日志")


def require_permission(code: str) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if code not in principal.permissions:
            raise HTTPException(status_code=403, detail="没有执行该操作的权限")
        return principal

    return dependency


def require_super_code_machine(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if principal.platform_role != "super_admin" or principal.device_trust_level != "super_code_machine":
        raise HTTPException(status_code=403, detail="仅超级代码机上的超级管理员可以执行该操作")
    return principal
