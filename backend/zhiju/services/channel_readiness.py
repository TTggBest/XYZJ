"""Read local channel materials; authorization alone does not mean production is ready."""
from sqlalchemy import select

from zhiju.models import ChannelPlaylist, ChannelProfile, ChannelPinnedCommentTemplate
from zhiju.models.v14 import V14Setting


def production_material_issues(session, channel, material=None):
    if material is None:
        setting = session.scalar(select(V14Setting))
        material = (setting.payload.get("channel_inputs", {}).get(channel.id) if setting else None) or {}
    issues = []
    profile = session.scalar(select(ChannelProfile).where(ChannelProfile.channel_id == channel.id))
    if profile is None:
        issues.append("频道基础资料")
    if profile is None or not profile.title_template:
        issues.append("标题模板")
    if profile is None or not profile.fixed_symbol:
        issues.append("固定符号")
    pinned = set(session.scalars(select(ChannelPinnedCommentTemplate.language).where(
        ChannelPinnedCommentTemplate.channel_id == channel.id,
        ChannelPinnedCommentTemplate.status == "active",
        ChannelPinnedCommentTemplate.body != "",
    )))
    for language in dict.fromkeys([channel.default_language, "zh-CN"]):
        if language and language not in pinned:
            issues.append(f"置顶回复（{language}）")
    for key, label in (("language", "生产材料语言"), ("generation_spec", "生成规范"),
                       ("description_fixed_assets", "说明固定资料"),
                       ("channel_hashtag_whitelist", "hashtag 白名单"),
                       ("community_footer_cta", "社群固定资料")):
        if not material.get(key):
            issues.append(label)
    configured = material.get("playlists") or []
    pools = list(session.scalars(select(ChannelPlaylist).where(
        ChannelPlaylist.channel_id == channel.id, ChannelPlaylist.status == "active")))
    if not configured:
        issues.append("生产配置播放列表")
    if not pools:
        issues.append("频道播放列表")
    for row in configured:
        name, url = row.get("name"), row.get("url")
        match = next((p for p in pools if p.local_name == name and p.url == url and url), None)
        if match is None:
            issues.append(f"播放列表关联：{name or '未命名'}")
        elif not match.local_description:
            issues.append(f"播放列表说明：{name}")
    return issues
