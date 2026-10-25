import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_restriction_upgrade_and_downgrade_preserve_existing_videos():
    path = Path(__file__).parents[1] / "alembic/versions/9d25a201d003_add_youtube_region_restriction.py"
    spec = importlib.util.spec_from_file_location("restriction_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE youtube_videos (id VARCHAR(36) PRIMARY KEY, title VARCHAR(500))")
        connection.exec_driver_sql("INSERT INTO youtube_videos VALUES ('existing', '已有视频')")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert tuple(connection.execute(sa.text("SELECT title,region_restriction FROM youtube_videos")).one()) == ("已有视频", None)
            module.downgrade()
        assert [c["name"] for c in sa.inspect(connection).get_columns("youtube_videos")] == ["id", "title"]
        assert connection.execute(sa.text("SELECT title FROM youtube_videos")).scalar_one() == "已有视频"
    engine.dispose()
