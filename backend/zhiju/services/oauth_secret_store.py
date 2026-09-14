from __future__ import annotations

import json
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiju.models.integration import OAuthTokenSecret


class EncryptedDatabaseSecretStore:
    def __init__(self, session: Session, encryption_key: str):
        try:
            self._fernet = Fernet(encryption_key.encode())
        except (TypeError, ValueError) as exc:
            raise ValueError("云端OAuth令牌加密密钥无效") from exc
        self._session = session

    def _tenant_id(self) -> str:
        tenant_id = str(self._session.info.get("tenant_id") or "").strip()
        if not tenant_id:
            raise ValueError("当前数据库会话缺少公司上下文")
        return tenant_id

    def put(self, grant_id: str, token: Mapping[str, object]) -> str:
        tenant_id = self._tenant_id()
        document = json.dumps(
            dict(token), ensure_ascii=True, separators=(",", ":"), sort_keys=True,
        )
        encrypted = self._fernet.encrypt(document.encode()).decode()
        row = self._session.scalar(
            select(OAuthTokenSecret).where(
                OAuthTokenSecret.tenant_id == tenant_id,
                OAuthTokenSecret.oauth_grant_id == grant_id,
            )
        )
        if row is None:
            row = OAuthTokenSecret(
                tenant_id=tenant_id,
                oauth_grant_id=grant_id,
                encrypted_payload=encrypted,
            )
            self._session.add(row)
        else:
            row.encrypted_payload = encrypted
        self._session.flush()
        return f"db-encrypted://google-oauth/{grant_id}"

    def get(self, grant_id: str) -> dict[str, object] | None:
        tenant_id = self._tenant_id()
        row = self._session.scalar(
            select(OAuthTokenSecret).where(
                OAuthTokenSecret.tenant_id == tenant_id,
                OAuthTokenSecret.oauth_grant_id == grant_id,
            )
        )
        if row is None:
            return None
        try:
            document = self._fernet.decrypt(row.encrypted_payload.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("云端OAuth令牌无法解密") from exc
        value = json.loads(document)
        if not isinstance(value, dict):
            raise ValueError("云端OAuth令牌格式无效")
        return value

    def delete(self, grant_id: str) -> None:
        tenant_id = self._tenant_id()
        row = self._session.scalar(
            select(OAuthTokenSecret).where(
                OAuthTokenSecret.tenant_id == tenant_id,
                OAuthTokenSecret.oauth_grant_id == grant_id,
            )
        )
        if row is not None:
            self._session.delete(row)
