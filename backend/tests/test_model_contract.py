from zhiju.models import Base


def test_foundation_tables_are_registered() -> None:
    assert {
        "devices",
        "google_accounts",
        "google_oauth_grants",
        "google_oauth_grant_scopes",
        "channels",
        "account_channel_authorizations",
        "authorization_events",
        "audit_events",
        "schema_comments",
        "media_assets",
        "channel_profiles",
        "channel_branding_assets",
        "channel_keywords",
        "channel_pinned_comment_templates",
        "channel_analysis_reports",
        "channel_analysis_topic_scores",
        "channel_analysis_keyword_scores",
        "channel_audience_profiles",
        "channel_strategy_recommendations",
        "channel_analysis_evidence",
        "channel_dna_versions",
        "channel_dna_signals",
        "integrations",
        "integration_accounts",
        "integration_credentials",
        "languages",
        "dramas",
        "drama_aliases",
        "drama_core_terms",
        "drama_translations",
        "channel_playlists",
        "channel_publish_slots",
        "channel_community_slots",
        "publish_cadence_template_slots",
        "channel_schedule_entries",
        "schedule_change_history",
        "schedule_candidates",
        "operation_tasks",
        "task_events",
        "work_orders",
        "operation_packages",
        "production_node_runs",
        "package_titles",
        "package_descriptions",
        "package_cover_variants",
        "package_community_posts",
        "community_post_assets",
        "package_playlist_assignments",
        "package_creative_slots",
        "package_artifacts",
        "package_validation_results",
        "package_similarity_checks",
        "package_output_copy_states",
        "system_events",
        "youtube_videos",
        "youtube_video_playlist_memberships",
        "youtube_playlist_order_history",
        "youtube_video_status_history",
        "youtube_comments",
        "youtube_comment_replies",
        "youtube_channel_daily_metrics",
        "youtube_video_daily_metrics",
        "youtube_analytics_breakdowns",
        "sync_watermarks",
        "api_request_logs",
        "quota_usage_logs",
        "skills",
        "skill_versions",
        "image_workspace_settings",
        "channel_logo_profiles",
        "image_processing_runs",
        "image_processing_items",
    }.issubset(Base.metadata.tables)


def test_every_foundation_column_has_a_chinese_comment() -> None:
    missing = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not column.comment:
                missing.append(f"{table.name}.{column.name}")
    assert missing == []


def test_tokens_are_not_database_columns() -> None:
    forbidden = {"access_token", "refresh_token", "password", "app_secret"}
    actual = {column.name for table in Base.metadata.sorted_tables for column in table.columns}
    assert forbidden.isdisjoint(actual)
