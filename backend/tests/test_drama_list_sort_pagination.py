import pytest
from fastapi.testclient import TestClient

from zhiju.app import app


@pytest.mark.parametrize(
    "path",
    ("/api/v3/dramas/library", "/api/v3/drama-production"),
)
def test_drama_lists_default_to_fifty_items_in_recorded_order(path: str) -> None:
    response = TestClient(app).get(path)

    assert response.status_code == 200
    payload = response.json()
    numbers = [item["sequence_number"] for item in payload["items"]]
    assert payload["page_size"] == 50
    assert len(numbers) == 50
    assert numbers == list(range(1, 51))


def test_library_sequence_starts_from_first_feishu_data_row() -> None:
    response = TestClient(app).get("/api/v3/dramas/library")

    assert response.status_code == 200
    first = response.json()["items"][0]
    assert first["sequence_number"] == 1
    assert first["source_row_number"] == 2


@pytest.mark.parametrize("page_size", (100, 150))
@pytest.mark.parametrize(
    "path",
    ("/api/v3/dramas/library", "/api/v3/drama-production"),
)
def test_drama_lists_support_descending_order_and_selectable_page_sizes(
    path: str,
    page_size: int,
) -> None:
    response = TestClient(app).get(
        path,
        params={"sort_order": "desc", "page_size": page_size},
    )

    assert response.status_code == 200
    payload = response.json()
    numbers = [item["sequence_number"] for item in payload["items"]]
    assert payload["page_size"] == page_size
    assert len(numbers) == page_size
    assert numbers == sorted(numbers, reverse=True)
    assert numbers[0] == payload["total"]
