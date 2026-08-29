from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_channel_detail_uses_structured_workspace() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function channelDetailBody" in source
    assert '["basic", "基础与装修"]' in source
    assert '["operations", "运营配置"]' in source
    assert '["analysis", "分析中心"]' in source
    assert '["reference", "运营参考"]' in source
    assert '["versions", "版本与规则"]' in source
    assert 'data-channel-detail-tab="${key}"' in source
    assert "JSON.stringify(data, null, 2)" not in source


def test_channel_identity_is_rendered_without_editable_inputs() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function channelHubForm" in source
    assert 'class="channel-hub-identity"' in source
    assert 'settingValue("频道名"' in source
    assert 'settingValue("YouTube Channel ID"' in source
    assert 'settingValue("频道地址"' in source
    assert 'id="channelHubForm"' in source


def test_channel_analysis_center_loads_structured_existing_data() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "async function loadChannelAnalysisCenter" in source
    assert "`/channels/${channelId}/analysis-reports`" in source
    assert "`/youtube/channel-daily-metrics${query({ channel_id: channelId })}`" in source
    assert "function channelAnalysisPanel" in source
    assert "用户画像" in source
    assert "策略建议" in source
    assert "频道日数据" in source


def test_channel_reference_loads_all_dna_versions() -> None:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "`/channels/${channelId}/dna-versions`" in source
    assert "function channelReferencePanel" in source
    assert "运营参考历史版本" in source
