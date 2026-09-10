from hashlib import sha256
from datetime import date
from io import BytesIO
from pathlib import Path
import subprocess
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from zhiju.app import app
from sqlalchemy.orm import Session

from zhiju import models
from zhiju.database import database_router
from zhiju.models import ImageProcessingItem, MediaAsset
from zhiju.services import image_processing
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
    assert "get" in paths["/api/v3/image-processing/batches/{batch_id}/asset-coverage"]
    assert "post" in paths["/api/v3/image-processing/import"]
    assert "get" in paths["/api/v3/image-processing/runs"]
    assert "post" in paths["/api/v3/image-processing/runs/{run_id}/generate-logo"]
    assert "post" in paths["/api/v3/image-processing/assets/reconcile"]
    assert "get" in paths["/api/v3/media-assets/{asset_id}/content"]
    assert "get" in paths["/api/v3/media-assets/{asset_id}/thumbnail"]
    assert "get" in paths["/api/v3/media-assets/contexts"]
    assert "post" in paths["/api/v3/media-assets/{asset_id}/reveal"]
    assert client.get("/api/v3/channels/logo-profiles").status_code == 200


def test_media_asset_contexts_return_only_packages_with_images_and_small_fields() -> None:
    list_contexts = getattr(image_processing, "list_media_asset_contexts", None)
    assert callable(list_contexts), "media page needs a dedicated lightweight context query"

    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = models.Channel(
            youtube_channel_id=f"UC-MEDIA-{suffix}",
            original_name=f"素材频道-{suffix}",
            operational_name=f"素材昵称-{suffix}",
            default_language="en",
            timezone="Asia/Shanghai",
            status="active",
        )
        drama = models.Drama(
            drama_number=-int(suffix[:8], 16),
            drama_code=f"MEDIA-{suffix}",
            chinese_title=f"素材剧目-{suffix}",
            normalized_title=f"素材剧目-{suffix}".casefold(),
            source_type="manual",
            status="active",
        )
        batch = models.ProductionBatch(
            batch_number=f"FS-MEDIA-{suffix}",
            production_date=date(2026, 9, 10),
            source="native",
            status="active",
        )
        session.add_all([channel, drama, batch])
        session.flush()
        task = models.OperationTask(
            batch_id=batch.id,
            channel_id=channel.id,
            drama_id=drama.id,
            task_date=date(2026, 9, 10),
            target_publish_date=date(2026, 9, 12),
            source="manual",
            status="completed",
            idempotency_key=f"media-context-task-{suffix}",
            source_video_id=f"video-{suffix}",
            source_row_number=7,
        )
        session.add(task)
        session.flush()
        work_order = models.WorkOrder(
            task_id=task.id,
            batch_id=batch.id,
            channel_id=channel.id,
            drama_id=drama.id,
            production_date=date(2026, 9, 10),
            target_publish_date=date(2026, 9, 12),
            status="completed",
        )
        session.add(work_order)
        session.flush()
        with_asset = models.OperationPackage(
            work_order_id=work_order.id,
            batch_id=batch.id,
            channel_id=channel.id,
            drama_id=drama.id,
            version_number=1,
            status="approved",
        )
        without_asset = models.OperationPackage(
            work_order_id=work_order.id,
            batch_id=batch.id,
            channel_id=channel.id,
            drama_id=drama.id,
            version_number=2,
            status="approved",
        )
        session.add_all([with_asset, without_asset])
        session.flush()
        session.add(models.MediaAsset(
            channel_id=channel.id,
            operation_package_id=with_asset.id,
            storage_provider="local",
            storage_key=f"用户产物/{suffix}/cover.webp",
            original_filename="cover.webp",
            asset_type="image",
            asset_role="thumbnail",
            mime_type="image/webp",
            sha256="a" * 64,
            width=1280,
            height=720,
            file_size_bytes=100,
            status="ready",
        ))
        session.commit()

        rows = list_contexts(session)
        row = next(item for item in rows if item["package_id"] == with_asset.id)

        assert not any(item["package_id"] == without_asset.id for item in rows)
        assert row == {
            "package_id": with_asset.id,
            "channel_id": channel.id,
            "channel_name": channel.operational_name,
            "language_code": "en",
            "drama_id": drama.id,
            "drama_code": drama.drama_code,
            "chinese_title": drama.chinese_title,
            "video_id": task.source_video_id,
            "source_row_number": 7,
            "batch_number": batch.batch_number,
            "target_publish_date": date(2026, 9, 12),
            "planned_local_time": None,
        }
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_batch_asset_coverage_includes_complete_incomplete_and_empty_packages() -> None:
    list_coverage = getattr(image_processing, "list_batch_media_coverage", None)
    assert callable(list_coverage), "selected batch needs package-level image coverage"

    suffix = uuid4().hex[:10]
    connection = database_router.get_active_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        channel = models.Channel(
            youtube_channel_id=f"UC-COVERAGE-{suffix}",
            original_name=f"覆盖频道-{suffix}",
            operational_name=f"覆盖昵称-{suffix}",
            default_language="es",
            timezone="Asia/Shanghai",
            status="active",
        )
        batch = models.ProductionBatch(
            batch_number=f"FS-COVERAGE-{suffix}",
            production_date=date(2026, 9, 10),
            source="native",
            status="active",
        )
        session.add_all([channel, batch])
        session.flush()

        package_rows = []
        for number, community_count in enumerate((1, 2, 1), start=1):
            drama = models.Drama(
                drama_number=-(int(suffix[:7], 16) + number),
                drama_code=f"COVERAGE-{suffix}-{number}",
                chinese_title=f"覆盖剧目-{suffix}-{number}",
                normalized_title=f"覆盖剧目-{suffix}-{number}".casefold(),
                source_type="manual",
                status="active",
            )
            session.add(drama)
            session.flush()
            task = models.OperationTask(
                batch_id=batch.id,
                channel_id=channel.id,
                drama_id=drama.id,
                task_date=date(2026, 9, 10),
                target_publish_date=date(2026, 9, 12),
                community_count=community_count,
                source="manual",
                status="completed",
                idempotency_key=f"coverage-task-{suffix}-{number}",
                source_video_id=f"video-{suffix}-{number}",
            )
            session.add(task)
            session.flush()
            order = models.WorkOrder(
                task_id=task.id,
                batch_id=batch.id,
                channel_id=channel.id,
                drama_id=drama.id,
                production_date=date(2026, 9, 10),
                target_publish_date=date(2026, 9, 12),
                community_count=community_count,
                status="completed",
            )
            session.add(order)
            session.flush()
            package = models.OperationPackage(
                work_order_id=order.id,
                batch_id=batch.id,
                channel_id=channel.id,
                drama_id=drama.id,
                version_number=1,
                status="approved",
            )
            session.add(package)
            session.flush()
            package_rows.append((package, task))

        roles_by_package = {
            package_rows[0][0].id: (
                "02_标题1_16x9_logo.png",
                "04_标题2_16x9_logo.png",
                "06_标题3_16x9_logo.png",
                "07_社群1_1x1.png",
            ),
            package_rows[1][0].id: (
                "02_标题1_16x9_logo.png",
                "06_标题3_16x9_logo.png",
                "07_社群1_1x1.png",
            ),
        }
        asset_number = 0
        for package_id, filenames in roles_by_package.items():
            for filename in filenames:
                asset_number += 1
                session.add(models.MediaAsset(
                    channel_id=channel.id,
                    operation_package_id=package_id,
                    storage_provider="local",
                    storage_key=f"用户产物/{suffix}/{package_id}/{filename}",
                    original_filename=filename,
                    asset_type="image",
                    asset_role="thumbnail",
                    mime_type="image/png",
                    sha256=f"{asset_number:x}" * 64,
                    width=1280,
                    height=720,
                    file_size_bytes=100,
                    status="ready",
                ))
        session.commit()

        rows = list_coverage(session, batch.id)
        by_video = {row["video_id"]: row for row in rows}

        assert len(rows) == 3
        complete = by_video[package_rows[0][1].source_video_id]
        assert complete["complete"] is True
        assert complete["expected_count"] == 4
        assert complete["present_count"] == 4
        assert complete["missing_roles"] == []

        incomplete = by_video[package_rows[1][1].source_video_id]
        assert incomplete["complete"] is False
        assert incomplete["expected_count"] == 5
        assert incomplete["present_count"] == 3
        assert incomplete["missing_roles"] == ["封面2", "社群2"]

        empty_package = by_video[package_rows[2][1].source_video_id]
        assert empty_package["present_count"] == 0
        assert empty_package["missing_roles"] == ["封面1", "封面2", "封面3", "社群1"]
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_media_asset_thumbnail_is_small_webp(tmp_path: Path) -> None:
    render_thumbnail = getattr(image_processing, "render_media_asset_thumbnail", None)
    assert callable(render_thumbnail), "media list needs a small thumbnail renderer"
    source = tmp_path / "large.png"
    Image.new("RGB", (1600, 900), "blue").save(source)

    content, media_type = render_thumbnail(source)

    assert media_type == "image/webp"
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert max(thumbnail.size) == 480


