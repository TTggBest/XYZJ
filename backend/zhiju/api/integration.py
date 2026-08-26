from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from zhiju.database import get_db
from zhiju.schemas.integration import (
    IntegrationAccountCreate,
    IntegrationAccountRead,
    IntegrationAccountVerify,
    IntegrationCreate,
    IntegrationCredentialRead,
    IntegrationCredentialUpsert,
    IntegrationRead,
)
from zhiju.services.identity import ConflictError
from zhiju.services.integration import (
    IntegrationNotFoundError,
    create_integration,
    create_integration_account,
    list_integration_accounts,
    list_integration_credentials,
    list_integrations,
    upsert_integration_credential,
    verify_integration_account,
)


router = APIRouter(prefix="/v3", tags=["integrations"])


def _raise(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(exc, IntegrationNotFoundError) else 409,
        detail=str(exc),
    )


@router.get("/integrations", response_model=list[IntegrationRead])
def get_integrations(session: Session = Depends(get_db)) -> list[IntegrationRead]:
    return list_integrations(session)


@router.post("/integrations", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
def post_integration(
    payload: IntegrationCreate, session: Session = Depends(get_db)
) -> IntegrationRead:
    try:
        return create_integration(session, payload)
    except ConflictError as exc:
        raise _raise(exc) from exc


@router.get(
    "/integrations/{integration_id}/accounts",
    response_model=list[IntegrationAccountRead],
)
def get_integration_accounts(
    integration_id: str, session: Session = Depends(get_db)
) -> list[IntegrationAccountRead]:
    try:
        return list_integration_accounts(session, integration_id)
    except IntegrationNotFoundError as exc:
        raise _raise(exc) from exc


@router.post(
    "/integrations/{integration_id}/accounts",
    response_model=IntegrationAccountRead,
    status_code=status.HTTP_201_CREATED,
)
def post_integration_account(
    integration_id: str,
    payload: IntegrationAccountCreate,
    session: Session = Depends(get_db),
) -> IntegrationAccountRead:
    try:
        return create_integration_account(session, integration_id, payload)
    except (IntegrationNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.get(
    "/integration-accounts/{account_id}/credentials",
    response_model=list[IntegrationCredentialRead],
)
def get_integration_credentials(
    account_id: str, session: Session = Depends(get_db)
) -> list[IntegrationCredentialRead]:
    try:
        return list_integration_credentials(session, account_id)
    except IntegrationNotFoundError as exc:
        raise _raise(exc) from exc


@router.put(
    "/integration-accounts/{account_id}/credentials",
    response_model=IntegrationCredentialRead,
)
def put_integration_credential(
    account_id: str,
    payload: IntegrationCredentialUpsert,
    session: Session = Depends(get_db),
) -> IntegrationCredentialRead:
    try:
        return upsert_integration_credential(session, account_id, payload)
    except (IntegrationNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc


@router.post(
    "/integration-accounts/{account_id}/verify",
    response_model=IntegrationAccountRead,
)
def post_integration_account_verify(
    account_id: str,
    payload: IntegrationAccountVerify,
    session: Session = Depends(get_db),
) -> IntegrationAccountRead:
    try:
        return verify_integration_account(session, account_id, payload)
    except (IntegrationNotFoundError, ConflictError) as exc:
        raise _raise(exc) from exc

