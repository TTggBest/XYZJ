from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from zhiju.models import Base


def _columns(constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def test_youtube_import_tables_are_tenant_owned_and_related() -> None:
    sessions = Base.metadata.tables["youtube_channel_import_sessions"]
    candidates = Base.metadata.tables["youtube_channel_import_candidates"]
    secrets = Base.metadata.tables["oauth_token_secrets"]

    assert sessions.c.tenant_id.nullable is False
    assert candidates.c.tenant_id.nullable is False
    assert secrets.c.tenant_id.nullable is False

    candidate_fks = {
        (_columns(fk), fk.referred_table.name)
        for fk in candidates.constraints
        if isinstance(fk, ForeignKeyConstraint)
    }
    assert (("tenant_id", "import_session_id"), "youtube_channel_import_sessions") in candidate_fks

    secret_unique_keys = {
        _columns(key) for key in secrets.constraints if isinstance(key, UniqueConstraint)
    }
    assert ("tenant_id", "oauth_grant_id") in secret_unique_keys
