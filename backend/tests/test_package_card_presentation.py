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


def render_summary(summary: dict, current: int) -> str:
    script = """
const presentation = require(process.argv[1]);
const summary = JSON.parse(process.argv[2]);
process.stdout.write(presentation.renderPackageProgressSummary(summary, Number(process.argv[3])));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "assets" / "package-presentation.js"),
            json.dumps(summary, ensure_ascii=False),
            str(current),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def inspection_targets(items: list[dict], stage: str) -> list[dict]:
    script = """
const presentation = require(process.argv[1]);
const items = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(presentation.listPackageInspectionTargets(items, process.argv[3])));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "assets" / "package-presentation.js"),
            json.dumps(items, ensure_ascii=False),
            stage,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def missing_image_targets(roles: list[str]) -> list[dict]:
    script = """
const presentation = require(process.argv[1]);
const roles = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(presentation.resolveMissingImageTargets(roles)));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "assets" / "package-presentation.js"),
            json.dumps(roles, ensure_ascii=False),
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


def test_package_summary_renders_distinct_semantic_badges() -> None:
    markup = render_summary(
        {"total": 53, "generated": 51, "images_completed": 27, "completed": 6},
        current=42,
    )

    assert 'id="packageProgressSummary"' in markup
    assert 'class="package-progress-stat is-total"' in markup
    assert 'class="package-progress-stat is-generated"' in markup
    assert 'class="package-progress-stat is-images"' in markup
    assert 'class="package-progress-stat is-completed"' in markup
    assert 'class="package-progress-stat is-visible"' in markup
    assert "<span>一共</span><strong>53</strong>" in markup
    assert "<span>已完成</span><strong>6</strong>" in markup
    assert "<span>当前显示</span><strong>42</strong>" in markup


def test_package_list_refreshes_summary_after_copy_and_on_demand() -> None:
    app_source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "renderPackageProgressSummary();" in app_source
    assert 'action === "refresh-package-summary"' in app_source
    assert 'data-action="clear-package-search"' in app_source


def test_package_search_filters_loaded_rows_without_refetching_the_database() -> None:
    app_source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function renderPackageListResults()" in app_source
    assert 'document.addEventListener("input", event =>' in app_source
    assert 'if (event.target.id === "packageSearch")' in app_source
    assert "renderPackageListResults();" in app_source
    assert 'if (event.target.id === "packageSearch") { state.packageSearch = event.target.value; await loadView("packages"); }' not in app_source


def test_package_summary_and_search_have_scoped_visual_styles() -> None:
    styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")

    assert ".package-progress-stat.is-total" in styles
    assert ".package-progress-stat.is-generated" in styles
    assert ".package-progress-stat.is-images" in styles
    assert ".package-progress-stat.is-completed" in styles
    assert ".package-progress-stat.is-visible" in styles
    assert ".package-search-control:focus-within" in styles


def test_package_filters_render_as_one_compact_responsive_toolbar() -> None:
    app_source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")

    assert 'class="package-filter-bar" role="search"' in app_source
    assert 'class="package-filter-item package-filter-search"' in app_source
    assert 'class="package-filter-item package-filter-date"' in app_source
    assert 'class="package-filter-item package-filter-channel"' in app_source
    assert 'class="package-filter-item package-filter-status"' in app_source
    assert 'class="button button-primary package-filter-sync"' in app_source
    assert app_source.index('id="packageSearch"') < app_source.index('id="packageDate"')
    assert ".package-filter-bar" in styles
    assert ".package-filter-item:focus-within" in styles
    assert "grid-template-areas" in styles
    assert '"search search" "date status" "channel channel" "sync sync"' in styles


def test_progress_inspection_finds_first_missing_cell_for_each_incomplete_package() -> None:
    complete_covers = [
        {
            "id": f"cover-{variant}-{ratio}",
            "title_id": f"title-{variant}",
            "aspect_ratio": ratio,
            "creative_prompt": "prompt",
            "asset_id": f"logo-{variant}" if ratio == "16:9" else None,
        }
        for variant in (1, 2, 3)
        for ratio in ("4:5", "16:9")
    ]
    titles = [{"id": f"title-{variant}", "variant_number": variant} for variant in (1, 2, 3)]
    image_keys = [f"cover:{cover['id']}" for cover in complete_covers]
    ready_assets = [{"id": f"logo-{variant}", "asset_role": "thumbnail", "status": "ready"} for variant in (1, 2, 3)]
    items = [
        {"package_id": "not-generated", "source_complete": False},
        {
            "package_id": "missing-cover-click",
            "source_complete": True,
            "titles": titles,
            "covers": complete_covers,
            "community_count": 0,
            "copied_keys": image_keys[:-1],
            "copy_status": "in_progress",
            "media_assets": ready_assets,
        },
        {
            "package_id": "missing-copy",
            "source_complete": True,
            "titles": titles,
            "covers": complete_covers,
            "community_count": 0,
            "copied_keys": image_keys,
            "copy_status": "in_progress",
            "description": {"id": "description-1", "localized_text": "description"},
            "media_assets": ready_assets,
        },
        {
            "package_id": "missing-logo",
            "source_complete": True,
            "titles": titles,
            "covers": complete_covers,
            "community_count": 0,
            "copied_keys": image_keys,
            "copy_status": "completed",
            "media_assets": ready_assets[:-1],
        },
    ]

    assert inspection_targets(items, "generated") == [
        {"package_id": "not-generated", "kind": "card"}
    ]
    assert inspection_targets(items, "images") == [
        {"package_id": "not-generated", "kind": "card"},
        {"package_id": "missing-cover-click", "kind": "output", "output_type": "cover", "output_id": "cover-3-16:9"},
    ]
    assert inspection_targets(items, "completed") == [
        {"package_id": "not-generated", "kind": "card"},
        {"package_id": "missing-cover-click", "kind": "output", "output_type": "cover", "output_id": "cover-3-16:9"},
        {"package_id": "missing-copy", "kind": "output", "output_type": "title", "output_id": "title-1"},
        {"package_id": "missing-logo", "kind": "logo"},
    ]


def test_completed_progress_badge_has_no_action_when_every_package_is_complete() -> None:
    incomplete = render_summary(
        {"total": 3, "generated": 2, "images_completed": 1, "completed": 0},
        current=3,
    )
    complete = render_summary(
        {"total": 3, "generated": 3, "images_completed": 3, "completed": 3},
        current=3,
    )

    assert 'data-action="inspect-package-progress" data-stage="generated"' in incomplete
    assert 'data-action="inspect-package-progress" data-stage="images"' in incomplete
    assert 'data-action="inspect-package-progress" data-stage="completed"' in incomplete
    assert 'data-action="inspect-package-progress"' not in complete


def test_missing_image_roles_map_to_their_exact_package_prompt_sections() -> None:
    assert missing_image_targets(["封面2", "社群1", "封面2", "未知图片"]) == [
        {"role": "封面2", "kind": "cover", "sequence": 2},
        {"role": "社群1", "kind": "community", "sequence": 1},
    ]


def test_progress_inspection_scrolls_and_highlights_without_writing_data() -> None:
    app_source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")

    assert 'action === "inspect-package-progress"' in app_source
    assert "listPackageInspectionTargets" in app_source
    assert "scrollIntoView({ behavior: \"smooth\", block: \"center\" })" in app_source
    assert ".is-inspection-target" in styles
