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
      version_label: item.workflow_version
        ? `生产流程 ${item.workflow_version.label} · 修订 ${item.workflow_version.revision} / 产物 V${version}`
        : `运营包版本 V${version}`,
      playlist_name: textOr(item.playlist_name, "暂无播放列表"),
      playlists,
      localized_description: textOr(description.localized_text, "暂无频道语言说明"),
      chinese_description: textOr(description.chinese_translation, "暂无中文对照"),
    };
  }

  function packageLogosComplete(item) {
    const readyAssets = new Set((item.media_assets || [])
      .filter(asset => asset.asset_role === "thumbnail" && asset.status === "ready")
      .map(asset => asset.id));
    const logoCovers = (item.covers || []).filter(cover => cover.aspect_ratio === "16:9");
    return logoCovers.length === 3
      && logoCovers.every(cover => cover.asset_id && readyAssets.has(cover.asset_id));
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
    if (communityCount === 0) return true;
    const posts = item.community_posts || [];
    return posts.length === communityCount
      && posts.every(post => post.image_prompt && copied.has(`community_image:${post.id}`));
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

  function resolveMissingImageTargets(roles) {
    const seen = new Set();
    return (roles || []).map(value => {
      const role = textOr(value, "");
      const cover = /^封面([1-3])$/.exec(role);
      const community = /^社群([1-9]\d*)$/.exec(role);
      if (cover) return { role, kind: "cover", sequence: Number(cover[1]) };
      if (community) return { role, kind: "community", sequence: Number(community[1]) };
      return null;
    }).filter(target => {
      if (!target || seen.has(target.role)) return false;
      seen.add(target.role);
      return true;
    });
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

  function buildPackagesMarkdown(items, productionDate) {
    const heading = value => textOr(value, '未命名').replace(/\s+/g, ' ').replace(/([\\`*_{}\[\]<>#|])/g, '\\$1');
    const block = value => {
      const text = value == null || value === '' ? '暂无内容' : String(value);
      const fence = '`'.repeat(Math.max(3, ...[...text.matchAll(/`+/g)].map(match => match[0].length + 1)));
      return `${fence}text\n${text}\n${fence}`;
    };
    const time = (value, zone) => {
      if (!value) return '未设置';
      const date = new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
      const parts = Object.fromEntries(new Intl.DateTimeFormat('zh-CN', {timeZone:zone, hourCycle:'h23', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'}).formatToParts(date).map(part => [part.type, part.value]));
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
    };
    const lines = ['# 运营包汇总', '', `生产日期：${heading(productionDate)} · 已选 ${items.length} 个运营包`, '', '内容为导出时已加载的运营包文本；图片成品请在系统中查看或下载。', ''];
    const channels = new Map();
    for (const item of items) {
      const key = item.channel_id || item.channel_name;
      if (!channels.has(key)) channels.set(key, []);
      channels.get(key).push(item);
    }
    for (const group of channels.values()) {
      lines.push(`## 频道：${heading(group[0].channel_name || group[0].channel_original_name)}`, '');
      for (const item of group) {
        const presentation = buildPackagePresentation(item);
        lines.push(`### 剧目：${heading(item.chinese_title)}`, '', `- 剧目 ID：${heading(item.business_drama_id)}`, `- 运营包 ID：${heading(item.package_id)}`, `- 版本：${heading(presentation.version_label)}`, `- 批次：${heading(item.batch_number || '未分批')}`, `- 状态：${heading(item.package_status || '未标注')}`, `- 视频预约（北京时间）：${time(item.planned_utc_time, 'Asia/Shanghai')}`, `- 视频预约（频道当地 ${heading(item.channel_timezone || '未配置')}）：${item.channel_timezone ? time(item.planned_utc_time, item.channel_timezone) : '未配置时区'}`, `- Video ID：${heading(item.youtube_video_id || '未绑定')}`, '');
        if (item.youtube_video_id) lines.push(`视频链接：https://www.youtube.com/watch?v=${encodeURIComponent(item.youtube_video_id)}`, '');
        if (item.source_complete === false) lines.push(`> 数据不完整：${heading(item.source_incomplete_reason || '部分内容尚未同步或生成')}`, '');
        lines.push('#### 标题与封面提示词', '');
        const titles = [...(item.titles || [])].sort((a,b) => a.variant_number - b.variant_number);
        if (!titles.length) lines.push('暂无标题', '');
        for (const title of titles) {
          lines.push(`##### 标题 ${title.variant_number}`, '', '原标题', '', block(title.localized_title), '', '中文对照', '', block(title.chinese_translation), '', '核心词', '', block(title.core_phrase), '');
          const covers = (item.covers || []).filter(cover => cover.title_id === title.id);
          for (const cover of covers) lines.push(`封面 ${heading(cover.aspect_ratio)} 提示词`, '', block(cover.creative_prompt), '');
        }
        lines.push('#### 发布说明', '', '频道语言说明', '', block(item.description?.localized_text), '', '中文对照', '', block(item.description?.chinese_translation), '', '#### 播放列表', '');
        for (const playlist of presentation.playlists) lines.push(`- ${heading(playlist.name)}${playlist.chinese_name ? `（中文：${heading(playlist.chinese_name)}）` : ''}${playlist.selected ? ' · 本剧已选' : ''}`);
        if (!presentation.playlists.length) lines.push(heading(presentation.playlist_name));
        lines.push('', '#### 社群内容', '');
        const posts = [...(item.community_posts || [])].sort((a,b) => a.sequence_number - b.sequence_number);
        if (!posts.length) lines.push(item.community_count > 0 ? `社群待生成（${item.community_count} 套）` : '无需社群内容', '');
        for (const post of posts) lines.push(`##### 社群 ${post.sequence_number}`, '', `排期（北京时间）：${time(post.planned_utc_time, 'Asia/Shanghai')}`, '', '社群文案', '', block(post.localized_text), '', '中文对照', '', block(post.chinese_translation), '', '社群图提示词', '', block(post.image_prompt), '');
        lines.push('---', '');
      }
    }
    return lines.join('\n');
  }

  return { buildPackagesMarkdown, buildPackagePresentation, summarizePackageProgress, renderPackageProgressSummary, listPackageInspectionTargets, resolveMissingImageTargets };
});
