from fastapi.testclient import TestClient

from zhiju.app import create_app


def test_privacy_policy_is_public_and_describes_google_data_use() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/privacy")

    assert response.status_code == 200
    assert "筱宇智矩隐私政策" in response.text
    assert "YouTube" in response.text
    assert "OAuth" in response.text
    assert "12345ttgg12345@gmail.com" in response.text


def test_terms_are_public() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/terms")

    assert response.status_code == 200
    assert "筱宇智矩服务条款" in response.text
    assert "12345ttgg12345@gmail.com" in response.text
