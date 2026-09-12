from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from zhiju.auth_context import Principal
from zhiju.database import TenantSession
from zhiju.models import Base, Channel, OAuthAuthorizationState
from zhiju.services.youtube_oauth import create_oauth_state, consume_oauth_state
from zhiju.services.channel import NotFoundError


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
PRINCIPAL = Principal(
    user_id="user-a", tenant_id="tenant-a", membership_role="owner",
    platform_role=None, device_id=None, device_trust_level="normal",
    permissions=frozenset(), session_id="session-a",
)


@pytest.fixture
def state_store():
    engine = sa.create_engine(
        "sqlite://", poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Channel(
                id="channel-a", tenant_id="tenant-a", youtube_channel_id="UC-A",
                original_name="A", status="active",
            ),
            Channel(
                id="channel-b", tenant_id="tenant-b", youtube_channel_id="UC-B",
                original_name="B", status="active",
            ),
        ])
        session.commit()
    yield engine
    engine.dispose()


def test_oauth_state_persists_exact_principal_context_and_is_single_use(state_store):
    with TenantSession(
        state_store, info={"tenant_id": "tenant-a", "user_id": "user-a", "permissions": frozenset()},
    ) as session:
        opaque = create_oauth_state(session, PRINCIPAL, "channel-a", now=NOW)

    with Session(state_store) as session:
        row = session.scalar(sa.select(OAuthAuthorizationState))
        assert row.tenant_id == "tenant-a"
        assert row.user_id == "user-a"
        assert row.session_id == "session-a"
        assert row.channel_id == "channel-a"
        assert row.expires_at.replace(tzinfo=timezone.utc) == NOW + timedelta(minutes=10)
        assert row.consumed_at is None

        context = consume_oauth_state(session, opaque, now=NOW + timedelta(seconds=1))
        assert (
            context.tenant_id, context.user_id, context.session_id, context.channel_id
        ) == ("tenant-a", "user-a", "session-a", "channel-a")
        assert session.get(OAuthAuthorizationState, row.id).consumed_at.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=1)

        with pytest.raises(ValueError, match="无效或已经使用"):
            consume_oauth_state(session, opaque, now=NOW + timedelta(seconds=2))


def test_oauth_state_rejects_foreign_channel_before_creating_row(state_store):
    with TenantSession(
        state_store, info={"tenant_id": "tenant-a", "user_id": "user-a", "permissions": frozenset()},
    ) as session:
        with pytest.raises(NotFoundError):
            create_oauth_state(session, PRINCIPAL, "channel-b", now=NOW)
        assert session.scalar(sa.select(sa.func.count()).select_from(OAuthAuthorizationState)) == 0


def test_expired_oauth_state_cannot_be_consumed(state_store):
    with TenantSession(
        state_store, info={"tenant_id": "tenant-a", "user_id": "user-a", "permissions": frozenset()},
    ) as session:
        opaque = create_oauth_state(session, PRINCIPAL, "channel-a", now=NOW, ttl_seconds=30)
    with Session(state_store) as session:
        with pytest.raises(ValueError, match="已过期"):
            consume_oauth_state(session, opaque, now=NOW + timedelta(seconds=31))


@pytest.fixture
def migration():
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    revision = next(
        (item for item in ScriptDirectory.from_config(config).walk_revisions()
         if item.revision == "a6c9d2e7f165"),
        None,
    )
    return revision.module if revision else None


def test_oauth_youtube_migration_stops_before_ddl_when_strong_parents_disagree(migration):
    assert migration is not None, "Task 8 migration is missing"
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    for table in migration.ROOTS:
        sa.Table(table, metadata, sa.Column("id", sa.String(36), primary_key=True), sa.Column("tenant_id", sa.String(36)))
    sa.Table("google_oauth_grants", metadata, sa.Column("id", sa.String(36), primary_key=True), sa.Column("account_id", sa.String(36)))
    sa.Table("google_oauth_grant_scopes", metadata, sa.Column("grant_id", sa.String(36)), sa.Column("scope", sa.String(500)))
    sa.Table(
        "account_channel_authorizations", metadata,
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("account_id", sa.String(36)),
        sa.Column("channel_id", sa.String(36)), sa.Column("oauth_grant_id", sa.String(36)),
    )
    sa.Table(
        "authorization_events", metadata, sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36)), sa.Column("channel_id", sa.String(36)),
        sa.Column("oauth_grant_id", sa.String(36)),
    )
    for table, columns in migration.YOUTUBE_COLUMNS.items():
        sa.Table(table, metadata, sa.Column("id", sa.String(36), primary_key=True), *(
            sa.Column(column, sa.String(36)) for column in columns
        ))
    for table, columns in migration.EXISTING_COLUMNS.items():
        sa.Table(table, metadata, sa.Column("id", sa.String(36), primary_key=True), *(
            sa.Column(column, sa.String(36)) for column in columns
        ))
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(metadata.tables["google_accounts"].insert(), [
            {"id": "account-a", "tenant_id": "tenant-a"},
        ])
        connection.execute(metadata.tables["channels"].insert(), [
            {"id": "channel-b", "tenant_id": "tenant-b"},
        ])
        connection.execute(metadata.tables["google_oauth_grants"].insert(), [
            {"id": "grant-a", "account_id": "account-a"},
        ])
        connection.execute(metadata.tables["account_channel_authorizations"].insert(), [
            {"id": "binding", "account_id": "account-a", "channel_id": "channel-b", "oauth_grant_id": "grant-a"},
        ])
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="account_channel_authorizations"):
            migration.upgrade()
        assert "tenant_id" not in {
            column["name"] for column in sa.inspect(connection).get_columns("google_oauth_grants")
        }
        assert not sa.inspect(connection).has_table("oauth_authorization_states")
    engine.dispose()
