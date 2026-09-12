from dataclasses import replace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import String, delete, event, select, update
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, aliased, mapped_column

from zhiju import auth_context, database
from zhiju.auth_context import Principal
from zhiju.models import base


PRINCIPAL = Principal(
    user_id="user-a", tenant_id="tenant-a", membership_role="owner", platform_role=None,
    device_id=None, device_trust_level="normal", permissions=frozenset({"channel.read"}),
)


class FixtureBase(DeclarativeBase):
    pass


class OwnedFixture(base.TenantOwnedMixin, FixtureBase):
    __tablename__ = "owned_fixture"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(default="original")


@pytest.fixture
def tenant_store(monkeypatch, tmp_path):
    router = database.DatabaseRouter(
        f"sqlite:///{tmp_path / 'tenant.db'}", initial_environment="development",
    )
    monkeypatch.setattr(database, "database_router", router)
    FixtureBase.metadata.create_all(router.get_active_engine())
    with router.open_session() as session:
        session.add_all([
            OwnedFixture(id="a", tenant_id="tenant-a"),
            OwnedFixture(id="a2", tenant_id="tenant-a"),
            OwnedFixture(id="b", tenant_id="tenant-b"),
            OwnedFixture(id="legacy", tenant_id=None),
        ])
        session.commit()
    yield router
    router.dispose()


def test_tenant_owned_mixin_declares_nullable_indexed_tenant_id():
    assert hasattr(base, "TenantOwnedMixin")

    class FixtureBase(DeclarativeBase):
        pass

    class OwnedFixture(base.TenantOwnedMixin, FixtureBase):
        __tablename__ = "owned_fixture"
        id: Mapped[str] = mapped_column(primary_key=True)

    column = OwnedFixture.__table__.c.tenant_id
    assert isinstance(column.type, String)
    assert column.type.length == 36
    assert column.nullable
    assert column.index


def test_open_tenant_session_carries_resolved_principal(monkeypatch):
    assert hasattr(database, "open_tenant_session")
    router = database.DatabaseRouter("sqlite://", initial_environment="development")
    monkeypatch.setattr(database, "database_router", router)
    try:
        with database.open_tenant_session(PRINCIPAL) as session:
            assert isinstance(session, database.TenantSession)
            assert session.info == {
                "tenant_id": "tenant-a", "user_id": "user-a", "permissions": PRINCIPAL.permissions,
            }
            assert session.get_bind() is router.get_active_engine()
    finally:
        router.dispose()


@pytest.mark.parametrize("tenant_id", [None, ""])
def test_open_tenant_session_requires_current_tenant(tenant_id):
    assert hasattr(database, "open_tenant_session")
    with pytest.raises(HTTPException) as exc:
        database.open_tenant_session(replace(PRINCIPAL, tenant_id=tenant_id))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("shape", ["entity", "column", "alias"])
def test_select_filters_current_tenant_in_each_session(tenant_store, shape):
    model = aliased(OwnedFixture) if shape == "alias" else OwnedFixture
    statement = select(model.id) if shape == "column" else select(model)
    for tenant_id, expected in [("tenant-a", ["a", "a2"]), ("tenant-b", ["b"])]:
        with database.open_tenant_session(replace(PRINCIPAL, tenant_id=tenant_id)) as session:
            rows = session.scalars(statement.order_by(model.id)).all()
            assert (rows if shape == "column" else [row.id for row in rows]) == expected


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_orm_bulk_dml_filters_current_tenant(tenant_store, operation):
    statement = (
        update(OwnedFixture).values(name="changed") if operation == "update"
        else delete(OwnedFixture)
    )
    with database.open_tenant_session(PRINCIPAL) as session:
        result = session.execute(statement)
        assert result.rowcount == 2
        session.commit()
    with tenant_store.open_session() as session:
        assert session.get(OwnedFixture, "b").name == "original"
        assert session.get(OwnedFixture, "legacy").name == "original"
        own = session.get(OwnedFixture, "a")
        assert own.name == "changed" if operation == "update" else own is None


