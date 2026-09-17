from sqlalchemy import ForeignKeyConstraint

from zhiju.models import Base


def _columns(constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def test_youtube_import_tables_are_tenant_owned_and_related() -> None:
    sessions = Base.metadata.tables["youtube_channel_import_sessions"]
    candidates = Base.metadata.tables["youtube_channel_import_candidates"]

    assert sessions.c.tenant_id.nullable is False
    assert candidates.c.tenant_id.nullable is False

    candidate_fks = {
        (_columns(fk), fk.referred_table.name)
        for fk in candidates.constraints
        if isinstance(fk, ForeignKeyConstraint)
    }
    assert (("tenant_id", "import_session_id"), "youtube_channel_import_sessions") in candidate_fks
