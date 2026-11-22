const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");

const settle = () => new Promise(resolve => setImmediate(resolve));
const row = id => ({id, invoice_id: "invoice", party_name: id, reference: id,
  amount_due: 100, amount_received: 0, balance_amount: 100, status: "UNPAID"});

function harness(query = "") {
  const states = [], refs = [], effects = [], requests = [], mutations = [];
  let index = 0, pending = [];
  const react = {...React,
    useState(initial) {
      const i = index++;
      if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
      return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
    },
    useRef(initial) {
      const i = index++;
      if (!(i in refs)) refs[i] = {current: initial};
      return refs[i];
    },
    useEffect(effect, deps) {
      const i = index++;
      if (!effects[i] || deps.some((value, j) => value !== effects[i].deps[j])) {
        pending.push(() => { effects[i]?.cleanup?.(); effects[i] = {deps, cleanup: effect()}; });
      }
    },
  };
  const CursorPagination = () => null;
  const request = (kind, filters, id) => new Promise((resolve, reject) => requests.push({kind, filters, id, resolve, reject}));
  const api = {parties: async () => ({items: []}), accounts: async () => ({items: []}),
    markReceivableReminder: async (...args) => { mutations.push(args); }};
  const mocks = {
    react, "../api": {api},
    "../features/receivablesClient": {receivablesClient: {
      ledger: filters => {
        assert.ok(filters.page_size, "receivable reads must always be bounded");
        if (filters.invoice_id || filters.receivable_id) return request("resolution", filters);
        if ("search" in filters) return request("selection", filters);
        return request("ledger", filters);
      },
      due: filters => request("due", filters), history: (id, filters) => request("history", filters, id),
    }},
    "../components/CursorPagination": {CursorPagination},
    "../features/drafts": {useDraftState: (_key, initial) => react.useState(initial)},
    "react-router-dom": {useSearchParams: () => [new URLSearchParams(query)]},
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "pages", "ReceivablesPage.tsx"), "utf8");
  const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  vm.runInNewContext(code, {exports, URLSearchParams, require: name => mocks[name] ||
    (name.startsWith(".") ? new Proxy({}, {get: () => () => null}) : require(name))});
  function render() {
    index = 0;
    const tree = exports.ReceivablesPage();
    const queued = pending; pending = []; queued.forEach(effect => effect());
    return tree;
  }
  function all(node, predicate) {
    if (!node || typeof node !== "object") return [];
    return [...(predicate(node) ? [node] : []),
      ...React.Children.toArray(node.props?.children).flatMap(child => all(child, predicate))];
  }
  return {render, requests, mutations, all, setQuery: value => { query = value; }, latest: kind => requests.filter(r => r.kind === kind).at(-1),
    selectionControls: tree => all(tree, node => node.type === CursorPagination)[0].props,
    controls: (tree, i) => all(tree, node => node.type === CursorPagination)[i + 1].props};
}

test("ledger defaults to all-age open balances and keeps explicit invoice/status deep links", async () => {
  const h = harness("invoice_id=invoice&store_id=store");
  h.render(); h.render();
  assert.equal(h.latest("ledger").filters.open_only, true);
  assert.equal(h.latest("ledger").filters.from_date, undefined);
  assert.equal(h.latest("ledger").filters.store_id, "store");
  h.latest("ledger").resolve({items: [row("first")], next_cursor: "ledger-next"});
  h.latest("due").resolve({items: []});
  assert.equal(h.latest("resolution").filters.invoice_id, "invoice");
  assert.equal(h.latest("resolution").filters.page_size, 1);
  assert.equal(h.latest("resolution").filters.open_only, undefined);
  h.latest("resolution").resolve({items: [row("selection")]});
  await settle(); h.render(); await settle();
  let tree = h.render();
  const selector = h.all(tree, node => node.type === "select" && node.props.value === "selection")[0];
  assert.ok(selector, "invoice selection survives filtering the ledger");
  h.controls(tree, 0).onNext(); h.render();
  assert.equal(h.latest("ledger").filters.cursor, "ledger-next");
  tree = h.render(); h.controls(tree, 0).onPrevious(); h.render();
  assert.equal(h.latest("ledger").filters.cursor, null);
  for (const status of ["UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT", "OPEN"]) {
    const linked = harness(`invoice_id=invoice&status=${status}`);
    linked.render(); await settle(); linked.render();
    assert.equal(linked.latest("ledger").filters.open_only, status === "OPEN");
    assert.equal(linked.latest("ledger").filters.status, status === "OPEN" ? undefined : status);
  }
});

