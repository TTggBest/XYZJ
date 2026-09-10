(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ZhijuRuntimeViewState = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function localDate(now = new Date()) {
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }

  function resetDateToToday(state, now = new Date()) {
    state.date = localDate(now);
    state.dateManuallySet = false;
  }

  function shouldShowScrollTop(scrollOffset, viewportHeight) {
    return Number(scrollOffset) > Number(viewportHeight);
  }

  return { localDate, resetDateToToday, shouldShowScrollTop };
});
