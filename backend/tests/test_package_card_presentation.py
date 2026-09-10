import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def render_presentation(item: dict) -> dict:
    script = """
const presentation = require(process.argv[1]);
const item = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(presentation.buildPackagePresentation(item)));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "assets" / "package-presentation.js"),
            json.dumps(item, ensure_ascii=False),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def summarize_packages(items: list[dict], total: int) -> dict:
    script = """
const presentation = require(process.argv[1]);
const items = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(presentation.summarizePackageProgress(items, Number(process.argv[3]))));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "assets" / "package-presentation.js"),
            json.dumps(items, ensure_ascii=False),
            str(total),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_package_card_keeps_operational_nickname_and_distinct_original_channel_name() -> None:
    result = render_presentation(
        {
            "channel_name": "Bangkit Setelah Terluka-印尼-女频-复仇逆袭",
            "channel_original_name": "Bangkit Setelah Terluka",
            "package_version": 1,
        }
    )

    assert result["channel_primary"] == "Bangkit Setelah Terluka-印尼-女频-复仇逆袭"
    assert result["channel_secondary"] == "原频道：Bangkit Setelah Terluka"
    assert result["channel_title"] == (
        "运营昵称：Bangkit Setelah Terluka-印尼-女频-复仇逆袭\n"
        "原频道：Bangkit Setelah Terluka"
    )
    assert result["version_label"] == "运营包版本 V1"


def test_package_card_falls_back_to_original_channel_and_marks_empty_text() -> None:
    result = render_presentation(
        {
            "channel_name": "",
            "channel_original_name": "Original Channel",
            "package_version": None,
            "playlist_name": None,
            "description": None,
        }
    )

    assert result["channel_primary"] == "Original Channel"
    assert result["channel_secondary"] == ""
    assert result["version_label"] == "运营包版本 V1"
    assert result["playlist_name"] == "暂无播放列表"
    assert result["playlists"] == []
    assert result["localized_description"] == "暂无频道语言说明"
    assert result["chinese_description"] == "暂无中文对照"


def test_package_card_exposes_all_channel_playlists_and_marks_selected_one() -> None:
    result = render_presentation(
        {
            "channel_name": "运营昵称",
            "channel_original_name": "运营昵称",
            "package_version": 3,
            "playlist_name": "Revenge Stories",
            "playlist_id": "playlist-2",
            "playlists": [
                {"id": "playlist-1", "local_name": "Family Stories", "chinese_name": "家庭故事", "status": "active"},
                {"id": "playlist-2", "local_name": "Revenge Stories", "chinese_name": "复仇故事", "status": "active"},
                {"id": "playlist-3", "local_name": "CEO Romance", "chinese_name": None, "status": "active"},
            ],
            "description": {
                "localized_text": "Local description",
                "chinese_translation": "中文说明",
            },
        }
    )

    assert result["channel_secondary"] == ""
    assert result["version_label"] == "运营包版本 V3"
    assert result["playlist_name"] == "Revenge Stories"
    assert result["playlists"] == [
        {"name": "Family Stories", "chinese_name": "家庭故事", "selected": False, "status": "active"},
        {"name": "Revenge Stories", "chinese_name": "复仇故事", "selected": True, "status": "active"},
        {"name": "CEO Romance", "chinese_name": "", "selected": False, "status": "active"},
    ]
    assert result["localized_description"] == "Local description"
    assert result["chinese_description"] == "中文说明"


def test_package_summary_uses_work_orders_click_progress_and_logo_outputs() -> None:
    def package(
        package_id: str,
        *,
        source_complete: bool = True,
        image_clicks_complete: bool = False,
        copy_status: str = "in_progress",
        logos_complete: bool = False,
    ) -> dict:
        titles = [{"id": f"{package_id}-title-{variant}", "variant_number": variant} for variant in (1, 2, 3)]
        covers = [
            {
                "id": f"{package_id}-cover-{variant}-{ratio}",
                "title_id": f"{package_id}-title-{variant}",
                "aspect_ratio": ratio,
                "creative_prompt": f"prompt {variant} {ratio}",
                "asset_id": f"{package_id}-logo-{variant}" if logos_complete and ratio == "16:9" else None,
            }
            for variant in (1, 2, 3)
            for ratio in ("4:5", "16:9")
        ]
        community = [{"id": f"{package_id}-community-1", "image_prompt": "community prompt"}]
        copied_keys = []
        if image_clicks_complete:
            copied_keys = [f"cover:{cover['id']}" for cover in covers]
            copied_keys.append(f"community_image:{package_id}-community-1")
        media_assets = [
            {"id": f"{package_id}-logo-{variant}", "asset_role": "thumbnail", "status": "ready"}
            for variant in (1, 2, 3)
        ] if logos_complete else []
        return {
            "package_id": package_id,
            "source_complete": source_complete,
            "community_count": 1,
            "titles": titles,
            "covers": covers,
            "community_posts": community,
            "copied_keys": copied_keys,
            "copy_status": copy_status,
            "media_assets": media_assets,
        }

    result = summarize_packages(
        [
            package("gray", source_complete=False),
            package("drawn", image_clicks_complete=True),
            package("done", image_clicks_complete=True, copy_status="completed", logos_complete=True),
        ],
        total=4,
    )

    assert result == {
        "total": 4,
        "generated": 2,
        "images_completed": 2,
        "completed": 1,
    }


def test_package_summary_requires_all_six_cover_clicks_and_required_community_clicks() -> None:
    titles = [{"id": f"title-{variant}", "variant_number": variant} for variant in (1, 2, 3)]
    covers = [
        {"id": f"cover-{variant}-{ratio}", "title_id": f"title-{variant}", "aspect_ratio": ratio, "creative_prompt": "prompt"}
        for variant in (1, 2, 3)
        for ratio in ("4:5", "16:9")
    ]
    item = {
        "source_complete": True,
        "community_count": 1,
        "titles": titles,
        "covers": covers,
        "community_posts": [{"id": "community-1", "image_prompt": "prompt"}],
        "copied_keys": [f"cover:{cover['id']}" for cover in covers[:-1]],
        "copy_status": "in_progress",
        "media_assets": [],
    }

    assert summarize_packages([item], total=1)["images_completed"] == 0
