from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from zhiju.app import app
from zhiju.services.image_processing import (
    calibrate_template,
    classify_image_filename,
    resolve_workspace_root,
)


def test_image_processing_routes_are_registered() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]

    assert {"get", "put"}.issubset(paths["/api/v3/settings/image-workspace"])
    assert "get" in paths["/api/v3/channels/logo-profiles"]
    assert "put" in paths["/api/v3/channels/{channel_id}/logo-profile"]
    assert "get" in paths["/api/v3/image-processing/batches"]
    assert "post" in paths["/api/v3/image-processing/import"]
    assert "get" in paths["/api/v3/image-processing/runs"]
    assert "post" in paths["/api/v3/image-processing/runs/{run_id}/generate-logo"]
    assert client.get("/api/v3/channels/logo-profiles").status_code == 200


def test_workspace_root_uses_device_shared_root_for_relative_setting(tmp_path: Path) -> None:
    assert resolve_workspace_root("images", tmp_path) == (tmp_path / "images").resolve()
    assert resolve_workspace_root(str(tmp_path / "absolute"), None) == (tmp_path / "absolute").resolve()


def test_workspace_root_rejects_relative_setting_without_shared_root() -> None:
    try:
        resolve_workspace_root("images", None)
    except ValueError as exc:
        assert "ZHJ_SHARED_ROOT" in str(exc)
    else:
        raise AssertionError("relative workspace root must require ZHJ_SHARED_ROOT")


def test_v11_image_names_are_classified_by_video_id() -> None:
    expected = {
        "abc1231_4_5.png": "01_标题1_4x5",
        "abc1231.png": "02_标题1_16x9",
        "abc1232_4_5.png": "03_标题2_4x5",
        "abc1232.png": "04_标题2_16x9",
        "abc1233_4_5.png": "05_标题3_4x5",
        "abc1233.png": "06_标题3_16x9",
        "abc123.png": "07_社群1_1x1",
        "abc123_2.jpg": "08_社群2_1x1",
    }

    for filename, role in expected.items():
        result = classify_image_filename(filename, ["abc123"])
        assert result.identifier == "abc123"
        assert result.role == role
        assert result.match_status == "matched"


def test_template_calibration_finds_left_and_right_logo_regions(tmp_path: Path) -> None:
    template = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(template)
    draw.rectangle((40, 610, 310, 680), fill="black")
    draw.rectangle((890, 610, 1240, 680), fill="black")
    template_path = tmp_path / "tem.jpg"
    template.save(template_path, quality=100)

    config = calibrate_template(template_path)

    assert config["canvas"] == {"width": 1280, "height": 720}
    assert config["left_logo"]["x"] < 0.1
    assert config["right_logo"]["x"] > 0.6
    assert config["left_logo"]["width"] > 0.15
    assert config["right_logo"]["width"] > 0.2
