from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.identity import (
    AccountCreate,
    AccountRead,
    AuthorizationEventRead,
    ChannelAuthorizationRead,
    ChannelAuthorizationVerify,
    ChannelCreate,
    ChannelOverview,
    ChannelRead,
    ChannelStatusChange,
    DeviceRead,
    DeviceRegister,
    OAuthGrantCreate,
    OAuthGrantRead,
)
from zhiju.services.identity import (
    ConflictError,
    IdentityNotFoundError,
    archive_channel,
    change_channel_status,
    create_account,
    create_channel,
    list_authorization_events,
    list_channel_authorizations,
    list_accounts,
    list_channel_overview,
    list_channels,
    list_oauth_grants,
    register_device,
    register_oauth_grant,
    verify_channel_authorization,
)


router = APIRouter(prefix="/v3", tags=["identity"])


def _identity_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(exc, IdentityNotFoundError) else 409,
        detail=str(exc),
    )


@router.get("/accounts", response_model=list[AccountRead])
def get_accounts(session: Session = Depends(get_db)) -> list[AccountRead]:
    return list_accounts(session)


@router.post("/accounts", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def post_account(payload: AccountCreate, session: Session = Depends(get_db)) -> AccountRead:
    try:
        return create_account(session, payload)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/channels", response_model=list[ChannelRead])
def get_channels(
    include_archived: bool = False,
    session: Session = Depends(get_db),
) -> list[ChannelRead]:
    return list_channels(session, include_archived=include_archived)


@router.post("/channels", response_model=ChannelRead, status_code=status.HTTP_201_CREATED)
def post_channel(payload: ChannelCreate, session: Session = Depends(get_db)) -> ChannelRead:
    try:
        return create_channel(session, payload)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/channels/overview", response_model=list[ChannelOverview])
def get_channel_overview(
    include_archived: bool = False,
    channel_status: str | None = Query(default=None, alias="status"),
    language: str | None = None,
    session: Session = Depends(get_db),
) -> list[ChannelOverview]:
    return list_channel_overview(
        session,
        include_archived=include_archived,
        status=channel_status,
        language=language,
    )


@router.patch("/channels/{channel_id}/status", response_model=ChannelRead)
def patch_channel_status(
    channel_id: str,
    payload: ChannelStatusChange,
    session: Session = Depends(get_db),
) -> ChannelRead:
    try:
        return change_channel_status(session, channel_id, payload)
    except (IdentityNotFoundError, ConflictError) as exc:
        raise _identity_error(exc) from exc


@router.delete("/channels/{channel_id}", response_model=ChannelRead)
def delete_channel(
    channel_id: str,
    reason: str = Query(min_length=1),
    session: Session = Depends(get_db),
) -> ChannelRead:
    try:
        return archive_channel(session, channel_id, reason)
    except (IdentityNotFoundError, ConflictError) as exc:
        raise _identity_error(exc) from exc


@router.put("/devices/register", response_model=DeviceRead)
def put_device(payload: DeviceRegister, session: Session = Depends(get_db)) -> DeviceRead:
    try:
        return register_device(session, payload)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/oauth-grants", response_model=list[OAuthGrantRead])
def get_oauth_grants(
    account_id: str | None = None, session: Session = Depends(get_db)
) -> list[OAuthGrantRead]:
    try:
        return list_oauth_grants(session, account_id)
    except IdentityNotFoundError as exc:
        raise _identity_error(exc) from exc


@router.post("/oauth-grants", response_model=OAuthGrantRead, status_code=status.HTTP_201_CREATED)
def post_oauth_grant(
    payload: OAuthGrantCreate, session: Session = Depends(get_db)
) -> OAuthGrantRead:
    try:
        return register_oauth_grant(session, payload)
    except (IdentityNotFoundError, ConflictError) as exc:
        raise _identity_error(exc) from exc


@router.get("/accounts/{account_id}/oauth-grants", response_model=list[OAuthGrantRead])
def get_account_oauth_grants(
    account_id: str, session: Session = Depends(get_db)
) -> list[OAuthGrantRead]:
    try:
        return list_oauth_grants(session, account_id)
    except IdentityNotFoundError as exc:
        raise _identity_error(exc) from exc


@router.post(
    "/channel-authorizations/verify",
    response_model=ChannelAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def post_channel_authorization_verify(
    payload: ChannelAuthorizationVerify, session: Session = Depends(get_db)
) -> ChannelAuthorizationRead:
    try:
        return verify_channel_authorization(session, payload)
    except (IdentityNotFoundError, ConflictError) as exc:
        raise _identity_error(exc) from exc


@router.get(
    "/channels/{channel_id}/authorizations",
    response_model=list[ChannelAuthorizationRead],
)
def get_channel_authorizations(
    channel_id: str, session: Session = Depends(get_db)
) -> list[ChannelAuthorizationRead]:
    try:
        return list_channel_authorizations(session, channel_id)
    except IdentityNotFoundError as exc:
        raise _identity_error(exc) from exc


@router.get("/authorization-events", response_model=list[AuthorizationEventRead])
def get_authorization_events(
    account_id: str | None = None,
    channel_id: str | None = None,
    result: Literal["success", "failure", "cancelled"] | None = None,
    session: Session = Depends(get_db),
) -> list[AuthorizationEventRead]:
    return list_authorization_events(
        session,
        account_id=account_id,
        channel_id=channel_id,
        result=result,
    )
    archive_channel,
    change_channel_status,
