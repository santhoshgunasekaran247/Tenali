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

function mountBilling() {
  const state = [], dependencies = [], effects = [], requests = {};
  let cursor = 0;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === "function" ? initial() : initial;
      return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!dependencies[index] || deps.some((dep, i) => dep !== dependencies[index][i])) {
        effects.push(() => {
          dependencies[index]?.cleanup?.();
          const saved = [...deps];
          saved.cleanup = effect();
          dependencies[index] = saved;
        });
      }
    },
  };
  const api = Object.fromEntries(["billingCustomers", "accounts", "hsnMasters", "inventoryProducts", "company", "invoices", "invoiceReconcileRuns"].map(name => [
    name, (...args) => {
      const request = { ...deferred(), args };
      (requests[name] ||= []).push(request);
      return request.promise;
    },
  ]));
  const component = () => null;
  const overrides = {
    react,
    "react-router-dom": { Link: component },
    "lucide-react": { Download: component },
    "../components/TaxLinesEditor": { TaxLinesEditor: component, newTaxLine: () => ({ quantity: "1", rate: "0", gst_rate: "0" }) },
    "../components/PortalHomeLink": { PortalHomeLink: component },
    "../api": { api },
    "../features/postingKey": { postingKey: () => "key" },
    "../features/taxTotals": { calculateLineTotals: () => ({ subtotal: 0, gstTotal: 0, total: 0 }) },
    "../features/stores": { StoreSelect: component, useStores: () => ({ stores: [], stockStores: [], selectedId: "", selected: null, error: "" }) },
    "../components/BillingCustomer": { BillingCustomer: component },
    "../components/Notifications": { FloatingAlert: component },
    "../features/drafts": { useDraftState: (_key, initial) => react.useState(initial) },
    "../features/invoiceReissue": { reissueInvoice: () => ({ form: {}, lines: [], sameShipping: true }) },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "pages", "BillingPage.tsx"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, Error, require: name => overrides[name] || require(name) });
  function render() {
    cursor = 0;
    const tree = exports.BillingPage();
    effects.splice(0).forEach(effect => effect());
    return tree;
  }
  render();
  return { requests, render };
}

function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test("customers render before inventory, invoices, or reconciliation finish; failures do not hide successful data", async () => {
  const { requests, render } = mountBilling();
  assert.equal(requests.invoiceReconcileRuns?.length, 1, "Audit request starts immediately, not after all other data");
  requests.billingCustomers[0].resolve({ items: [{ id: "customer-1", party_type: "customer" }] });
  await flush();
  const customerControl = nodes(render()).find(node => Array.isArray(node.props?.parties));
  assert.equal(customerControl.props.parties[0].id, "customer-1");

  requests.inventoryProducts[0].reject(new Error("Inventory unavailable"));
  await flush();
  const tree = render();
  assert.equal(nodes(tree).find(node => Array.isArray(node.props?.parties)).props.parties.length, 1);
  assert.ok(nodes(tree).some(node => String(node.props?.children).includes("Inventory unavailable")));
});

test("invoice filters and audit pagination fetch only their own data and ignore stale results", async () => {
  const { requests, render } = mountBilling();
  const filter = nodes(render()).find(node => node.type === "select" && nodes(node).some(child => child.props?.children === "All Collection Status"));
  filter.props.onChange({ target: { value: "UNPAID" } });
  render();
  assert.equal(requests.invoices.length, 2);
  assert.equal(requests.invoices[1].args[0].collection_status, "UNPAID");
  for (const name of ["billingCustomers", "company", "accounts", "hsnMasters", "inventoryProducts", "invoiceReconcileRuns"]) {
    assert.equal(requests[name].length, 1, `${name} must not refetch on invoice filter changes`);
  }
  requests.invoices[1].resolve({ items: [] });
  requests.invoices[0].resolve({ items: [{ id: "stale-invoice" }] });
  await flush();
  assert.ok(!JSON.stringify(render()).includes("stale-invoice"));

  requests.invoiceReconcileRuns[0].resolve({ items: [], total: 20 });
  await flush();
  const next = nodes(render()).find(node => node.type === "button" && String(node.props.children).includes("Next"));
  next.props.onClick();
  render();
  assert.equal(requests.invoiceReconcileRuns.length, 2);
  assert.equal(requests.invoiceReconcileRuns[1].args[1], 10);
  assert.equal(requests.invoices.length, 2);
  assert.equal(requests.billingCustomers.length, 1);
});
