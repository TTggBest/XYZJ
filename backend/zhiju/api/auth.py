from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal, get_current_principal
from zhiju.config import Settings, get_settings
from zhiju.database import get_db
from zhiju.schemas.auth import CurrentUser, LogoutResult, PasswordLogin, TenantSwitch
from zhiju.services.auth import current_user, logout, password_login, switch_tenant


router = APIRouter(prefix="/v3/auth", tags=["auth"])


def require_same_origin(request: Request) -> None:
    if request.headers.get("origin") != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(status_code=403, detail="请求来源不匹配")


def _cookie_options(request: Request, settings: Settings) -> dict:
    return {
        "key": "zhiju_session", "path": "/", "httponly": True, "samesite": "lax",
        "secure": settings.env == "production" and request.url.scheme == "https",
    }


@router.post("/login", response_model=CurrentUser, dependencies=[Depends(require_same_origin)])
def post_login(
    payload: PasswordLogin, request: Request, response: Response,
    session: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> CurrentUser:
    with session.begin():
        result = password_login(
            session, login_name=payload.login_name, password=payload.password.get_secret_value(),
            request_id=str(uuid4()), configured_device_id=settings.device_id,
        )
        body = current_user(session, result.principal) if result else None
    # Login failures must commit their counters and audit before returning the same 401.
    if result is None:
        raise HTTPException(status_code=401, detail="账号或密码错误，或账号暂不可用")
    response.set_cookie(value=result.token, expires=result.expires_at, **_cookie_options(request, settings))
    response.headers["Cache-Control"] = "no-store"
    return body


@router.post("/logout", response_model=LogoutResult, dependencies=[Depends(require_same_origin)])
def post_logout(
    request: Request, response: Response, session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LogoutResult:
    # The cookie can still be cleared after an account or its tenant becomes inactive.
    with session.begin():
        logout(session, token=request.cookies.get("zhiju_session"), request_id=str(uuid4()))
    response.delete_cookie(**_cookie_options(request, settings))
    response.headers["Cache-Control"] = "no-store"
    return LogoutResult()


@router.get("/me", response_model=CurrentUser)
def get_me(
    response: Response, principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> CurrentUser:
    response.headers["Cache-Control"] = "no-store"
    return current_user(session, principal)


@router.post("/switch-tenant", response_model=CurrentUser, dependencies=[Depends(require_same_origin)])
def post_switch_tenant(
    payload: TenantSwitch, request: Request, response: Response, session: Session = Depends(get_db),
) -> CurrentUser:
    # Own the transaction before principal resolution so its heartbeat cannot commit writes.
    with session.begin():
        principal = get_current_principal(request, session)
        switch_tenant(
            session, principal, token=request.cookies["zhiju_session"], tenant_id=payload.tenant_id,
            request_id=str(uuid4()),
        )
        body = current_user(session, get_current_principal(request, session))
    response.headers["Cache-Control"] = "no-store"
    return body
