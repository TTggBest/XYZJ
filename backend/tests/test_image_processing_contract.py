from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from zhiju.app import app
from zhiju.models import ImageProcessingItem, MediaAsset
from zhiju.services.image_processing import (
    _bind_asset_to_package_output,
    _register_imported_community_asset,
    _register_logo_asset,
    calibrate_template,
    classify_image_filename,
    reveal_media_asset_folder,
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
    assert "post" in paths["/api/v3/image-processing/assets/reconcile"]
    assert "get" in paths["/api/v3/media-assets/{asset_id}/content"]
    assert "post" in paths["/api/v3/media-assets/{asset_id}/reveal"]
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
        "abc123-2.jpg": "08_社群2_1x1",
        "abc123-3.webp": "09_社群3_1x1",
        "abc123-12.png": "18_社群12_1x1",
    }

    for filename, role in expected.items():
        result = classify_image_filename(filename, ["abc123"])
        assert result.identifier == "abc123"
        assert result.role == role
        assert result.match_status == "matched"


def test_old_underscore_community_suffix_is_not_matched() -> None:
    result = classify_image_filename("abc123_2.jpg", ["abc123"])

    assert result.identifier is None
    assert result.role is None
    assert result.match_status == "unmatched"


def test_existing_full_community_role_name_remains_supported() -> None:
    result = classify_image_filename("abc123_08_社群2_1x1.png", ["abc123"])

    assert result.identifier == "abc123"
    assert result.role == "08_社群2_1x1"
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


def test_generated_logo_is_registered_as_media_asset(tmp_path: Path) -> None:
    output_path = tmp_path / "02_标题1_16x9_logo.png"
    Image.new("RGB", (1280, 720), "green").save(output_path)
    session = Mock()
    session.scalar.return_value = None
    item = ImageProcessingItem(channel_id="channel-id", package_id="package-id")

    asset = _register_logo_asset(session, item, output_path, "用户产物/logo.png")

    assert isinstance(asset, MediaAsset)
    assert asset.asset_role == "thumbnail"
    assert asset.operation_package_id == "package-id"
    assert asset.width == 1280
    assert asset.height == 720
    assert asset.sha256 == sha256(output_path.read_bytes()).hexdigest()
    session.add.assert_called_once_with(asset)


def test_imported_community_image_is_registered_as_media_asset(tmp_path: Path) -> None:
    source_path = tmp_path / "08_社群2_1x1.jpg"
    Image.new("RGB", (1080, 1080), "blue").save(source_path)
    session = Mock()
    session.scalar.return_value = None
    item = ImageProcessingItem(channel_id="channel-id", package_id="package-id")

    asset = _register_imported_community_asset(
        session, item, source_path, "用户产物/08_社群2_1x1.jpg"
    )

    assert isinstance(asset, MediaAsset)
    assert asset.asset_role == "community_image"
    assert asset.operation_package_id == "package-id"
    assert asset.width == 1080
    assert asset.height == 1080
    session.add.assert_called_once_with(asset)


def test_generated_cover_asset_is_bound_to_selected_cover() -> None:
    session = Mock()
    cover = Mock(asset_id=None, status="prompt_ready")
    session.scalar.return_value = cover
    item = Mock(package_id="package-id", image_role="02_标题1_16x9")
    asset = Mock(id="asset-id")

    assert _bind_asset_to_package_output(session, item, asset) is True
    assert cover.asset_id == "asset-id"
    assert cover.status == "rendered"


def test_imported_community_asset_is_bound_to_matching_post() -> None:
    session = Mock()
    post = Mock(id="post-id")
    session.scalar.side_effect = [post, None]
    item = Mock(package_id="package-id", image_role="08_社群2_1x1")
    asset = Mock(id="asset-id")

    assert _bind_asset_to_package_output(session, item, asset) is True
    link = session.add.call_args.args[0]
    assert link.community_post_id == "post-id"
    assert link.asset_id == "asset-id"
    assert link.position_number == 1


def test_reveal_media_asset_opens_its_parent_folder(tmp_path: Path) -> None:
    image_path = tmp_path / "drama" / "02_标题1_16x9_logo.png"
    image_path.parent.mkdir()
    image_path.write_bytes(b"image")

    with (
        patch(
            "zhiju.services.image_processing.resolve_media_asset_file",
            return_value=(Mock(), image_path),
        ),
        patch("zhiju.services.image_processing.subprocess.Popen") as popen,
    ):
        folder = reveal_media_asset_folder(Mock(), "asset-id")

    assert folder == image_path.parent
    popen.assert_called_once()
    assert popen.call_args.args[0] == ["/usr/bin/open", str(image_path.parent)]


def test_media_page_shows_busy_states_and_prevents_duplicate_actions() -> None:
    source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(encoding="utf-8")

    assert "正在上传并分类" in source
    assert "正在生成…" in source
    assert source.count('dataset.busy === "true"') >= 2
    assert "并登记到素材资产" in source


def test_media_page_groups_assets_and_provides_image_viewer() -> None:
    source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(encoding="utf-8")

    assert "buildMediaGroups" in source
    assert "media-gallery-meta" in source
    assert "批次·档期" in source
    assert "open-media-viewer" in source
    assert "step-media-viewer" in source
    assert "select-media-viewer" in source
    assert "reveal-media-asset" in source
    assert "/content" in source
    assert "package-assets" in source
    assert "view-media-package" in source
    assert "reconcile-media-assets" in source
    assert "社群文案与成品" in source


def test_media_page_filters_assets_by_language_and_channel() -> None:
    source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="mediaLanguageFilter"' in source
    assert 'id="mediaChannelFilter"' in source
    assert "全部语言" in source
    assert "全部频道" in source
    assert "visibleMediaGroups" in source
