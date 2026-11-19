const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function compile(...segments) {
  return ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", ...segments), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
}

function harness({ headerHeight = 96, headerPosition = "sticky", scrollY = 0 } = {}) {
  let location = { pathname: "/portal/billing", hash: "", search: "" };
  const scrolls = [], sections = new Map(), observers = [], resizeObservers = [], timers = [], listeners = new Map(), hooks = [];
  let cursor = 0;
  const history = { scrollRestoration: "auto" };
  const effect = (callback, deps) => {
    const i = cursor++;
    if (!hooks[i] || deps.some((dep, j) => dep !== hooks[i].deps[j])) {
      hooks[i]?.cleanup?.();
      hooks[i] = { deps, cleanup: callback() };
    }
  };
  const header = { getBoundingClientRect: () => ({ height: headerHeight }) };
  const window = {
    history, scrollY,
    scrollTo: options => scrolls.push(options),
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name, fn) => { if (listeners.get(name) === fn) listeners.delete(name); },
  };
  const context = {
    window,
    document: { body: {}, getElementById: id => sections.get(id), querySelector: selector => selector === ".header" ? header : null },
    getComputedStyle: () => ({ position: headerPosition }),
    setTimeout: fn => { timers.push(fn); return timers.length; },
    clearTimeout: () => undefined,
    MutationObserver: class {
      constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
      observe() {}
      disconnect() { this.disconnected = true; }
    },
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; this.disconnected = false; resizeObservers.push(this); }
      observe() {}
      disconnect() { this.disconnected = true; }
    },
  };
  const sectionScroll = {};
  vm.runInNewContext(compile("components", "sectionScroll.ts"), { ...context, exports: sectionScroll });
  const exports = {};
  vm.runInNewContext(compile("components", "RouteScroll.tsx"), {
    ...context,
    exports,
    require: name => name === "react"
      ? { useEffect: effect, useLayoutEffect: effect }
      : name === "./sectionScroll" ? sectionScroll : { useLocation: () => location },
  });
  return {
    history, scrolls, sections, observers, resizeObservers, timers, listeners, window,
    section(id, top) { const section = { top, getBoundingClientRect: () => ({ top: section.top }) }; sections.set(id, section); return section; },
    render(next = location) { location = next; cursor = 0; exports.RouteScroll(); },
    unmount() { hooks.forEach(hook => hook.cleanup?.()); },
  };
}

test("page navigation starts at the top immediately, including browser back navigation", () => {
  const h = harness();
  h.render();
  h.render({ pathname: "/portal/masters/hsn", hash: "", search: "" });
  h.render({ pathname: "/portal/billing", hash: "", search: "" });
  assert.equal(h.scrolls.length, 3);
  assert.ok(h.scrolls.every(scroll => scroll.top === 0 && scroll.left === 0 && scroll.behavior === "instant"));
  assert.equal(h.history.scrollRestoration, "manual");
  h.unmount();
  assert.equal(h.history.scrollRestoration, "auto");
});

test("changing only query filters does not disturb the current scroll position", () => {
  const h = harness();
  h.render();
  h.render({ pathname: "/portal/billing", hash: "", search: "?status=UNPAID" });
  assert.equal(h.scrolls.length, 1);
});

test("section links work on the same page and after asynchronous content loads", () => {
  const h = harness();
  h.section("company-profile", 500);
  h.render({ pathname: "/portal/company", hash: "#company-profile", search: "" });
  assert.deepEqual({ ...h.scrolls.at(-1) }, { top: 404, left: 0, behavior: "instant" });
  assert.equal(h.observers.length, 0);
  h.render({ pathname: "/", hash: "#categories", search: "" });
  h.section("categories", 900);
  h.observers[0].callback();
  assert.equal(h.scrolls.at(-1).top, 804);
  assert.equal(h.observers[0].disconnected, true);
});

test("sections land directly below the sticky header and stay there while the page settles", () => {
  const h = harness({ headerHeight: 82, scrollY: 1000 });
  const specials = h.section("sru-specials", 300);
  h.render({ pathname: "/", hash: "#sru-specials", search: "" });
  assert.equal(h.scrolls.at(-1).top, 1218);
  specials.top = 520;
  h.resizeObservers[0].callback();
  assert.equal(h.scrolls.at(-1).top, 1438);
  h.timers[0]();
  assert.equal(h.resizeObservers[0].disconnected, true);
  assert.equal(h.listeners.size, 0);
});

test("the shopper scrolling stops section re-alignment immediately", () => {
  const h = harness();
  h.section("brands", 700);
  h.render({ pathname: "/", hash: "#brands", search: "" });
  const count = h.scrolls.length;
  h.listeners.get("wheel")();
  h.resizeObservers[0].callback();
  assert.equal(h.scrolls.length, count);
  assert.equal(h.resizeObservers[0].disconnected, true);
});

test("a non-sticky header adds no offset", () => {
  const h = harness({ headerPosition: "static" });
  h.section("contact", 640);
  h.render({ pathname: "/", hash: "#contact", search: "" });
  assert.equal(h.scrolls.at(-1).top, 640);
});

test("leaving a page cancels pending section scrolling", () => {
  const h = harness();
  h.render({ pathname: "/portal/company", hash: "#missing", search: "" });
  h.render({ pathname: "/portal/billing", hash: "", search: "" });
  assert.equal(h.observers[0].disconnected, true);
});
