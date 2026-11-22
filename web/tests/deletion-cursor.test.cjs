const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");

function harness() {
  const states = [], refs = [], effects = [], requests = [];
  let index = 0, pending = [];
  const react = { ...React,
    useState(initial) {
      const i = index++;
      if (!(i in states)) states[i] = initial;
      return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
    },
    useRef(initial) {
      const i = index++;
      if (!(i in refs)) refs[i] = { current: initial };
      return refs[i];
    },
    useEffect(effect, deps) {
      const i = index++;
      if (!effects[i] || deps.some((value, j) => value !== effects[i].deps[j])) {
        pending.push(() => {
          if (effects[i]?.cleanup) effects[i].cleanup();
          effects[i] = { deps, cleanup: effect() };
        });
      }
    },
  };
  const CursorPagination = () => null;
  const overrides = {
    react,
    "./CursorPagination": { CursorPagination },
    "./Notifications": { FloatingAlert: () => null },
    "../features/auth": { useAuth: () => ({ user: { role: "admin", company_id: "company" } }) },
    "../features/deletions": { canDeleteTransactions: () => true },
    "./DeleteTransactionDialog": { DeleteTransactionDialog: () => null },
    "../api": { api: { deletionHistory: (size, cursor) => new Promise((resolve, reject) => requests.push({ size, cursor, resolve, reject })) } },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "components", "TransactionDeletionPanel.tsx"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => overrides[name] || require(name) });
  const render = () => {
    index = 0;
    const tree = exports.TransactionDeletionPanel();
    const queued = pending; pending = []; queued.forEach(effect => effect());
    return tree;
  };
  const find = node => {
    if (!node || typeof node !== "object") return undefined;
    if (node.type === CursorPagination) return node;
    return React.Children.toArray(node.props?.children).map(find).find(Boolean);
  };
  return { render, find, requests };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test("deletion history fetches pages, resets size, and ignores stale responses", async () => {
  const h = harness();
  h.render();
  assert.equal(h.requests[0].size, 25);
  h.requests[0].resolve({ items: [], next_cursor: "page-two" });
  await settle();
  let controls = h.find(h.render()).props;
  assert.equal(controls.hasNext, true);
  controls.onNext();
  h.render();
  assert.equal(h.requests[1].cursor, "page-two");
  controls = h.find(h.render()).props;
  assert.equal(controls.busy, true);
  controls.onSize(50);
  h.render();
  assert.equal(h.requests[2].size, 50);
  assert.equal(h.requests[2].cursor, null);
  h.requests[1].resolve({ items: [], next_cursor: "stale" });
  await settle();
  assert.equal(h.find(h.render()).props.busy, true);
  h.requests[2].resolve({ items: [], next_cursor: "fresh" });
  await settle();
  controls = h.find(h.render()).props;
  assert.equal(controls.page, 0);
  assert.equal(controls.hasNext, true);
  controls.onNext(); h.render();
  assert.equal(h.requests[3].cursor, "fresh");
  h.requests[3].reject(new Error("network error"));
  await settle();
  controls = h.find(h.render()).props;
  assert.equal(controls.hasNext, false);
  assert.equal(controls.busy, false);
  controls.onPrevious(); h.render();
  assert.equal(h.requests[4].cursor, null);
});
