const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function mount(page, extra) {
  const state = [], deps = [], effects = [];
  let index = 0;
  const react = {
    useState(initial) { const i = index++; if (!(i in state)) state[i] = typeof initial === "function" ? initial() : initial;
      return [state[i], value => { state[i] = typeof value === "function" ? value(state[i]) : value; }]; },
    useEffect(effect, next) { const i = index++; if (!deps[i] || next.some((value, j) => value !== deps[i][j])) {
      effects.push(() => { deps[i]?.cleanup?.(); const saved = [...next]; saved.cleanup = effect(); deps[i] = saved; });
    } },
    useMemo: fn => fn(),
  };
  const overrides = {
    react,
    "../components/CursorPagination": { CursorPagination: () => null },
    "../components/Notifications": { FloatingAlert: () => null },
    "../components/PortalHomeLink": { PortalHomeLink: () => null },
    "../components/GstReconciliation": { GstReconciliation: () => null },
    ...extra,
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "pages", `${page}.tsx`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  const anchor = { click() {}, remove() {} };
  vm.runInNewContext(compiled, { exports, Error, Date, Blob, window: { URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} } },
    document: { createElement: () => anchor, body: { appendChild() {} } },
    require: name => overrides[name] || require(name) });
  return () => { index = 0; const tree = exports[page](); effects.splice(0).forEach(effect => effect()); return tree; };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test("reports request full filtered transaction and journal exports", async () => {
  const calls = [];
  const api = {
    exportAccountTransactionsCsv: filters => { calls.push(["transactions", filters]); return Promise.resolve(new Blob()); },
    exportAccountJournalCsv: filters => { calls.push(["journal", filters]); return Promise.resolve(new Blob()); },
  };
  const render = mount("ReportsPage", { "../api": { api } });
  const tree = render();
  for (const label of ["Export Transactions", "Export Journal"]) {
    nodes(tree).find(node => node.type === "button" && node.props.children === label).props.onClick();
  }
  await flush();
  assert.equal(calls.length, 2);
  for (const [, filters] of calls) {
    assert.equal(filters.full, true);
    assert.match(filters.from_date, /^\d{4}-\d{2}-01$/);
    assert.match(filters.to_date, /^\d{4}-\d{2}-\d{2}$/);
  }
});

test("audit navigation carries date filters, resets cursors and ignores stale pages", async () => {
  const requests = [];
  const render = mount("AuditPage", { "../features/historyClient": { historyClient: {
    audit: filters => { const request = { ...deferred(), filters }; requests.push(request); return request.promise; },
  } } });
  let tree = render();
  requests[0].resolve({ items: [], next_cursor: "next" });
  await flush();
  tree = render();
  let pager = nodes(tree).find(node => node.props?.onNext);
  pager.props.onNext();
  tree = render();
  assert.equal(requests[1].filters.cursor, "next");
  const from = nodes(tree).find(node => node.type === "input" && node.props.type === "date");
  from.props.onChange({ target: { value: "2026-01-01" } });
  tree = render();
  assert.equal(requests[2].filters.cursor, null);
  assert.equal(requests[2].filters.from_date, "2026-01-01");
  requests[2].resolve({ items: [], next_cursor: null });
  requests[1].resolve({ items: [{ id: "stale" }], next_cursor: null });
  await flush();
  tree = render();
  assert.ok(!JSON.stringify(tree).includes("stale"));
  pager = nodes(tree).find(node => node.props?.onNext);
  assert.equal(pager.props.page, 0);
  assert.equal(pager.props.hasNext, false);
});
