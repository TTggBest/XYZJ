(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZhijuOperationsPageData = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // A channel keeps its place when names, uploads or production status change.
  function sortChannels(channels) {
    return [...channels].sort((a, b) =>
      (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0)
      || String(a.channel_id).localeCompare(String(b.channel_id)));
  }

  function sortChannelRecords(items, channels) {
    const rank = new Map(sortChannels(channels).map((channel, index) => [channel.channel_id, index]));
    const channelKey = item => String(item.channel_id || item.channel_name || "");
    const time = item => String(item.planned_beijing_time || item.planned_utc_time || item.planned_local_time || item.target_publish_date || "9999");
    const identity = item => String(item.schedule_id || item.task_id || item.package_id || item.id || item.key || "");
    return [...items].sort((a, b) =>
      (rank.get(channelKey(a)) ?? channels.length) - (rank.get(channelKey(b)) ?? channels.length)
      || channelKey(a).localeCompare(channelKey(b))
      || time(a).localeCompare(time(b))
      || identity(a).localeCompare(identity(b)));
  }

  async function loadPackagePageData(request, productionDate) {
    const date = encodeURIComponent(productionDate);
    const [items, tasks] = await Promise.all([
      request(`/packages/operations-overview?production_date=${date}`),
      request(`/tasks/overview?task_date=${date}`),
    ]);
    return { items, workOrderTotal: tasks.length };
  }

  function workOrderSubtitle(tasks) {
    return `当天共 ${(tasks || []).length} 条工单 · 罗列需要生产运营包的剧目，并显示搜索、标题、封面、说明、社群、合成进度`;
  }

  return { loadPackagePageData, workOrderSubtitle, sortChannels, sortChannelRecords };
});
