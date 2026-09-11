(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ZhijuMediaGallery = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function paginateGroups(groups, requestedPage, pageSize) {
    const total = groups.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(Math.max(1, requestedPage), totalPages);
    const start = (page - 1) * pageSize;
    return {
      items: groups.slice(start, start + pageSize),
      page,
      totalPages,
      total,
    };
  }

  function filterGroups(groups, filters = {}) {
    return groups.filter(group => {
      const channelKey = group.meta.channel_id || group.meta.channel_name;
      if (filters.language && group.meta.language_code !== filters.language) return false;
      if (filters.channel && channelKey !== filters.channel) return false;
      if (filters.status === "complete" && group.complete !== true) return false;
      if (filters.status === "incomplete" && group.complete !== false) return false;
      return true;
    });
  }

  function nextIncompleteGroup(groups, currentPackageId = "") {
    const incomplete = groups.filter(group => group.complete === false);
    if (!incomplete.length) return null;
    const currentIndex = incomplete.findIndex(group => group.meta.package_id === currentPackageId);
    return incomplete[(currentIndex + 1) % incomplete.length];
  }

  function filterImportFiles(files) {
    return Array.from(files || []).filter(file => {
      const basename = String(file.name || "").split(/[\\/]/).pop();
      return basename !== ".DS_Store";
    });
  }

  async function loadRunHistory(request, options = {}) {
    const expanded = options.expanded === true;
    const pageSize = expanded ? (options.pageSize || 10) : 1;
    const page = expanded ? Math.max(1, Number(options.page) || 1) : 1;
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
    });
    if (options.batchId) params.set("batch_id", options.batchId);
    const result = await request(`/image-processing/runs/history?${params.toString()}`);
    const total = Number(result.total || 0);
    return {
      total,
      items: result.items || [],
      page,
      totalPages: expanded ? Math.max(1, Math.ceil(total / pageSize)) : 1,
    };
  }

  return { filterGroups, filterImportFiles, loadRunHistory, nextIncompleteGroup, paginateGroups };
});