def test_media_gallery_paginates_twenty_groups_per_page() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "assets" / "media-gallery.js"
    program = (
        "const gallery=require(process.argv[1]);"
        "const result=gallery.paginateGroups(Array.from({length:45},(_,i)=>i+1),2,20);"
        "process.stdout.write(JSON.stringify(result));"
    )

    completed = subprocess.run(
        ["node", "-e", program, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == '{"items":[21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40],"page":2,"totalPages":3,"total":45}'


def test_media_gallery_filters_status_and_cycles_incomplete_groups() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "assets" / "media-gallery.js"
    program = (
        "const gallery=require(process.argv[1]);"
        "const groups=["
        "{complete:true,meta:{package_id:'ready',language_code:'es',channel_id:'a'}},"
        "{complete:false,meta:{package_id:'missing-1',language_code:'es',channel_id:'a'}},"
        "{complete:false,meta:{package_id:'missing-2',language_code:'es',channel_id:'b'}}];"
        "const filtered=gallery.filterGroups(groups,{status:'incomplete'}).map(x=>x.meta.package_id);"
        "const first=gallery.nextIncompleteGroup(groups);"
        "const second=gallery.nextIncompleteGroup(groups,first.meta.package_id);"
        "const wrapped=gallery.nextIncompleteGroup(groups,second.meta.package_id);"
        "process.stdout.write(JSON.stringify({filtered,first:first.meta.package_id,second:second.meta.package_id,wrapped:wrapped.meta.package_id}));"
    )

    completed = subprocess.run(
        ["node", "-e", program, str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == '{"filtered":["missing-1","missing-2"],"first":"missing-1","second":"missing-2","wrapped":"missing-1"}'


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


def test_media_page_filters_assets_by_selected_production_batch() -> None:
    source = (Path(__file__).resolve().parents[2] / "assets" / "app.js").read_text(encoding="utf-8")

    assert 'id="mediaBatchFilter"' in source
    assert "batch_id: state.mediaBatchId" in source
    assert 'event.target.id === "mediaBatchFilter"' in source


def test_media_page_shows_batch_coverage_video_id_and_missing_image_navigation() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "assets" / "app.js").read_text(encoding="utf-8")
    styles = (root / "assets" / "styles.css").read_text(encoding="utf-8")

    assert "asset-coverage" in source
    assert 'id="mediaBatchProgress"' in source
    assert "Video ID" in source
    assert "missing_roles" in source
    assert 'data-action="show-missing-media"' in source
    assert 'data-action="show-media-package-missing"' in source
    assert 'id="mediaStatusFilter"' in source
    assert "nextIncompleteGroup" in source
    assert "run.batch_id === state.mediaBatchId" in source
    assert ".media-gallery-group.is-complete" in styles
    assert ".media-gallery-group.is-incomplete" in styles
    assert ".media-assets-fixed-panel { position: sticky; top: 78px;" in styles
    assert ".media-assets-section #mediaGalleryContent { overflow: visible; }" in styles
    assert "height: calc(100vh - 104px)" not in styles


def test_media_viewer_hides_thumbnail_strip_until_bottom_interaction() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "assets" / "app.js").read_text(encoding="utf-8")
    styles = (root / "assets" / "styles.css").read_text(encoding="utf-8")

    assert "bindMediaViewerStrip" in source
    assert "media-viewer-strip-handle" in source
    assert "mouseenter" in source
    assert "mouseleave" in source
    assert "toggle-media-strip" in source
    assert ".media-viewer.is-strip-open" in styles
    assert "grid-template-rows: 68px minmax(0, 1fr) 18px" in styles
    assert "grid-template-rows: 68px minmax(0, 1fr) 142px" in styles
