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

  return { buildPackagePresentation };
});
