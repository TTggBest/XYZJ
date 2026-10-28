from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_inventory_migration_keeps_existing_progress_and_distinguishes_unknown_from_empty(monkeypatch):
    module = import_module("backend.alembic.versions.d83f1e604af2_add_finished_language_inventory")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE drama_production_states (id TEXT PRIMARY KEY, production_completion_status TEXT)"))
        connection.execute(sa.text("INSERT INTO drama_production_states VALUES ('existing','completed')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        table = sa.Table("drama_production_states", sa.MetaData(), autoload_with=connection)
        row = connection.execute(sa.select(table)).mappings().one()
        assert row["production_completion_status"] == "completed" and row["finished_languages"] is None
        connection.execute(table.update().values(finished_languages=[]))
        assert connection.execute(sa.select(table.c.finished_languages)).scalar_one() == []
        module.downgrade()
        assert connection.execute(sa.text("SELECT production_completion_status FROM drama_production_states")).scalar_one() == "completed"
    engine.dispose()
