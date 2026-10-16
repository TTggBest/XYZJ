from copy import deepcopy

import pytest


def envelope(count=1):
    from zhiju.v14_runtime.contract import bundled_rules
    return {"run_id": "r1", "model": "test-model", "rules_snapshot": bundled_rules(),
        "input_snapshot": {"channel_id": "c1", "channel_name": "频道", "drama_id": "d1", "drama_name": "剧目",
            "community_count": count, "target_publish_date": "2026-10-20",
            "drama": {"content_summary": "女主重生复仇", "plot_archive": "剧情档案", "plot_pattern": "复仇", "core_personas": "女主"},
            "channel": {"language": "阿拉伯语", "gender": "女频", "direction": "复仇",
                "generation_spec": "## [GLOBAL]\n通用规则\n## [TITLE]\n标题规则\n## [COVER]\n封面专用秘密\n## [DESCRIPTION]\n描述\n## [HASHTAG]\n标签\n## [COMMUNITY]\n社群\n## [PLAYLIST]\n列表\n",
                "description_fixed_assets": {"disclaimer": "声明"},
                "community_footer_cta": {"full_video_cta": "观看", "subscribe_cta": "订阅", "share_cta": "分享", "layout_style": "样式"},
                "playlists": [{"name": "剧集", "url": "https://www.youtube.com/playlist?list=PL123"}],
                "channel_hashtag_whitelist": {"selection_count": 12, "mandatory_hashtags": ["#cdrama"], "additional_candidates": [f"#tag{n}" for n in range(1, 12)], "target_language_tags": ["#tag1"]}}},
        "accepted_results": {"search": {"market_payload": {"final_angles": [{"angle_id": n} for n in ("A", "B", "C")]}}, "title": {"results": [{"packaging_brief": {"creative_slot_id": "r1"}}]}},
        "creative_history": [], "retry_state": []}


def test_missing_channel_rules_fail_before_model():
    from zhiju.v14_runtime.contract import build_stage_input
    e = envelope()
    e["input_snapshot"]["channel"]["generation_spec"] = ""
    with pytest.raises(ValueError, match="generation_spec"):
        build_stage_input(e, "title")


def test_title_only_receives_global_and_title_sections():
    from zhiju.v14_runtime.contract import build_stage_input
    stage = build_stage_input(envelope(), "title")
    assert "通用规则" in stage.prompt
    assert "标题规则" in stage.prompt
    assert "封面专用秘密" not in stage.prompt


def test_downstream_inherits_packaging_brief():
    from zhiju.v14_runtime.contract import build_stage_input
    e = envelope()
    e["accepted_results"]["title"] = {"results": [{"packaging_brief": {"packaging_brief_id": "brief-1", "core_story_promise": "真实承诺"}}]}
    stage = build_stage_input(e, "cover")
    assert "brief-1" in stage.prompt and "真实承诺" in stage.prompt


@pytest.mark.parametrize("count", [0, 1, 2])
def test_community_count_zero_one_two(count):
    from zhiju.v14_runtime.contract import build_stage_input
    stage = build_stage_input(envelope(count), "community")
    assert stage.schema["properties"]["results"]["minItems"] == count
    assert stage.schema["properties"]["results"]["maxItems"] == count


def test_full_evidence_and_json_are_retained():
    from zhiju.v14_runtime.contract import build_stage_input
    e = envelope()
    e["accepted_results"]["search"] = {"plot_payload": {"results": [{"plot_fields": {"内容概述": "真剧情"}}]},
        "market_payload": {"final_angles": [{"angle_id": n, "hook": "完整证据"} for n in ("A", "B", "C")]}, "external_evidence": {"videos": [{"video_url": "https://youtube.com/watch?v=abcdefghijk"}]}}
    original = deepcopy(e)
    assert "完整证据" in build_stage_input(e, "title").prompt
    assert e == original


def test_description_requires_cloud_channel_hashtag_assets():
    from zhiju.v14_runtime.contract import build_stage_input
    e = envelope()
    e["input_snapshot"]["channel"]["channel_hashtag_whitelist"] = {}
    with pytest.raises(ValueError, match="hashtag"):
        build_stage_input(e, "description")


def test_blank_video_id_uses_pending_link_contract():
    from zhiju.v14_runtime.contract import build_stage_input
    stage = build_stage_input(envelope(), "community")
    assert stage.item["video_id"].startswith("pending_")


def test_current_v14_does_not_restore_legacy_theme_keyword_gate():
    from zhiju.v14_runtime.contract import build_stage_input
    from zhiju.v14_runtime.canonical import channel_theme_alignment_issues
    e = envelope()
    e["input_snapshot"]["channel"]["direction"] = "萌宝家庭"
    e["input_snapshot"]["drama"]["content_summary"] = "孩子和母亲重逢"
    stage = build_stage_input(e, "cover")
    result = {"results": [{"titles": [{"title_index": 1, "story_hook": "成人关系发生变化"}]}]}
    assert channel_theme_alignment_issues("xy-cover", result, stage.context) == []
