from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhiju.models import Integration, IntegrationAccount, IntegrationCredential
from zhiju.schemas.integration import (
    IntegrationAccountCreate,
    IntegrationAccountVerify,
    IntegrationCreate,
    IntegrationCredentialUpsert,
)
from zhiju.services.identity import ConflictError, _audit


class IntegrationNotFoundError(Exception):
    pass


def _integration(session: Session, integration_id: str) -> Integration:
    row = session.get(Integration, integration_id)
    if row is None:
        raise IntegrationNotFoundError("第三方集成不存在")
    return row


def _account(session: Session, account_id: str, *, lock: bool = False) -> IntegrationAccount:
    statement = select(IntegrationAccount).where(IntegrationAccount.id == account_id)
    if lock:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise IntegrationNotFoundError("第三方集成账号不存在")
    return row


def create_integration(session: Session, payload: IntegrationCreate) -> Integration:
    row = Integration(
        code=payload.code.strip().lower(),
        name=payload.name.strip(),
        provider_type=payload.provider_type.strip().lower(),
        status=payload.status,
    )
    session.add(row)
    try:
        session.flush()
        _audit(session, "integration.created", "integration", row.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("集成代码已经存在") from exc
    session.refresh(row)
    return row


def list_integrations(session: Session) -> list[Integration]:
    return list(session.scalars(select(Integration).order_by(Integration.code)))


def create_integration_account(
    session: Session, integration_id: str, payload: IntegrationAccountCreate
) -> IntegrationAccount:
    integration = _integration(session, integration_id)
    if integration.status != "active":
        raise ConflictError("当前集成未启用，不能新增账号")
    row = IntegrationAccount(
        integration_id=integration_id,
        account_key=payload.account_key.strip(),
        display_name=payload.display_name.strip(),
        external_account_id=payload.external_account_id,
        status=payload.status,
    )
    session.add(row)
    try:
        session.flush()
        _audit(session, "integration_account.created", "integration_account", row.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("该集成下的账号标识已经存在") from exc
    session.refresh(row)
    return row


def list_integration_accounts(
    session: Session, integration_id: str
) -> list[IntegrationAccount]:
    _integration(session, integration_id)
    return list(
        session.scalars(
            select(IntegrationAccount)
            .where(IntegrationAccount.integration_id == integration_id)
            .order_by(IntegrationAccount.created_at.desc())
        )
    )


def upsert_integration_credential(
    session: Session, account_id: str, payload: IntegrationCredentialUpsert
) -> IntegrationCredential:
    _account(session, account_id, lock=True)
    credential_type = payload.credential_type.strip().lower()
    row = session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.integration_account_id == account_id,
            IntegrationCredential.credential_type == credential_type,
        )
    )
    values = payload.model_dump()
    values["credential_type"] = credential_type
    values["secret_reference"] = payload.secret_reference.strip()
    if row is None:
        row = IntegrationCredential(integration_account_id=account_id, **values)
        session.add(row)
        action = "integration_credential.created"
    else:
        for field, value in values.items():
            setattr(row, field, value)
        action = "integration_credential.updated"
    try:
        session.flush()
        _audit(session, action, "integration_credential", row.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("凭证引用数据冲突") from exc
    session.refresh(row)
    return row


def list_integration_credentials(
    session: Session, account_id: str
) -> list[IntegrationCredential]:
    _account(session, account_id)
    return list(
        session.scalars(
            select(IntegrationCredential)
            .where(IntegrationCredential.integration_account_id == account_id)
            .order_by(IntegrationCredential.credential_type)
        )
    )


def verify_integration_account(
    session: Session, account_id: str, payload: IntegrationAccountVerify
) -> IntegrationAccount:
    account = _account(session, account_id, lock=True)
    now = datetime.now(timezone.utc)
    credentials = list(
        session.scalars(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_account_id == account_id
            )
        )
    )
    usable = [
        item
        for item in credentials
        if item.status == "active"
        and (item.expires_at is None or _as_utc(item.expires_at) > now)
    ]
    if payload.success and not usable:
        raise ConflictError("没有未过期的有效凭证引用，不能将集成账号标记为可用")
    if payload.success:
        account.status = "active"
        account.last_verified_at = now
        if payload.external_account_id is not None:
            account.external_account_id = payload.external_account_id
        for credential in usable:
            credential.last_verified_at = now
        action = "integration_account.verified"
    else:
        account.status = "error"
        action = "integration_account.verification_failed"
    session.flush()
    _audit(
        session,
        action,
        "integration_account",
        account.id,
        change_summary=f"error_code={payload.error_code}"
        if not payload.success and payload.error_code
        else None,
    )
    session.commit()
    session.refresh(account)
    return account


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
