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

  return { paginateGroups };
});
