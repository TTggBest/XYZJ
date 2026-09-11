(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZhijuOperationsPageData = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

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

  return { loadPackagePageData, workOrderSubtitle };
});
