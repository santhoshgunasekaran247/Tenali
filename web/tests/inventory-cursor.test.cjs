const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");

function harness() {
  const states = [], refs = [], effects = [], requests = [], selections = [];
  let index = 0, pending = [];
  const react = { ...React,
    useState(initial) {
      const i = index++;
      if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
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
          effects[i]?.cleanup?.();
          effects[i] = { deps, cleanup: effect() };
        });
      }
    },
  };
  const CursorPagination = () => null;
  const empty = {items: []};
  const api = {
    inventoryProductPage: (...args) => new Promise((resolve, reject) => requests.push({args, resolve, reject})),
    inventoryProductIds: (...args) => new Promise((resolve, reject) => selections.push({args, resolve, reject})),
    inventoryLookups: async () => ({brands: [], categories: [], vendors: []}),
    hsnMasters: async () => empty, inventoryAlerts: async () => empty,
    inventoryReconciliation: async () => empty, inventoryMissingSources: async () => empty,
  };
  const overrides = {
    react,
    "../components/CursorPagination": {CursorPagination},
    "../features/drafts": {useDraftState: (_key, initial) => react.useState(initial)},
    "../features/auth": {useAuth: () => ({user: {role: "owner"}})},
    "../features/stores": {useStores: () => ({stockStores: [], stores: []})},
    "../features/postingKey": {postingKey: () => "key"},
    "../features/inventoryStockRows": {inventoryStockRows: () => []},
    "../api": {api},
    "react-router-dom": {useLocation: () => ({search: ""}), Link: () => null},
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "pages", "InventoryPage.tsx"), "utf8");
  const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {exports, URLSearchParams, require: name => overrides[name] || (name.startsWith(".") ? new Proxy({}, {get: () => () => null}) : require(name))});
  const render = () => {
    index = 0;
    const tree = exports.InventoryPage();
    const queued = pending; pending = []; queued.forEach(effect => effect());
    return tree;
  };
  const find = (node, predicate) => {
    if (!node || typeof node !== "object") return undefined;
    if (predicate(node)) return node;
    return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
  };
  return {render, find, requests, selections, CursorPagination};
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const product = id => ({id, name: id, is_active: true, variants: [], offers: [], stock_qty: 0});

test("product register retrieves pages, resets filters and selects all matching IDs", async () => {
  const h = harness();
  h.render(); await settle(); h.render();
  const initial = h.requests.at(-1);
  assert.equal(initial.args[0], 25);
  assert.equal(initial.args[1], null);
  initial.resolve({items: [product("first")], next_cursor: "next"});
  await settle();
  let tree = h.render();
  let controls = h.find(tree, node => node.type === h.CursorPagination).props;
  controls.onNext(); h.render();
  const next = h.requests.at(-1);
  assert.equal(next.args[1], "next");
  tree = h.render();
  const search = h.find(tree, node => node.type === "input" && node.props.type === "search");
  search.props.onChange({target: {value: "blue"}});
  h.render();
  const filtered = h.requests.at(-1);
  assert.equal(filtered.args[1], null);
  assert.equal(filtered.args[2], "blue");
  next.resolve({items: [product("stale")], next_cursor: null});
  filtered.resolve({items: [product("blue")], next_cursor: "more"});
  await settle();
  tree = h.render();
  assert.ok(h.find(tree, node => node.type === "button" && node.props["aria-label"] === "Open blue"));
  assert.equal(h.find(tree, node => node.type === "button" && node.props["aria-label"] === "Open stale"), undefined);
  const header = h.find(tree, node => node.type === "input" && node.props["aria-label"] === "Select all matching products across pages");
  header.props.onChange({target: {checked: true}});
  assert.equal(h.selections[0].args[1], "blue");
  h.selections[0].resolve({items: ["blue"], next_cursor: "ids-next"});
  await settle();
  assert.equal(h.selections[1].args[0], "ids-next");
  h.selections[1].resolve({items: ["second"], next_cursor: null});
  await settle();
  tree = h.render();
  assert.equal(h.find(tree, node => node.type === "input" && node.props["aria-label"] === "Select blue").props.checked, true);
  assert.equal(h.find(tree, node => node.type === "input" && node.props["aria-label"] === "Select all matching products across pages").props.checked, true);
  controls = h.find(tree, node => node.type === h.CursorPagination).props;
  controls.onSize(50); h.render();
  assert.equal(h.requests.at(-1).args[0], 50);
  assert.equal(h.requests.at(-1).args[1], null);
});