test("due pages reset date and size, reject stale loads, and retain reminder drafts", async () => {
  const h = harness();
  h.render(); h.render();
  h.latest("ledger").resolve({items: []});
  h.latest("due").resolve({items: [row("first")], next_cursor: "due-next"});
  await settle();
  let tree = h.render();
  const reminderRow = h.all(tree, node => node.type === "tr" && node.key?.includes("r-first"))[0];
  h.all(reminderRow, node => node.type === "input")[0].props.onChange({target: {value: "2026-12-01"}});
  // Navigate using the server cursor; a page-size change must invalidate that response.
  tree = h.render(); h.controls(tree, 1).onNext(); h.render();
  const stale = h.latest("due");
  assert.equal(stale.filters.cursor, "due-next");
  tree = h.render(); h.controls(tree, 1).onSize(50); h.render();
  const fresh = h.latest("due");
  assert.equal(fresh.filters.cursor, null); assert.equal(fresh.filters.page_size, 50);
  stale.resolve({items: [row("stale")], next_cursor: "wrong"});
  fresh.resolve({items: [row("fresh")], next_cursor: null});
  await settle(); tree = h.render();
  assert.equal(h.all(tree, node => node.type === "td" && node.props.children === "stale").length, 0);
  assert.equal(h.controls(tree, 1).hasNext, false);
  const dueDate = h.all(tree, node => node.type === "label" && React.Children.toArray(node.props.children)[0] === "Due as of (blank = today)")[0].props.children[1];
  dueDate.props.onChange({target: {value: "2026-12-31"}}); h.render();
  assert.equal(h.latest("due").filters.as_of, "2026-12-31");
  assert.equal(h.latest("due").filters.cursor, null);
});

test("mark reminded keeps its mutation payload and refreshes server pages", async () => {
  const h = harness();
  h.render(); h.render(); h.latest("ledger").resolve({items: []});
  h.latest("due").resolve({items: [row("first")], next_cursor: null});
  await settle();
  let tree = h.render();
  const reminderRow = h.all(tree, node => node.type === "tr" && node.key?.includes("r-first"))[0];
  h.all(reminderRow, node => node.type === "input")[0].props.onChange({target: {value: "2026-12-01"}});
  tree = h.render();
  h.all(tree, node => node.type === "button" && node.props.children === "Mark reminded")[0].props.onClick();
  await settle();
  assert.equal(h.mutations[0][0], "first");
  assert.equal(h.mutations[0][1].next_reminder_date, "2026-12-01");
  assert.equal(h.mutations[0][1].reminded_by, "operations_user");
  h.latest("ledger").resolve({items: []});
  await settle();
  assert.equal(h.requests.filter(r => r.kind === "due").length, 2);
  h.latest("due").resolve({items: []});
  await settle();
  tree = h.render();
  assert.equal(h.controls(tree, 1).busy, false);
});

test("history keeps applied filters across Next/Previous and resets on selection", async () => {
  const h = harness("store_id=store");
  h.render(); h.render();
  h.latest("ledger").resolve({items: [row("first"), row("second")]});
  h.latest("due").resolve({items: []});
  await settle();
  let tree = h.render();
  h.all(tree, node => node.type === "button" && node.props.children === "Reminder history")[0].props.onClick(); h.render();
  assert.equal(h.latest("history").id, "first");
  assert.equal(h.latest("history").filters.page_size, 25);
  h.latest("history").resolve({items: [], next_cursor: "history-next"});
  await settle(); tree = h.render();
  h.all(tree, node => node.type === "input" && node.props.placeholder === "Reminded by")[0].props.onChange({target: {value: "ops"}});
  tree = h.render();
  h.all(tree, node => node.type === "button" && node.props.children === "Apply")[0].props.onClick(); h.render();
  assert.equal(h.latest("history").filters.reminded_by, "ops");
  assert.equal(h.latest("history").filters.cursor, null);
  h.latest("history").resolve({items: [], next_cursor: "filtered-next"});
  await settle(); tree = h.render();
  h.controls(tree, 2).onNext(); h.render();
  assert.equal(h.latest("history").filters.cursor, "filtered-next");
  assert.equal(h.latest("history").filters.reminded_by, "ops");
  assert.equal(h.latest("history").filters.store_id, "store");
  const stale = h.latest("history");
  tree = h.render();
  h.all(tree, node => node.type === "button" && node.props.children === "Reminder history")[1].props.onClick(); h.render();
  const latest = h.latest("history");
  assert.equal(latest.id, "second"); assert.equal(latest.filters.cursor, null);
  stale.resolve({items: [{id: "stale", reminded_at: "stale"}]});
  latest.resolve({items: [{id: "fresh", reminded_at: "fresh"}]});
  await settle(); tree = h.render();
  assert.equal(h.all(tree, node => node.type === "td" && node.props.children === "stale").length, 0);
  h.controls(tree, 2).onSize(100); h.render();
  assert.equal(h.latest("history").filters.page_size, 100);
  assert.equal(h.latest("history").filters.cursor, null);
});

