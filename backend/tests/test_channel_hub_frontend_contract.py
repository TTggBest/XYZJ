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
