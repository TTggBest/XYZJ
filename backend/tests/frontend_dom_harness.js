// Minimal document boundary for the real app bootstrap; network is always a fixture.
const fs = require("node:fs");
const vm = require("node:vm");

function target(id = "") {
  const listeners = new Map(), classes = new Set();
  const item = { id, hidden: false, innerHTML: "", textContent: "", value: "", disabled: false, dataset: {}, style: {},
    classList: { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)), contains: name => classes.has(name), toggle: (name, force) => { const on = force ?? !classes.has(name); on ? classes.add(name) : classes.delete(name); return on; } },
    addEventListener: (name, listener) => { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(listener); },
    emit: async (name, event = {}) => { for (const fn of listeners.get(name) || []) await fn({ preventDefault() {}, target: item, ...event }); },
    setAttribute: (key, value) => { item[key] = value; }, getAttribute: key => item[key],
    focus() {}, reset() { Object.values(item.elements || {}).forEach(element => { element.value = ""; }); },
    querySelector: () => null, querySelectorAll: () => [], closest: () => null,
    appendChild() {}, remove() {}, getBoundingClientRect: () => ({ bottom: 0 }),
  };
  return item;
}

function start(root, auth, fetcher) {
  const nodes = new Map();
  for (const match of fs.readFileSync(root + "/index.html", "utf8").matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
    const item = target(match[1]); item.hidden = /\bhidden\b/.test(match[0]); nodes.set(item.id, item);
  }
  const document = Object.assign(target("document"), { visibilityState: "visible", getElementById: id => nodes.get(id), createElement: () => target(), body: target("body") });
  const window = Object.assign(target("window"), {
    ZhijuAuthState: auth, ZhijuAccountCenter: require(root + "/assets/account-center.js"),
    ZhijuRuntimeViewState: require(root + "/assets/runtime-view-state.js"), innerWidth: 1280, innerHeight: 800, scrollY: 0,
    location: { origin: "http://fixture" }, scrollTo() {}, scrollBy() {},
  });
  if (nodes.has("loginForm")) nodes.get("loginForm").elements = { login_name: nodes.get("loginName"), password: nodes.get("loginPassword") };
  const sandbox = { document, window, console, FormData, URLSearchParams, DOMException, AbortController, structuredClone, CSS: { escape: text => text },
    fetch: fetcher, localStorage: { getItem: () => null, setItem() {} }, navigator: {},
    requestAnimationFrame: fn => fn(), setTimeout: () => 1, clearTimeout() {},
  };
  vm.runInNewContext(fs.readFileSync(root + "/assets/app.js", "utf8"), sandbox);
  return { nodes, document, window, tick: () => new Promise(resolve => setImmediate(resolve)) };
}

module.exports = { start };
