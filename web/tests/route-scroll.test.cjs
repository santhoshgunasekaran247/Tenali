const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function harness() {
  let location = { pathname: "/portal/billing", hash: "", search: "" };
  const scrolls = [], sections = new Map(), observers = [], hooks = [];
  let cursor = 0;
  const history = { scrollRestoration: "auto" };
  const effect = (callback, deps) => {
    const i = cursor++;
    if (!hooks[i] || deps.some((dep, j) => dep !== hooks[i].deps[j])) {
      hooks[i]?.cleanup?.();
      hooks[i] = { deps, cleanup: callback() };
    }
  };
  const exports = {};
  const source = readFileSync(path.join(__dirname, "..", "src", "components", "RouteScroll.tsx"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(compiled, {
    exports,
    require: name => name === "react"
      ? { useEffect: effect, useLayoutEffect: effect }
      : { useLocation: () => location },
    window: { history, scrollTo: options => scrolls.push(options) },
    document: { body: {}, getElementById: id => sections.get(id) },
    MutationObserver: class {
      constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
      observe() {}
      disconnect() { this.disconnected = true; }
    },
  });
  return {
    history, scrolls, sections, observers,
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
  const calls = [];
  h.sections.set("company-profile", { scrollIntoView: options => calls.push(options) });
  h.render({ pathname: "/portal/company", hash: "#company-profile", search: "" });
  assert.equal(calls.length, 1);
  assert.equal(h.observers.length, 0);
  h.render({ pathname: "/", hash: "#categories", search: "" });
  h.sections.set("categories", { scrollIntoView: options => calls.push(options) });
  h.observers[0].callback();
  assert.equal(calls.length, 2);
  assert.equal(h.observers[0].disconnected, true);
});

test("leaving a page cancels pending section scrolling", () => {
  const h = harness();
  h.render({ pathname: "/portal/company", hash: "#missing", search: "" });
  h.render({ pathname: "/portal/billing", hash: "", search: "" });
  assert.equal(h.observers[0].disconnected, true);
});