test("dedicated read client uses tenant transport and serializes pagination/filter values", async () => {
  const calls = [];
  let failure = false;
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "receivablesClient.ts"), "utf8");
  const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022}}).outputText;
  const exports = {};
  vm.runInNewContext(code, {exports, URLSearchParams, require: name => {
    if (name === "../api") return {API_BASE: "/api"};
    if (name === "./tenantTransport") return {tenantFetch: async (...args) => {
      calls.push(args);
      return {ok: !failure, status: 422, json: async () => ({items: [], next_cursor: "next"}),
        text: async () => JSON.stringify({detail: [{loc: ["query", "page_size"], msg: "Invalid size"}]})};
    }};
    throw new Error(`Unexpected module: ${name}`);
  }});
  const client = exports.receivablesClient;
  const page = await client.ledger({page_size: 50, cursor: "a+b=", open_only: true, store_id: "store"});
  assert.equal(page.next_cursor, "next");
  const url = new URL(calls[0][0], "https://example.com");
  assert.equal(url.pathname, "/api/collections/receivables");
  assert.equal(url.searchParams.get("cursor"), "a+b=");
  assert.equal(url.searchParams.get("open_only"), "true");
  assert.equal(url.searchParams.get("store_id"), "store");
  assert.equal(calls[0][1].headers["Content-Type"], "application/json");
  await client.due({page_size: 25, as_of: "2026-12-31"});
  assert.match(calls[1][0], /as_of=2026-12-31/);
  await client.history("id/with slash", {page_size: 10, reminded_by: "ops"});
  assert.match(calls[2][0], /id%2Fwith%20slash\/reminders/);
  failure = true;
  await assert.rejects(client.due({page_size: 0}), /query.page_size: Invalid size/);
});

test("searchable collection choices page independently, preserve selection, and discard stale searches", async () => {
  const h = harness("store_id=store");
  h.render(); h.render();
  const initial = h.latest("selection");
  assert.equal(initial.filters.page_size, 25);
  assert.equal(initial.filters.open_only, true);
  assert.equal(initial.filters.from_date, undefined);
  initial.resolve({items: [row("older-open")], next_cursor: "selection-next"});
  h.latest("ledger").resolve({items: [row("ledger")], next_cursor: "ledger-next"});
  h.latest("due").resolve({items: []});
  await settle();
  let tree = h.render();
  const select = h.all(tree, node => node.type === "select" && node.props.required && node.props.value === "")[0];
  select.props.onChange({target: {value: "older-open"}});
  h.render(); h.latest("resolution").resolve({items: [row("older-open")]});
  await settle(); tree = h.render();
  const beforePaging = h.requests.filter(r => r.kind === "selection").length;
  h.controls(tree, 0).onNext(); h.render();
  assert.equal(h.requests.filter(r => r.kind === "selection").length, beforePaging, "ledger paging must not reload choices");
  tree = h.render();
  h.selectionControls(tree).onNext(); h.render();
  assert.equal(h.latest("selection").filters.cursor, "selection-next");
  const stale = h.latest("selection");
  tree = h.render();
  h.all(tree, node => node.type === "input" && node.props.type === "search")[0].props.onChange({target: {value: "old invoice"}});
  h.render();
  const fresh = h.latest("selection");
  assert.equal(fresh.filters.search, "old invoice");
  assert.equal(fresh.filters.cursor, null);
  stale.resolve({items: [row("stale")]});
  fresh.resolve({items: [row("matched")], next_cursor: null});
  await settle(); tree = h.render();
  assert.ok(h.all(tree, node => node.type === "option" && node.props.value === "older-open")[0], "selected choice stays pinned");
  assert.equal(h.all(tree, node => node.type === "option" && node.props.value === "stale").length, 0);
  h.selectionControls(tree).onSize(50); h.render();
  assert.equal(h.latest("selection").filters.page_size, 50);
  assert.equal(h.latest("selection").filters.cursor, null);
});

test("changing an invoice deep link discards its older targeted resolution", async () => {
  const h = harness("invoice_id=old");
  h.render(); h.render();
  const stale = h.latest("resolution");
  h.setQuery("invoice_id=new"); h.render();
  const current = h.latest("resolution");
  assert.equal(current.filters.invoice_id, "new");
  stale.resolve({items: [row("wrong")]});
  current.resolve({items: [row("beyond-first-page")]});
  await settle();
  const tree = h.render();
  assert.ok(h.all(tree, node => node.type === "select" && node.props.value === "beyond-first-page")[0]);
  assert.equal(h.all(tree, node => node.type === "option" && node.props.value === "wrong").length, 0);
});
