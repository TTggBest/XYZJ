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

  return { filterGroups, nextIncompleteGroup, paginateGroups };
});
