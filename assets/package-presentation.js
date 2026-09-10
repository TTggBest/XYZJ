(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZhijuPackagePresentation = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function textOr(value, fallback) {
    const text = value == null ? "" : String(value).trim();
    return text || fallback;
  }

  function buildPackagePresentation(item) {
    const originalName = textOr(item.channel_original_name, "");
    const primaryName = textOr(item.channel_name, originalName || "未命名频道");
    const hasDistinctOriginal = Boolean(originalName && originalName !== primaryName);
    const channelSecondary = hasDistinctOriginal ? `原频道：${originalName}` : "";
    const description = item.description || {};
    const version = Number.isInteger(item.package_version) && item.package_version > 0
      ? item.package_version
      : 1;
    const playlists = Array.isArray(item.playlists) ? item.playlists.map(playlist => ({
      name: textOr(playlist.local_name, "未命名播放列表"),
      chinese_name: textOr(playlist.chinese_name, ""),
      selected: playlist.id === item.playlist_id || playlist.selected === true,
      status: textOr(playlist.status, "draft"),
    })) : [];

    return {
      channel_primary: primaryName,
      channel_secondary: channelSecondary,
      channel_title: hasDistinctOriginal
        ? `运营昵称：${primaryName}\n${channelSecondary}`
        : `频道：${primaryName}`,
      version_label: `运营包版本 V${version}`,
      playlist_name: textOr(item.playlist_name, "暂无播放列表"),
      playlists,
      localized_description: textOr(description.localized_text, "暂无频道语言说明"),
      chinese_description: textOr(description.chinese_translation, "暂无中文对照"),
    };
  }

  function packageImageClicksComplete(item) {
    if (item.source_complete !== true) return false;
    const copied = new Set(item.copied_keys || []);
    const covers = item.covers || [];
    const expectedPairs = new Set([
      "1:4:5", "1:16:9", "2:4:5", "2:16:9", "3:4:5", "3:16:9",
    ]);
    const actualPairs = new Set(covers.map(cover => {
      const title = (item.titles || []).find(row => row.id === cover.title_id);
      return `${title?.variant_number || ""}:${cover.aspect_ratio}`;
    }));
    const coversComplete = covers.length === 6
      && [...expectedPairs].every(pair => actualPairs.has(pair))
      && covers.every(cover => cover.creative_prompt && copied.has(`cover:${cover.id}`));
    if (!coversComplete) return false;

    const communityCount = Number(item.community_count || 0);
    const posts = item.community_posts || [];
    if (communityCount === 0) return true;
    return posts.length === communityCount
      && posts.every(post => post.image_prompt && copied.has(`community_image:${post.id}`));
  }

  function packageLogosComplete(item) {
    const readyAssets = new Set((item.media_assets || [])
      .filter(asset => asset.asset_role === "thumbnail" && asset.status === "ready")
      .map(asset => asset.id));
    const logoCovers = (item.covers || []).filter(cover => cover.aspect_ratio === "16:9");
    return logoCovers.length === 3
      && logoCovers.every(cover => cover.asset_id && readyAssets.has(cover.asset_id));
  }

  function summarizePackageProgress(items, total) {
    const generatedItems = (items || []).filter(item => item.source_complete === true);
    const imagesCompletedItems = generatedItems.filter(packageImageClicksComplete);
    return {
      total: Number(total || 0),
      generated: generatedItems.length,
      images_completed: imagesCompletedItems.length,
      completed: imagesCompletedItems.filter(item => item.copy_status === "completed" && packageLogosComplete(item)).length,
    };
  }

  return { buildPackagePresentation, summarizePackageProgress };
});
