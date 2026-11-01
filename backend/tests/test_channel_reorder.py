from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select

from zhiju.database import TenantSession
from zhiju.models import Base, Channel
from zhiju.services import identity


def test_reorder_persists_for_the_tenant_and_appends_new_channels():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with TenantSession(bind=engine, info={"tenant_id": "tenant-a"}) as session:
        old = Channel(id="old", youtube_channel_id="UC-old", original_name="Old", status="active", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        new = Channel(id="new", youtube_channel_id="UC-new", original_name="New", status="active", created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
        session.add_all([old, new]); session.commit()
        assert [c.id for c in identity.list_channels(session)] == ["old", "new"]
        identity.reorder_channels(session, ["new", "old"])
        session.expire_all()
        assert [c.id for c in identity.list_channels(session)] == ["new", "old"]
        assert [c["channel_id"] for c in identity.list_channel_overview(session)] == ["new", "old"]
        session.add(Channel(id="latest", youtube_channel_id="UC-latest", original_name="Latest", status="active", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc)))
        session.commit()
        assert [c.id for c in identity.list_channels(session)] == ["new", "old", "latest"]
        with pytest.raises(identity.ConflictError):
            identity.reorder_channels(session, ["old", "new"])
        with pytest.raises(identity.ConflictError):
            identity.reorder_channels(session, ["old", "new", "new"])
        assert [c.id for c in identity.list_channels(session)] == ["new", "old", "latest"]
    with TenantSession(bind=engine, info={"tenant_id": "tenant-b"}) as session:
        other = Channel(id="other", youtube_channel_id="UC-other", original_name="Other", status="active")
        session.add(other); session.commit()
        with pytest.raises(identity.ConflictError):
            identity.reorder_channels(session, ["new", "old", "latest"])
        assert session.scalar(select(Channel)).sort_order is None


def test_order_api_requires_management_permission_and_returns_saved_positions():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from zhiju.api.identity import router
    from zhiju.auth_context import Principal, get_current_principal, get_tenant_db
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    principal = Principal(user_id="user", tenant_id="tenant-a", membership_role="owner", platform_role=None,
                          device_id=None, device_trust_level="normal", permissions=frozenset({"channel.manage"}))
    app = FastAPI(); app.include_router(router, prefix="/api")
    def db():
        with TenantSession(bind=engine, info={"tenant_id": "tenant-a"}) as session:
            yield session
    app.dependency_overrides[get_tenant_db] = db
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TenantSession(bind=engine, info={"tenant_id": "tenant-a"}) as session:
        session.add_all([Channel(id=key, youtube_channel_id="UC-" + key, original_name=key, status="active") for key in ("first", "second")])
        session.commit()
    client = TestClient(app)
    response = client.put("/api/v3/channels/order", json={"channel_ids": ["second", "first"]})
    assert response.status_code == 200, response.text
    assert [(c["id"], c["sort_order"]) for c in response.json()] == [("second", 1), ("first", 2)]
    assert [c["id"] for c in client.get("/api/v3/channels").json()] == ["second", "first"]
    from dataclasses import replace
    app.dependency_overrides[get_current_principal] = lambda: replace(principal, permissions=frozenset({"channel.read"}))
    assert client.put("/api/v3/channels/order", json={"channel_ids": ["first", "second"]}).status_code == 403
    assert [c["id"] for c in client.get("/api/v3/channels").json()] == ["second", "first"]


def test_channel_order_migration_preserves_existing_rows():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    path = Path(__file__).resolve().parents[1] / "alembic/versions/f18b20261101_channel_sort_order.py"
    spec = importlib.util.spec_from_file_location("channel_order_migration", path)
    revision = importlib.util.module_from_spec(spec); spec.loader.exec_module(revision)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE channels (id TEXT PRIMARY KEY, original_name TEXT)"))
        connection.execute(text("INSERT INTO channels VALUES ('existing', 'Existing channel')"))
        revision.op = Operations(MigrationContext.configure(connection))
        revision.upgrade()
        assert connection.execute(text("SELECT id, original_name, sort_order FROM channels")).one() == ("existing", "Existing channel", None)
        revision.downgrade()
        assert connection.execute(text("SELECT * FROM channels")).one() == ("existing", "Existing channel")