def test_new_objects_receive_current_tenant(tenant_store):
    with database.open_tenant_session(PRINCIPAL) as session:
        row = OwnedFixture(id="new")
        session.add(row)
        session.commit()
        assert row.tenant_id == "tenant-a"
    with tenant_store.open_session() as session:
        assert session.get(OwnedFixture, "new").tenant_id == "tenant-a"


def test_explicit_other_tenant_on_insert_is_rejected(tenant_store):
    with database.open_tenant_session(PRINCIPAL) as session:
        session.add(OwnedFixture(id="new", tenant_id="tenant-b"))
        with pytest.raises(HTTPException) as exc:
            session.flush()
        assert exc.value.status_code == 403


@pytest.mark.parametrize("operation", ["modify", "delete", "reassign"])
def test_foreign_objects_cannot_be_flushed(tenant_store, operation):
    with tenant_store.open_session() as unscoped:
        row = unscoped.get(OwnedFixture, "b")
        unscoped.expunge(row)
    with database.open_tenant_session(PRINCIPAL) as session:
        if operation == "delete":
            session.delete(row)
        else:
            session.add(row)
            row.name = "changed"
            if operation == "reassign":
                row.tenant_id = "tenant-a"
        with pytest.raises(HTTPException) as exc:
            session.flush()
        assert exc.value.status_code == 403


@pytest.mark.parametrize("tenant_id", [None, "tenant-b"])
def test_current_tenant_objects_cannot_change_owner(tenant_store, tenant_id):
    with database.open_tenant_session(PRINCIPAL) as session:
        row = session.scalar(select(OwnedFixture).where(OwnedFixture.id == "a"))
        row.tenant_id = tenant_id
        with pytest.raises(HTTPException) as exc:
            session.flush()
        assert exc.value.status_code == 403


def test_current_tenant_objects_can_be_modified_and_deleted(tenant_store):
    with database.open_tenant_session(PRINCIPAL) as session:
        row = session.scalar(select(OwnedFixture).where(OwnedFixture.id == "a"))
        row.name = "changed"
        session.commit()
        session.delete(row)
        session.commit()
    with tenant_store.open_session() as session:
        assert session.get(OwnedFixture, "a") is None
        assert session.get(OwnedFixture, "b").name == "original"


@pytest.mark.parametrize("entity_id", ["b", "legacy", "missing"])
@pytest.mark.parametrize("lock", [False, True])
def test_require_tenant_entity_hides_other_tenant_and_missing_ids(tenant_store, entity_id, lock):
    from zhiju import tenant_repository

    with database.open_tenant_session(PRINCIPAL) as session:
        with pytest.raises(HTTPException) as exc:
            tenant_repository.require_tenant_entity(session, OwnedFixture, entity_id, lock=lock)
        assert exc.value.status_code == 404


@pytest.mark.parametrize("entity_ids", [["a", "b"], ["a", "missing"], ["a", "legacy"]])
def test_require_tenant_entities_fails_the_entire_batch(tenant_store, entity_ids):
    from zhiju import tenant_repository

    with database.open_tenant_session(PRINCIPAL) as session:
        with pytest.raises(HTTPException) as exc:
            tenant_repository.require_tenant_entities(session, OwnedFixture, entity_ids)
        assert exc.value.status_code == 404


@pytest.mark.parametrize("lock", [False, True])
def test_repository_reads_current_tenant_in_input_order(tenant_store, lock):
    from zhiju import tenant_repository

    with database.open_tenant_session(PRINCIPAL) as session:
        assert tenant_repository.require_tenant_entity(session, OwnedFixture, "a", lock=lock).id == "a"
        rows = tenant_repository.require_tenant_entities(
            session, OwnedFixture, ["a2", "a", "a2"], lock=lock,
        )
        assert [row.id for row in rows] == ["a2", "a", "a2"]
        assert tenant_repository.require_tenant_entities(session, OwnedFixture, [], lock=lock) == []


def test_repository_does_not_trust_identity_map(tenant_store):
    from zhiju import tenant_repository

    with tenant_store.open_session() as unscoped:
        foreign = unscoped.get(OwnedFixture, "b")
        unscoped.expunge(foreign)
    with database.open_tenant_session(PRINCIPAL) as session:
        session.add(foreign)
        assert session.get(OwnedFixture, "b") is foreign
        with pytest.raises(HTTPException) as exc:
            tenant_repository.require_tenant_entity(session, OwnedFixture, "b")
        assert exc.value.status_code == 404


