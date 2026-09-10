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
