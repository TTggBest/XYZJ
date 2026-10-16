import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upload_identity_upgrade_preserves_existing_video_and_downgrade_removes_only_new_columns():
    path = Path(__file__).parents[1] / "alembic/versions/6a81c4d290fe_add_video_upload_identity.py"
    spec = importlib.util.spec_from_file_location("upload_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE youtube_videos (id VARCHAR(36) PRIMARY KEY, title VARCHAR(500))")
        connection.exec_driver_sql("INSERT INTO youtube_videos VALUES ('old-video', '已有视频')")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            row = connection.execute(sa.text("SELECT title,original_file_name,uploaded_at,upload_status FROM youtube_videos")).one()
            assert tuple(row) == ("已有视频", None, None, None)
            module.downgrade()
        assert [c["name"] for c in sa.inspect(connection).get_columns("youtube_videos")] == ["id", "title"]
        assert connection.execute(sa.text("SELECT title FROM youtube_videos")).scalar_one() == "已有视频"
    engine.dispose()
