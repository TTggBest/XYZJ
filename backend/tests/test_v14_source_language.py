from copy import deepcopy

import pytest

from test_v14_contract import envelope
from test_v14_runs import configure, store
from zhiju.database import TenantSession
from zhiju.models import Drama
from zhiju.services.v14_runs import create_run
from zhiju.v14_runtime.contract import build_stage_input


@pytest.fixture(autouse=True)
def frozen_rules():
    from zhiju.v14_runtime.contract import bundled_rules
    from zhiju.v14_runtime.rules import using_rules

    with using_rules(bundled_rules()):
        yield


def test_new_run_freezes_original_language_not_channel_language(store):
    with TenantSession(store, info={"tenant_id": "tenant-a"}) as session:
        configure(session)
        drama = session.get(Drama, "drama-a")
        drama.source_language = "en"
        session.commit()
        session.expire_all()
        run = create_run(session, "work-a")
        assert run.input_snapshot["drama"]["source_language"] == "en"
        drama.source_language = "zh"
        session.commit()
        assert run.input_snapshot["drama"]["source_language"] == "en"


@pytest.mark.parametrize("node", ["title", "cover", "community"])
@pytest.mark.parametrize("language,expected", [
    ("en", "European and North American facial features"),
    ("zh", "Chinese facial features"),
    (None, "Chinese facial features"),
])
def test_visual_generation_uses_original_language_on_initial_and_retry(node, language, expected):
    data = envelope()
    data["input_snapshot"]["drama"]["source_language"] = language
    # Deliberately different: Arabic channel/dubbing language cannot decide faces.
    data["input_snapshot"]["channel"]["language"] = "阿拉伯语"
    for feedback in ([], [{"node_type": node, "error": "correct_failed_group"}]):
        data["retry_state"] = feedback
        original = deepcopy(data)
        stage = build_stage_input(data, node)
        assert stage.context["source_language"] == language
        assert expected in stage.prompt.split("Source-language cast requirement:")[-1]
        assert "Never infer" in stage.prompt.split("Source-language cast requirement:")[-1]
        assert data == original


@pytest.mark.parametrize("language,actor,style", [
    ("en", "Western actors, European and North American facial features, Western appearance", "Natural live-action Western television drama still"),
    ("zh", "Chinese actors, Chinese facial features, East Asian appearance", "Natural live-action Chinese television drama still"),
    (None, "Chinese actors, Chinese facial features, East Asian appearance", "Natural live-action Chinese television drama still"),
])
def test_final_cover_assembly_and_validation_share_original_language(language, actor, style):
    from zhiju.v14_runtime import canonical as c

    stage = build_stage_input(envelope(), "cover")
    stage.context["source_language"] = language
    result = {"section": "covers", "results": [{"titles": [
        {"title_index": n, "scene_prompt_4_5": "Two adults face each other across a table.",
         "core_words": word, "outpaint_environment": "Continue the room."}
        for n, word in enumerate(("Wife", "Mother", "Heiress"), 1)
    ]}]}
    c.normalize_identity(result, stage.item)
    c.normalize_cover_prompt_contract(result, stage.context["cover_rule_contract"], stage.context)
    for row in c.cover_rows(result):
        assert row["prompt_4_5"].count(actor) == 1
        assert row["prompt_4_5"].count(style) == 1
        assert c.cover_prompt_structure_issues(row, row["title_index"], stage.context) == []
        if language == "en":
            assert "Chinese" not in row["prompt_4_5"]
    issues = c.validate_cover(result, stage.item, stage.context)
    assert not [i for i in issues if "prompt_4_5_missing_" in i or "block_count" in i]
    c.cover_rows(result)[0]["prompt_4_5"] = "Unspecified actors."
    assert any("cover_1_prompt_4_5_missing_" in i for i in c.validate_cover(result, stage.item, stage.context))


@pytest.mark.parametrize("language,face,cast", [
    ("en", "European and North American facial features", "Western short-drama"),
    ("zh", "Chinese facial features", "Chinese short-drama"),
    (None, "Chinese facial features", "Chinese short-drama"),
])
def test_community_accepts_matching_cast_and_rejects_wrong_cast(language, face, cast):
    from zhiju.v14_runtime import canonical as c

    stage = build_stage_input(envelope(), "community")
    stage.context["source_language"] = language
    payload = {"section": "community", "results": [{"plan_index": 1,
        "image_prompt_1x1": f"Natural live-action {cast} cast with {face}.", "copy": ""}]}
    c.normalize_identity(payload, stage.item)
    issues = c.validate_post(payload, stage.item, stage.context)
    assert not [i for i in issues if "facial_features" in i or "short-drama" in i]
    payload["results"][0]["image_prompt_1x1"] = "Unspecified actors."
    issues = c.validate_post(payload, stage.item, stage.context)
    assert f"post_1_prompt_missing_{face.replace(' ', '_')}" in issues
    assert f"post_1_prompt_missing_{cast.replace(' ', '_')}" in issues


@pytest.mark.parametrize("already_backfilled", [False, True])
def test_migration_preserves_original_fields_and_existing_source_language(already_backfilled):
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / "alembic/versions/a16c2d9e4107_add_drama_original_language.py"
    spec = importlib.util.spec_from_file_location("original_language_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        suffix = ", source_language VARCHAR(10)" if already_backfilled else ""
        connection.exec_driver_sql("CREATE TABLE dramas (id INTEGER, chinese_title TEXT" + suffix + ")")
        connection.exec_driver_sql("INSERT INTO dramas (id, chinese_title) VALUES (1, 'Original title')")
        if already_backfilled:
            connection.exec_driver_sql("UPDATE dramas SET source_language='en' WHERE id=1")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT id, chinese_title, source_language FROM dramas").one() == (
            1, "Original title", "en" if already_backfilled else None,
        )
    engine.dispose()