@pytest.mark.parametrize("batch", [False, True])
def test_repository_requires_tenant_context(tenant_store, batch):
    from zhiju import tenant_repository

    with tenant_store.open_session() as session:
        with pytest.raises(HTTPException) as exc:
            if batch:
                tenant_repository.require_tenant_entities(session, OwnedFixture, [])
            else:
                tenant_repository.require_tenant_entity(session, OwnedFixture, "a")
        assert exc.value.status_code == 403


@pytest.mark.parametrize("batch", [False, True])
def test_repository_lock_emits_for_update(tenant_store, batch):
    from zhiju import tenant_repository

    statements = []
    with database.open_tenant_session(PRINCIPAL) as session:
        event.listen(session, "do_orm_execute", lambda state: statements.append(
            str(state.statement.compile(dialect=mysql.dialect())),
        ))
        if batch:
            tenant_repository.require_tenant_entities(session, OwnedFixture, ["a"], lock=True)
        else:
            tenant_repository.require_tenant_entity(session, OwnedFixture, "a", lock=True)
    assert len(statements) == 1
    assert "FOR UPDATE" in statements[0]


@pytest.mark.parametrize("tenant_id", ["tenant-a", None])
def test_tenant_dependency_uses_only_resolved_principal(tenant_store, tenant_id):
    assert hasattr(auth_context, "get_tenant_db")
    app = FastAPI()
    app.dependency_overrides[auth_context.get_current_principal] = lambda: replace(
        PRINCIPAL, tenant_id=tenant_id,
    )

    @app.get("/rows")
    def rows(session: Session = Depends(auth_context.get_tenant_db)):
        return {
            "tenant_id": session.info["tenant_id"],
            "ids": session.scalars(select(OwnedFixture.id).order_by(OwnedFixture.id)).all(),
        }

    with TestClient(app) as client:
        response = client.get("/rows?tenant_id=tenant-b", headers={"x-tenant-id": "tenant-b"})
    if tenant_id is None:
        assert response.status_code == 403
    else:
        assert response.status_code == 200
        assert response.json() == {"tenant_id": "tenant-a", "ids": ["a", "a2"]}


@pytest.mark.parametrize("shape", ["values", "ordered_values", "parameters"])
def test_orm_update_cannot_reassign_tenant(tenant_store, shape):
    with database.open_tenant_session(PRINCIPAL) as session:
        statement = update(OwnedFixture).where(OwnedFixture.id == "a")
        with pytest.raises(HTTPException) as exc:
            if shape == "values":
                session.execute(statement.values(tenant_id="tenant-b"))
            elif shape == "ordered_values":
                session.execute(statement.ordered_values((OwnedFixture.tenant_id, "tenant-b")))
            else:
                session.execute(statement, {"tenant_id": "tenant-b"})
        assert exc.value.status_code == 403


def test_orm_update_by_primary_key_fails_entire_cross_tenant_batch(tenant_store):
    with database.open_tenant_session(PRINCIPAL) as session:
        with pytest.raises(HTTPException) as exc:
            session.execute(update(OwnedFixture), [
                {"id": "a", "name": "changed"}, {"id": "b", "name": "changed"},
            ])
        assert exc.value.status_code == 404
        session.commit()
    with tenant_store.open_session() as session:
        assert session.get(OwnedFixture, "a").name == "original"
        assert session.get(OwnedFixture, "b").name == "original"


def test_orm_update_by_primary_key_allows_current_tenant_batch(tenant_store):
    with database.open_tenant_session(PRINCIPAL) as session:
        session.execute(update(OwnedFixture), [
            {"id": "a", "name": "changed"}, {"id": "a2", "name": "changed"},
        ])
        session.commit()
    with tenant_store.open_session() as session:
        assert session.get(OwnedFixture, "a").name == "changed"
        assert session.get(OwnedFixture, "a2").name == "changed"
        assert session.get(OwnedFixture, "b").name == "original"
