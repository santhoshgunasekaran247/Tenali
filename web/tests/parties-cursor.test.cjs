const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");

function harness(online) {
  const states = [], effects = [], requests = [], writes = [];
  let index = 0, pending = [];
  const react = { ...React,
    useState(initial) {
      const i = index++;
      if (!(i in states)) states[i] = initial;
      return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
    },
    useMemo(fn) { return fn(); },
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
  const PartySelect = () => null;
  const page = (...args) => new Promise((resolve, reject) => requests.push({ args, resolve, reject }));
  const api = {
    billingCustomers: async () => ({ items: [{ id: "counter" }] }),
    updateParty: async (...args) => writes.push(["update", ...args]),
    createParty: async (...args) => writes.push(["create", ...args]),
  };
  const overrides = {
    react,
    "../components/CursorPagination": { CursorPagination }, "./CursorPagination": { CursorPagination },
    "../components/Notifications": { FloatingAlert: () => null }, "./Notifications": { FloatingAlert: () => null },
    "../features/partiesPagination": { contactsPage: page, onlineCustomersPage: page },
    "../features/shop": { accountRequest: async (...args) => { writes.push(args); return {}; } },
    "../features/drafts": { useDraftState: (_key, initial) => react.useState(initial) },
    "../features/auth": { useAuth: () => ({ user: { role: "admin" } }) },
    "../components/SiteFooter": { SiteFooter: () => null },
    "../components/PortalHomeLink": { PortalHomeLink: () => null },
    "react-router-dom": { Link: () => null },
    "../api": { api },
    "./PartySelect": { PartySelect },
  };
  const filename = online ? "components\\OnlineCustomerLinks.tsx" : "pages\\PartiesPage.tsx";
  const source = readFileSync(path.join(__dirname, "..", "src", filename), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => overrides[name] || require(name), window: { scrollTo() {} }, URLSearchParams });
  const render = () => {
    index = 0;
    const tree = online ? exports.OnlineCustomerLinks() : exports.PartiesPage();
    const queued = pending; pending = []; queued.forEach(effect => effect());
    return tree;
  };
  const findAll = (node, predicate) => {
    if (!node || typeof node !== "object") return [];
    return [...(predicate(node) ? [node] : []), ...React.Children.toArray(node.props?.children).flatMap(child => findAll(child, predicate))];
  };
  const controls = tree => findAll(tree, node => node.type === CursorPagination)[0].props;
  const button = (tree, label) => findAll(tree, node => node.type === "button" && node.props.children === label)[0];
  return { render, findAll, controls, button, requests, writes, PartySelect };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

for (const online of [false, true]) {
  test(`${online ? "online customers" : "contacts"} fetch server pages, reset filters, and ignore stale responses`, async () => {
    const h = harness(online);
    h.render();
    assert.deepEqual(h.requests[0].args, online ? ["", 25, null] : ["", true, 25, null]);
    h.requests[0].resolve({ items: [], next_cursor: "next" }); await settle();
    let tree = h.render();
    h.controls(tree).onNext(); h.render();
    assert.equal(h.requests[1].args.at(-1), "next");
    tree = h.render();
    const search = h.findAll(tree, node => node.type === "input" && node.props.placeholder?.startsWith(online ? "Name" : "Search"))[0];
    search.props.onChange({ target: { value: "sam" } }); h.render();
    assert.equal(h.requests[2].args[0], "sam");
    assert.equal(h.requests[2].args.at(-1), null);
    h.requests[1].resolve({ items: [], next_cursor: "stale" }); await settle();
    assert.equal(h.controls(h.render()).busy, true);
    h.requests[2].resolve({ items: [], next_cursor: "fresh" }); await settle();
    tree = h.render();
    assert.equal(h.controls(tree).page, 0);
    h.controls(tree).onNext(); h.render();
    assert.equal(h.requests[3].args.at(-1), "fresh");
    h.requests[3].reject(new Error("network")); await settle();
    tree = h.render();
    assert.equal(h.controls(tree).hasNext, false);
    h.button(tree, "Retry").props.onClick(); h.render();
    h.requests[4].resolve({ items: [], next_cursor: null }); await settle();
    tree = h.render(); h.controls(tree).onPrevious(); h.render();
    assert.equal(h.requests[5].args.at(-1), null);
    h.requests[5].resolve({ items: [], next_cursor: "again" }); await settle();
    tree = h.render(); h.controls(tree).onSize(50); h.render();
    assert.equal(h.requests[6].args.at(-2), 50);
    assert.equal(h.requests[6].args.at(-1), null);
    h.requests[6].resolve({ items: [], next_cursor: null }); await settle();
    tree = h.render(); h.button(tree, "Reset filters").props.onClick(); h.render();
    assert.equal(h.requests[7].args[0], "");
    assert.equal(h.requests[7].args.at(-1), null);
  });
}

test("online link refreshes the current server page", async () => {
  const h = harness(true);
  h.render(); h.requests[0].resolve({ items: [{ id: "shopper", display_name: "Sam", email: "s@example.com", phone: null, customer_party_id: null }], next_cursor: null });
  await settle();
  let tree = h.render(); h.button(tree, "Link manually").props.onClick(); tree = h.render();
  h.findAll(tree, node => node.type === h.PartySelect)[0].props.onChange("counter");
  tree = h.render();
  h.findAll(tree, node => node.type === "input" && node.props.type === "checkbox")[0].props.onChange({ target: { checked: true } });
  tree = h.render(); h.button(tree, "Confirm link").props.onClick(); await settle(); h.render();
  assert.equal(h.writes[0][0], "/online-customers/shopper/link");
  assert.equal(h.requests.length, 2);
});

test("editing a contact updates it and reloads the first page", async () => {
  const h = harness(false);
  h.render(); h.requests[0].resolve({ items: [], next_cursor: "second" }); await settle();
  let tree = h.render(); h.controls(tree).onNext(); h.render();
  h.requests[1].resolve({ items: [{ id: "p1", legal_name: "Sam", nickname: "", party_type: "customer", is_active: true }], next_cursor: null });
  await settle();
  tree = h.render(); h.button(tree, "Edit").props.onClick(); tree = h.render();
  const form = h.findAll(tree, node => node.type === "form")[0];
  await form.props.onSubmit({ preventDefault() {} });
  h.render();
  assert.equal(h.writes[0][0], "update");
  assert.equal(h.writes[0][1], "p1");
  assert.equal(h.requests[2].args.at(-1), null);
});

test("dedicated requests encode filters and cursor without changing dropdown API", async () => {
  const calls = [];
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "partiesPagination.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, URLSearchParams, require: () => ({ accountRequest: (...args) => { calls.push(args); } }) });
  exports.contactsPage(" A&B ", false, 50, "x+/=");
  exports.onlineCustomersPage(" sam@example.com ", 25, null);
  assert.equal(calls[0][0], "?active_only=false&page_size=50&search=A%26B&cursor=x%2B%2F%3D");
  assert.equal(calls[1][0], "/online-customers?page_size=25&search=sam%40example.com");
  assert.equal(calls[0][2], "parties");
});
