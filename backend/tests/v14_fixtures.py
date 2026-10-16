def valid_market_payload():
    return {
        "schema_version": "1.0",
        "drama_id": "drama-1",
        "drama_title": "测试短剧",
        "searched_at": "2026-09-06T12:00:00+08:00",
        "search_status": "completed",
        "verified_market_angle_count": 1,
        "selection_context": {
            "channel_name": "频道甲",
            "channel_language": "印地",
            "channel_type": "豪门婚恋",
        },
        "search_window": {"primary": "recent_180d", "fallback": "none"},
        "market_videos": [
            {
                "market_video_id": "mv_001",
                "video_url": "https://www.youtube.com/watch?v=abcdefghijk",
                "video_title": "A market title",
                "channel_name": "Example Channel",
                "published_at": "2026-08-01",
                "views": 250000,
                "source_type": "external_youtube",
                "extracted_angle": "公开抛弃后当场改嫁",
                "extracted_visual_thesis": "婚礼现场女主转身选择另一位新郎",
                "fact_verification": {"status": "passed", "evidence": "剧情档案明确记录婚礼换新郎"},
                "eligible_for_angles": True,
                "evidence_freshness": "recent_180d",
            }
        ],
        "angle_candidates": [
            {
                "candidate_id": "candidate_001",
                "core_conflict": "婚礼公开抛弃与当场改嫁",
                "hook_a_fact": "未婚夫在婚礼当天离开",
                "hook_b_fact": "女主当场选择另一位新郎",
                "visual_moment": "女主从原新郎身边转向新郎的对手",
                "plot_evidence": "剧情档案明确记录该事件",
                "market_evidence_refs": ["mv_001"],
                "source_type": "external_market_verified",
                "market_confidence": "strong",
                "evidence_freshness": "recent_180d",
            }
        ],
        "final_angles": [
            {
                "angle_id": angle_id,
                "core_conflict": f"冲突{angle_id}",
                "hook_a_fact": f"A事实{angle_id}",
                "hook_b_fact": f"B事实{angle_id}",
                "visual_moment": f"视觉时刻{angle_id}",
                "plot_evidence": f"剧情证据{angle_id}",
                "market_evidence_refs": ["mv_001"] if angle_id == "A" else [],
                "channel_fit_reason": f"适合频道{angle_id}",
                "source_type": "external_market_verified" if angle_id == "A" else "story_derived",
                "market_confidence": "strong" if angle_id == "A" else "story_only",
                "evidence_freshness": "recent_180d" if angle_id == "A" else "none",
            }
            for angle_id in ("A", "B", "C")
        ],
        "fallback": {"used": True, "reason": "仅找到一个通过剧情核验的市场角度"},
    }
