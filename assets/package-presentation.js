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

  function imageInspectionTarget(item) {
    if (item.source_complete !== true) return { package_id: item.package_id, kind: "card" };
    const copied = new Set(item.copied_keys || []);
    const titles = [...(item.titles || [])].sort((left, right) => left.variant_number - right.variant_number);
    const covers = item.covers || [];
    for (const title of titles) {
      for (const ratio of ["4:5", "16:9"]) {
        const cover = covers.find(row => row.title_id === title.id && row.aspect_ratio === ratio);
        if (!cover || !cover.creative_prompt) return { package_id: item.package_id, kind: "cover_module" };
        if (!copied.has(`cover:${cover.id}`)) return { package_id: item.package_id, kind: "output", output_type: "cover", output_id: cover.id };
      }
    }
    if (titles.length !== 3 || covers.length !== 6) return { package_id: item.package_id, kind: "cover_module" };
    const communityCount = Number(item.community_count || 0);
    const communities = [...(item.community_posts || [])].sort((left, right) => left.sequence_number - right.sequence_number);
    if (communities.length !== communityCount) return { package_id: item.package_id, kind: "community_module" };
    for (const post of communities) {
      if (!post.image_prompt) return { package_id: item.package_id, kind: "community_module" };
      if (!copied.has(`community_image:${post.id}`)) return { package_id: item.package_id, kind: "output", output_type: "community_image", output_id: post.id };
    }
    return null;
  }

  function copyInspectionTarget(item) {
    const copied = new Set(item.copied_keys || []);
    const titles = [...(item.titles || [])].sort((left, right) => left.variant_number - right.variant_number);
    for (const title of titles) {
      if (title.id && !copied.has(`title:${title.id}`)) return { package_id: item.package_id, kind: "output", output_type: "title", output_id: title.id };
    }
    const covers = item.covers || [];
    for (const title of titles) {
      for (const ratio of ["4:5", "16:9"]) {
        const cover = covers.find(row => row.title_id === title.id && row.aspect_ratio === ratio);
        if (cover?.creative_prompt && !copied.has(`cover:${cover.id}`)) return { package_id: item.package_id, kind: "output", output_type: "cover", output_id: cover.id };
      }
    }
    const description = item.description;
    if (description?.localized_text && !copied.has(`description:${description.id}`)) return { package_id: item.package_id, kind: "output", output_type: "description", output_id: description.id };
    const communities = [...(item.community_posts || [])].sort((left, right) => left.sequence_number - right.sequence_number);
    for (const post of communities) {
      if (post.localized_text && !copied.has(`community_text:${post.id}`)) return { package_id: item.package_id, kind: "output", output_type: "community_text", output_id: post.id };
      if (post.image_prompt && !copied.has(`community_image:${post.id}`)) return { package_id: item.package_id, kind: "output", output_type: "community_image", output_id: post.id };
    }
    return { package_id: item.package_id, kind: "card" };
  }

  function listPackageInspectionTargets(items, stage) {
    return (items || []).map(item => {
      if (stage === "generated") return item.source_complete === true ? null : { package_id: item.package_id, kind: "card" };
      const imageTarget = imageInspectionTarget(item);
      if (stage === "images") return imageTarget;
      if (stage !== "completed") return null;
      if (imageTarget) return imageTarget;
      if (item.copy_status !== "completed") return copyInspectionTarget(item);
      return packageLogosComplete(item) ? null : { package_id: item.package_id, kind: "logo" };
    }).filter(Boolean);
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

  function renderPackageProgressSummary(summary, current) {
    const values = [
      ["一共", summary.total, "is-total"],
      ["已生成", summary.generated, "is-generated"],
      ["已出图", summary.images_completed, "is-images"],
      ["已完成", summary.completed, "is-completed"],
      ["当前显示", current, "is-visible"],
    ];
    const stageByClass = { "is-generated": "generated", "is-images": "images", "is-completed": "completed" };
    const total = Number(summary.total || 0);
    return `<span class="package-progress-summary" id="packageProgressSummary" role="status" aria-label="运营包进度统计">${values.map(([label, value, className]) => {
      const stage = stageByClass[className];
      const content = `<span>${label}</span><strong>${Number(value || 0)}</strong>`;
      return stage && Number(value || 0) < total
        ? `<button class="package-progress-stat ${className}" type="button" data-action="inspect-package-progress" data-stage="${stage}" title="点击定位下一条未完成项">${content}</button>`
        : `<span class="package-progress-stat ${className}">${content}</span>`;
    }).join("")}</span>`;
  }

  return { buildPackagePresentation, summarizePackageProgress, renderPackageProgressSummary, listPackageInspectionTargets };
});
