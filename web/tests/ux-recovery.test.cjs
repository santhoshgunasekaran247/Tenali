const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function compile(file, mocks = {}) {
  const source = readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require: name => mocks[name] || require(name), Intl, Date });
  return exports;
}

test("transfer date uses the India calendar across the UTC day boundary", () => {
  const { indiaDateKey } = compile("features/workflowDates.ts");
  assert.equal(indiaDateKey(new Date("2026-03-31T18:29:59Z")), "2026-03-31");
  assert.equal(indiaDateKey(new Date("2026-03-31T18:30:00Z")), "2026-04-01");
});

function draftHarness() {
  const slots = [];
  let cursor = 0, pending = [], fail = false, calls = 0;
  const react = { ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useEffect(effect, deps) {
      const index = cursor++, old = slots[index];
      if (!old || deps.some((value, i) => value !== old.deps[i])) {
        if (old?.cleanup) old.cleanup();
        slots[index] = { deps };
        pending.push(() => { slots[index].cleanup = effect(); });
      }
    },
  };
  const ai = {
    drafts: async () => { calls++; if (fail) throw new Error("offline"); return { items: [] }; },
    workflows: async () => ({ items: [] }),
  };
  const mocks = {
    react,
    "../features/ai": { ai, hasDuplicateDraft: () => false },
    "../api": { api: {} },
    "react-router-dom": { Link: ({ children }) => children },
    "./Notifications": { FloatingAlert: ({ children }) => React.createElement("div", null, children) },
    "./WorkflowReference": {},
  };
  const { AIDrafts } = compile("components/AIDrafts.tsx", mocks);
  return {
    render() {
      cursor = 0;
      const tree = AIDrafts({ conversationId: "one", refreshKey: 0, writable: true, aiEnabled: false });
      const effects = pending; pending = []; effects.forEach(effect => effect());
      return tree;
    },
    fail(value) { fail = value; },
    get calls() { return calls; },
  };
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test("draft history distinguishes loading, failure, retry and genuine emptiness", async () => {
  const h = draftHarness();
  h.fail(true);
  let tree = h.render();
  assert.match(renderToStaticMarkup(tree), /Loading saved workflows and drafts/);
  assert.doesNotMatch(renderToStaticMarkup(tree), /No workflows or drafts/);
  await flush();
  tree = h.render();
  assert.match(renderToStaticMarkup(tree), /Could not load saved workflows and drafts/);
  assert.doesNotMatch(renderToStaticMarkup(tree), /No workflows or drafts/);
  h.fail(false);
  find(tree, node => node.type === "button" && node.props.children === "Retry drafts").props.onClick();
  h.render();
  tree = h.render();
  assert.match(renderToStaticMarkup(tree), /Loading saved workflows and drafts/);
  await flush();
  tree = h.render();
  assert.match(renderToStaticMarkup(tree), /No workflows or drafts to review/);
  assert.equal(h.calls, 2);
});

test("bad debt requires a reason and acknowledgement before submitting the selected record", async () => {
  const slots = [], requests = [];
  let cursor = 0;
  const receivable = { id: "r1", party_name: "Customer", reference: "INV-1",
    amount_due: 100, amount_received: 0, balance_amount: 100, status: "UNPAID" };
  const react = { ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = index === 2 ? [receivable] : typeof initial === "function" ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef: value => ({ current: value }), useEffect: () => {}, useMemo: fn => fn(),
  };
  const api = {
    updateReceivable: async (id, payload) => { requests.push({ id, payload }); },
    parties: async () => ({ items: [] }), accounts: async () => ({ items: [] }),
    receivables: async () => ({ items: [] }), dueReceivableReminders: async () => ({ items: [] }),
  };
  const mocks = {
    react, "../api": { api },
    "../components/PaginatedTableBody": { PaginatedTableBody: "tbody" },
    "react-router-dom": { useSearchParams: () => [new URLSearchParams()] },
    "../features/drafts": { useDraftState: (_key, initial) => [typeof initial === "function" ? initial() : initial, () => {}] },
    "../components/Notifications": { FloatingAlert: () => null },
    "../components/PartySelect": { PartySelect: () => null },
    "../components/PortalHomeLink": { PortalHomeLink: () => null },
  };
  const { ReceivablesPage } = compile("pages/ReceivablesPage.tsx", mocks);
  const render = () => { cursor = 0; return ReceivablesPage(); };
  let tree = render();
  find(tree, node => node.type === "button" && node.props.children === "Mark bad debt").props.onClick();
  tree = render();
  let dialog = find(tree, node => node.type === "dialog");
  let submit = find(dialog, node => node.type === "button" && node.props.type === "submit");
  assert.equal(submit.props.disabled, true);
  find(dialog, node => node.type === "textarea").props.onChange({ target: { value: "  Customer insolvent  " } });
  tree = render(); dialog = find(tree, node => node.type === "dialog");
  assert.equal(find(dialog, node => node.type === "button" && node.props.type === "submit").props.disabled, true);
  find(dialog, node => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } });
  tree = render(); dialog = find(tree, node => node.type === "dialog");
  submit = find(dialog, node => node.type === "button" && node.props.type === "submit");
  assert.equal(submit.props.disabled, false);
  find(dialog, node => node.type === "form").props.onSubmit({ preventDefault() {} });
  await flush();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].id, "r1");
  assert.equal(requests[0].payload.status, "BAD_DEBT");
  assert.equal(requests[0].payload.bad_debt_reason, "Customer insolvent");
  assert.equal(find(render(), node => node.type === "dialog"), undefined);
});
