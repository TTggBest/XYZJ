from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from zhiju.models import Base, OAuthTokenSecret
from zhiju.services.oauth_secret_store import EncryptedDatabaseSecretStore


def test_database_secret_store_never_persists_plaintext() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    key = Fernet.generate_key().decode()

    with Session(engine, info={"tenant_id": "tenant-a"}) as session:
        store = EncryptedDatabaseSecretStore(session, key)
        reference = store.put(
            "grant-a",
            {"access_token": "access-secret", "refresh_token": "refresh-secret"},
        )
        row = session.scalar(select(OAuthTokenSecret))

        assert reference == "db-encrypted://google-oauth/grant-a"
        assert row is not None
        assert "access-secret" not in row.encrypted_payload
        assert "refresh-secret" not in row.encrypted_payload
        assert store.get("grant-a") == {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
        }

    engine.dispose()


def test_database_secret_store_rejects_invalid_key() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine, info={"tenant_id": "tenant-a"}) as session:
        try:
            EncryptedDatabaseSecretStore(session, "not-a-fernet-key")
        except ValueError as exc:
            assert str(exc) == "云端OAuth令牌加密密钥无效"
        else:
            raise AssertionError("invalid encryption key was accepted")

    engine.dispose()


def test_database_secret_store_reads_only_current_tenant() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    key = Fernet.generate_key().decode()
    cipher = Fernet(key.encode())

    with Session(engine, info={"tenant_id": "tenant-a"}) as session:
        session.add_all([
            OAuthTokenSecret(
                tenant_id="tenant-b",
                oauth_grant_id="grant-shared",
                encrypted_payload=cipher.encrypt(b'{"access_token":"tenant-b"}').decode(),
            ),
            OAuthTokenSecret(
                tenant_id="tenant-a",
                oauth_grant_id="grant-shared",
                encrypted_payload=cipher.encrypt(b'{"access_token":"tenant-a"}').decode(),
            ),
        ])
        session.commit()

        assert EncryptedDatabaseSecretStore(session, key).get("grant-shared") == {
            "access_token": "tenant-a"
        }

    engine.dispose()
