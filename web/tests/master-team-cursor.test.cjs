const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");

function compile(file, overrides) {
  const source = readFileSync(path.join(__dirname, "..", "src", file), "utf8");
  const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  vm.runInNewContext(code, {exports, URLSearchParams, require: name => overrides[name] || (name.startsWith(".") ? new Proxy({}, {get: () => () => null}) : require(name))});
  return exports;
}

function hooks() {
  const states = [], effects = [];
  let index = 0, pending = [];
  const react = {...React,
    useState(initial) {
      const i = index++;
      if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
      return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
    },
    useEffect(effect, deps) {
      const i = index++;
      if (!effects[i] || deps.some((value, j) => value !== effects[i].deps[j])) pending.push(() => {
        effects[i]?.cleanup?.();
        effects[i] = {deps, cleanup: effect()};
      });
    },
  };
  return {react, render(fn) { index = 0; const result = fn(); const queued = pending; pending = []; queued.forEach(effect => effect()); return result; }};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}

test("cursor state resets on search, size, scope and refresh; stale requests cannot win", async () => {
  const h = hooks(), requests = [];
  const module = compile("features/masterTeamPagination.ts", {react: h.react});
  const loader = (...args) => new Promise((resolve, reject) => requests.push({args, resolve, reject}));
  let resource = "brands", enabled = true;
  const render = () => h.render(() => module.useMasterTeamPage(resource, loader, enabled));
  render();
  assert.deepEqual(requests[0].args, ["brands", 25, null, ""]);
  requests[0].resolve({items: ["one"], next_cursor: "next"});
  await settle();
  let list = render();
  list.advance(); render();
  assert.deepEqual(requests[1].args, ["brands", 25, "next", ""]);
  list = render(); list.previous(); render();
  assert.deepEqual(requests[2].args, ["brands", 25, null, ""]);
  requests[2].resolve({items: ["one"], next_cursor: "next"}); await settle();
  list = render(); list.advance(); render();
  const stale = requests[3];
  list = render(); list.setSearch("blue"); render();
  assert.deepEqual(requests[4].args, ["brands", 25, null, "blue"]);
  requests[1].resolve({items: ["old"], next_cursor: null});
  stale.resolve({items: ["stale"], next_cursor: null});
  requests[4].resolve({items: ["blue"], next_cursor: "more"});
  await settle();
  list = render();
  assert.deepEqual(Array.from(list.items), ["blue"]);
  list.setSize(50); render();
  assert.deepEqual(requests[5].args, ["brands", 50, null, "blue"]);
  requests[5].resolve({items: ["fresh"], next_cursor: null}); await settle();
  list = render(); list.refresh(); render();
  assert.deepEqual(requests[6].args, ["brands", 50, null, "blue"]);
  resource = "categories";
  list = render(); assert.equal(list.items.length, 0);
  render();
  assert.deepEqual(requests[7].args, ["categories", 50, null, ""]);
  enabled = false; list = render(); assert.equal(list.items.length, 0);
  requests[7].resolve({items: ["hidden"], next_cursor: null}); await settle();
  assert.equal(render().items.length, 0);
});

test("focused clients encode pagination and search in tenant-aware requests", async () => {
  const calls = [];
  const module = compile("features/masterTeamPagination.ts", {
    "./tenantTransport": {tenantFetch: async url => { calls.push(url); return {ok: true, json: async () => ({items: [], next_cursor: null})}; }},
    "./auth": {authRequest: async url => { calls.push(url); return {items: [], next_cursor: null}; }},
  });
  await module.masterPage("brands", 25, "a+b", "red & blue");
  await module.teamPage("company", 10, null, "a@b");
  assert.equal(calls[0], "/api/inventory/lookups/brands?page_size=25&search=red+%26+blue&cursor=a%2Bb");
  assert.equal(calls[1], "/team?page_size=10&search=a%40b");
});

test("both screens refresh the server page after mutations and retain search controls", async () => {
  for (const screen of ["master", "team"]) {
    const h = hooks(), calls = [], refreshes = [];
    const list = {items: screen === "master" ? [{id: "1", name: "Brand", code: "B", description: null, is_active: true}] :
      [{id: "1", email: "u@example.test", display_name: "User", role: "staff", is_active: true, store_ids: null, modules: null}],
      error: "", loading: false, size: 25, page: 0, next: "next", search: "", refresh: () => refreshes.push(true),
      setSearch: value => calls.push(value), setSize() {}, previous() {}, advance() {}};
    const CursorPagination = () => null;
    const api = {stores: async () => ({items: []}), inventoryUpdateMaster: async () => { calls.push("updated"); }, inventoryCreateLookup: async () => { calls.push("created"); }};
    const authRequest = async url => { calls.push("updated", url); return {items: []}; };
    const overrides = {react: h.react, "../components/CursorPagination": {CursorPagination}, "../api": {api},
      "../features/drafts": {useDraftState: (_key, initial) => h.react.useState(initial)},
      "../features/auth": {useAuth: () => ({user: {role: "admin", company_id: "a"}}), authRequest},
      "../features/masterTeamPagination": {useMasterTeamPage: () => list, masterPage() {}, teamPage() {}},
      "react-router-dom": {Link: () => null}};
    const component = compile(`pages/${screen === "master" ? "InventoryMasterPage" : "TeamPage"}.tsx`, overrides);
    const render = () => h.render(() => screen === "master" ? component.InventoryMasterPage({kind: "brands"}) : component.TeamPage());
    const tree = render();
    assert.ok(find(tree, node => node.type === CursorPagination && node.props.size === 25));
    find(tree, node => node.type === "input" && node.props.type === "search").props.onChange({target: {value: "find"}});
    assert.ok(calls.includes("find"));
    find(tree, node => node.type === "button" && node.props["aria-label"] === (screen === "master" ? "Deactivate Brand" : "Deactivate u@example.test")).props.onClick();
    await settle();
    assert.equal(refreshes.length, 1);
    assert.ok(calls.includes("updated"));
    const after = render();
    find(after, node => node.type === "form").props.onSubmit({preventDefault() {}});
    await settle();
    assert.equal(refreshes.length, 2);
    if (screen === "team") assert.ok(calls.filter(value => typeof value === "string" && value.includes("return_team=false")).length === 2);
  }
});
