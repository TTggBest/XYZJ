from contextlib import contextmanager
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.api.auth import require_same_origin
from zhiju.auth_context import Principal, get_current_principal
from zhiju.database import get_db
from zhiju.permissions import require_super_code_machine
from zhiju.schemas.platform_admin import (
    AccountView, BindingRevoke, DeviceBindingCreate, DeviceBindingView, OwnerTransfer,
    PasswordReset, SuperAdminTransfer, TenantCreate, TenantUpdate, TenantView,
    UserCreate, UserUpdate, UserView,
)
from zhiju.services import platform_admin as service


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/v3/platform", tags=["platform-admin"], dependencies=[Depends(no_store)])
tenant_router = APIRouter(prefix="/v3/tenant/users", tags=["tenant-users"], dependencies=[Depends(no_store)])


@contextmanager
def _transaction(session: Session, request: Request):
    # Resolve inside the write transaction so auth heartbeat cannot commit any part of it.
    try:
        with session.begin():
            yield get_current_principal(request, session)
    except IntegrityError:
        # Database uniqueness is final authority; never expose bound values or SQL.
        raise HTTPException(status_code=409, detail="登录名、主账号简称或关联记录冲突") from None


@router.get("/tenants", response_model=list[TenantView])
def get_tenants(principal: Principal = Depends(get_current_principal), session: Session = Depends(get_db)):
    return service.list_tenants(session, principal)


@router.post("/tenants", response_model=TenantView, status_code=201, dependencies=[Depends(require_same_origin)])
def post_tenant(payload: TenantCreate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.create_tenant(session, principal, payload, request_id=str(uuid4()))


@router.patch("/tenants/{tenant_id}", response_model=TenantView, dependencies=[Depends(require_same_origin)])
def patch_tenant(tenant_id: str, payload: TenantUpdate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.update_tenant(session, principal, tenant_id, payload, request_id=str(uuid4()))


@router.post("/tenants/{tenant_id}/owner", response_model=TenantView, dependencies=[Depends(require_same_origin)])
def post_owner(tenant_id: str, payload: OwnerTransfer, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.transfer_owner(session, principal, tenant_id, payload, request_id=str(uuid4()))


@router.get("/tenants/{tenant_id}/users", response_model=list[UserView])
def get_users(tenant_id: str, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_db)):
    return service.list_users(session, principal, tenant_id=tenant_id)


@router.post("/tenants/{tenant_id}/users", response_model=UserView, status_code=201,
             dependencies=[Depends(require_same_origin)])
def post_user(tenant_id: str, payload: UserCreate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.create_user(session, principal, payload, tenant_id=tenant_id, request_id=str(uuid4()))


@router.patch("/tenants/{tenant_id}/users/{user_id}", response_model=UserView,
              dependencies=[Depends(require_same_origin)])
def patch_user(tenant_id: str, user_id: str, payload: UserUpdate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.update_user(session, principal, user_id, payload, tenant_id=tenant_id, request_id=str(uuid4()))


@router.post("/tenants/{tenant_id}/users/{user_id}/password", response_model=UserView,
             dependencies=[Depends(require_same_origin)])
def post_password(tenant_id: str, user_id: str, payload: PasswordReset, request: Request,
                  session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.reset_password(session, principal, user_id, payload, tenant_id=tenant_id, request_id=str(uuid4()))


@router.post("/super-admin", response_model=AccountView, dependencies=[Depends(require_same_origin)])
def post_super_admin(payload: SuperAdminTransfer, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.transfer_super_admin(session, principal, payload, request_id=str(uuid4()))


@router.get("/device-bindings", response_model=list[DeviceBindingView])
def get_bindings(tenant_id: str | None = None, principal: Principal = Depends(get_current_principal),
                 session: Session = Depends(get_db)):
    return service.list_device_bindings(session, principal, tenant_id=tenant_id)


@router.post("/device-bindings", response_model=DeviceBindingView, dependencies=[Depends(require_same_origin)])
def post_binding(payload: DeviceBindingCreate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        require_super_code_machine(principal)
        raise HTTPException(status_code=409, detail="请通过本地登记服务将设备秘密写入目标 Keychain；普通 API 不执行登记")


@router.post("/device-bindings/{binding_id}/revoke", response_model=DeviceBindingView,
             dependencies=[Depends(require_same_origin)])
def post_binding_revoke(binding_id: str, payload: BindingRevoke, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.revoke_device_binding(session, principal, binding_id, payload, request_id=str(uuid4()))


@tenant_router.get("", response_model=list[UserView])
def get_tenant_users(principal: Principal = Depends(get_current_principal), session: Session = Depends(get_db)):
    return service.list_users(session, principal)


@tenant_router.post("", response_model=UserView, status_code=201, dependencies=[Depends(require_same_origin)])
def post_tenant_user(payload: UserCreate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.create_user(session, principal, payload, request_id=str(uuid4()))


@tenant_router.patch("/{user_id}", response_model=UserView, dependencies=[Depends(require_same_origin)])
def patch_tenant_user(user_id: str, payload: UserUpdate, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.update_user(session, principal, user_id, payload, request_id=str(uuid4()))


@tenant_router.post("/{user_id}/password", response_model=UserView, dependencies=[Depends(require_same_origin)])
def post_tenant_password(user_id: str, payload: PasswordReset, request: Request, session: Session = Depends(get_db)):
    with _transaction(session, request) as principal:
        return service.reset_password(session, principal, user_id, payload, request_id=str(uuid4()))
