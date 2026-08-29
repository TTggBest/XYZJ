from fastapi.testclient import TestClient
from pathlib import Path

from zhiju.app import app


ROOT = Path(__file__).resolve().parents[2]


def test_skill_registry_routes_are_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert {"get", "post"}.issubset(paths["/api/v3/skills"])
    assert {"get", "patch"}.issubset(paths["/api/v3/skills/{skill_id}"])
    assert {"get", "post"}.issubset(
        paths["/api/v3/skills/{skill_id}/versions"]
    )
    assert {"get", "put"}.issubset(
        paths["/api/v3/skills/{skill_id}/versions/{version_id}"]
    )
    assert "post" in paths[
        "/api/v3/skills/{skill_id}/versions/{version_id}/publish"
    ]


def test_skill_contract_stores_bilingual_database_content() -> None:
    document = TestClient(app).get("/openapi.json").json()
    serialized = str(document)

    assert "body_zh_cn" in serialized
    assert "body_original" in serialized
    assert "source_file" not in serialized
    assert "file_path" not in serialized


def test_skills_page_can_manage_draft_versions_and_publish() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function skillVersionForm" in source
    assert 'data-action="add-skill-version"' in source
    assert 'data-action="edit-skill-version"' in source
    assert 'data-action="publish-skill-version"' in source
    assert 'id="skillVersionForm"' in source
    assert "`/skills/${skillId}/versions/${versionId}/publish`" in source
