import pytest
from fastapi.testclient import TestClient

from zhiju.app import app


@pytest.mark.parametrize(
    ("path", "number_field"),
    (
        ("/api/v3/dramas/library", "drama_number"),
        ("/api/v3/drama-production", "drama_number"),
    ),
)
def test_drama_lists_default_to_fifty_items_in_descending_number_order(
    path: str,
    number_field: str,
) -> None:
    response = TestClient(app).get(path)

    assert response.status_code == 200
    payload = response.json()
    numbers = [item[number_field] for item in payload["items"]]
    assert payload["page_size"] == 50
    assert len(numbers) == 50
    assert numbers == sorted(numbers, reverse=True)


@pytest.mark.parametrize("page_size", (100, 150))
@pytest.mark.parametrize(
    "path",
    ("/api/v3/dramas/library", "/api/v3/drama-production"),
)
def test_drama_lists_support_ascending_order_and_selectable_page_sizes(
    path: str,
    page_size: int,
) -> None:
    response = TestClient(app).get(
        path,
        params={"sort_order": "asc", "page_size": page_size},
    )

    assert response.status_code == 200
    payload = response.json()
    numbers = [item["drama_number"] for item in payload["items"]]
    assert payload["page_size"] == page_size
    assert len(numbers) == page_size
    assert numbers == sorted(numbers)
