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
  const api = Object.fromEntries(["billingCustomers", "accounts", "hsnMasters", "inventoryProducts", "company", "invoices", "invoiceReconcileRuns", "quotations"].map(name => [
    name, (...args) => {
      const request = { ...deferred(), args };
      (requests[name] ||= []).push(request);
      return request.promise;
    },
  ]));
  const component = () => null;
  const overrides = {
    react,
    "../components/PaginatedTableBody": { PaginatedTableBody: "tbody" },
    "../components/CursorPagination": { CursorPagination: () => null },
    "react-router-dom": { Link: component },
    "lucide-react": { Download: component },
    "../components/TaxLinesEditor": { TaxLinesEditor: component, newTaxLine: () => ({ quantity: "1", rate: "0", gst_rate: "0" }) },
    "../components/PortalHomeLink": { PortalHomeLink: component },
    "../api": { api },
    "../features/historyClient": { historyClient: {
      invoices: (...args) => { const request = { ...deferred(), args }; (requests.filteredInvoices ||= []).push(request); return request.promise; },
      quotations: (...args) => { const request = { ...deferred(), args }; (requests.filteredQuotations ||= []).push(request); return request.promise; },
      reconcileCsv: (...args) => { const request = { ...deferred(), args }; (requests.reconcileCsv ||= []).push(request); return request.promise; },
      salesRegisterCsv: (...args) => { const request = { ...deferred(), args }; (requests.salesRegisterCsv ||= []).push(request); return request.promise; },
    } },
    "../features/postingKey": { postingKey: () => "key" },
    "../features/workflowDates": { indiaDateKey: () => "2026-03-25" },
    "../features/taxTotals": { calculateLineTotals: () => ({ subtotal: 0, gstTotal: 0, total: 0 }) },
    "../features/stores": { StoreSelect: component, useStores: () => ({ stores: [], stockStores: [], selectedId: "", selected: null, error: "" }) },
    "../components/BillingCustomer": { BillingCustomer: component },
    "../components/Notifications": { FloatingAlert: component },
    "../features/drafts": { useDraftState: (_key, initial) => react.useState(initial) },
    "../features/invoiceReissue": { reissueInvoice: () => ({ form: {}, lines: [], sameShipping: true }) },
    "../features/auth": { useAuth: () => ({ user: { role: "owner" } }) },
    "../features/deletions": { canDeleteTransactions: () => true },
    "../components/DeleteTransactionDialog": { DeleteTransactionDialog: component },
    "../components/CancelDocumentDialog": { CancelDocumentDialog: component },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "pages", "BillingPage.tsx"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const link = { click() {} };
  vm.runInNewContext(compiled, { exports, Error, Date, URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
    document: { createElement: () => link, body: { appendChild() {}, removeChild() {} } },
    require: name => overrides[name] || require(name) });
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

test("billing keeps quotations, invoices and audit stacked beside the creation form", () => {
  const { render } = mountBilling();
  const layout = nodes(render()).find(node => node.props?.className === "ops-grid billing-layout");
  assert.ok(layout);
  const [create, records] = layout.props.children;
  assert.match(create.props.className, /billing-create-card/);
  assert.equal(records.props.className, "billing-records");
  const cards = records.props.children.filter(Boolean);
  assert.deepEqual(Array.from(cards, card => card.props["aria-labelledby"]), [
    "billing-quotations-heading", "billing-invoices-heading", "billing-audit-heading",
  ]);
  assert.equal(nodes(records).filter(node => node.type === "table").length, 3);
  assert.ok(nodes(records).some(node => node.props?.["aria-label"] === "Collection status"));
});

test("history ranges default to all time and reset paging with independent server filters", () => {
  const { requests, render } = mountBilling();
  let tree = render();
  const range = label => nodes(tree).find(node => node.props?.label === label && node.props?.value?.preset);
  assert.equal(range("Invoice").props.value.preset, "all");
  assert.equal(range("Quotation").props.value.preset, "all");
  range("Invoice").props.onChange({ preset: "custom", from: "", to: "" });
  tree = render();
  assert.equal(requests.filteredInvoices, undefined);
  range("Invoice").props.onChange({ preset: "custom", from: "2026-01-01", to: "2026-01-31" });
  tree = render();
  assert.equal(requests.filteredInvoices[0].args[0].from_date, "2026-01-01");
  assert.equal(requests.filteredInvoices[0].args[0].to_date, "2026-01-31");
  assert.equal(requests.filteredInvoices[0].args[0].cursor, null);
  range("Quotation").props.onChange({ preset: "today", from: "", to: "" });
  tree = render();
  assert.equal(requests.filteredQuotations[0].args[0].from_date, requests.filteredQuotations[0].args[0].to_date);
  assert.equal(requests.filteredInvoices.length, 1);
  range("Quotation").props.onChange({ preset: "month", from: "", to: "" });
  tree = render();
  assert.match(requests.filteredQuotations[1].args[0].from_date, /^\d{4}-\d{2}-01$/);
  assert.equal(requests.filteredQuotations[1].args[0].to_date.slice(0, 7), requests.filteredQuotations[1].args[0].from_date.slice(0, 7));
  range("Invoice").props.onChange({ preset: "all", from: "", to: "" });
  render();
  assert.equal(requests.invoices.length, 2);
});

test("reconcile export requests complete CSV even when the displayed page is empty", async () => {
  const { requests, render } = mountBilling();
  requests.invoiceReconcileRuns[0].resolve({ items: [], total: 0 });
  await flush();
  let tree = render();
  const button = nodes(tree).find(node => node.type === "button" && String(node.props.children).includes("Export CSV"));
  assert.ok(button);
  button.props.onClick();
  tree = render();
  assert.equal(requests.reconcileCsv.length, 1);
  assert.equal(requests.reconcileCsv[0].args.length, 0);
  assert.equal(nodes(tree).find(node => node.type === "button" && String(node.props.children).includes("Export CSV")).props.disabled, true);
  requests.reconcileCsv[0].reject(new Error("Export failed"));
  await flush();
  assert.ok(JSON.stringify(render()).includes("Export failed"));
});

test("sales register exports the visible invoice date, status and store filters", () => {
  const { requests, render } = mountBilling();
  let tree = render();
  nodes(tree).find(node => node.props?.["aria-label"] === "Collection status").props.onChange({ target: { value: "PARTIAL" } });
  tree = render();
  nodes(tree).find(node => node.props?.["aria-label"] === "History store").props.onChange({ target: { value: "store-1" } });
  tree = render();
  nodes(tree).find(node => node.props?.label === "Invoice" && node.props?.value?.preset).props.onChange({
    preset: "custom", from: "2026-03-01", to: "2026-03-31",
  });
  tree = render();
  nodes(tree).find(node => node.type === "button" && node.props.children === "Export Sales Register").props.onClick();
  const filters = requests.salesRegisterCsv[0].args[0];
  assert.equal(filters.from_date, "2026-03-01");
  assert.equal(filters.to_date, "2026-03-31");
  assert.equal(filters.collection_status, "PARTIAL");
  assert.equal(filters.store_id, "store-1");
  assert.equal(filters.all_time, true);
  nodes(tree).find(node => node.props?.label === "Invoice" && node.props?.value?.preset).props.onChange({ preset: "all", from: "", to: "" });
  tree = render();
  nodes(tree).find(node => node.type === "button" && node.props.children === "Export Sales Register").props.onClick();
  assert.equal(requests.salesRegisterCsv[1].args[0].from_date, "");
  assert.equal(requests.salesRegisterCsv[1].args[0].all_time, true);
});

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

test("quotation mode hides payment and receivable controls", () => {
  const { render } = mountBilling();
  const first = render();
  const selector = nodes(first).find(node => node.type === "select" &&
    nodes(node).some(option => option.props?.value === "quotation"));
  assert.ok(selector);
  selector.props.onChange({ target: { value: "quotation" } });
  const quote = nodes(render());
  assert.ok(quote.some(node => node.props?.children === "Save Quotation"));
  assert.ok(!quote.some(node => node.type === "input" && node.props?.required === true &&
    node.props?.placeholder === "cash / bank / upi"));
  assert.ok(quote.some(node => typeof node.props?.children === "string" &&
    node.props.children.includes("does not change stock, accounts or receivables")));
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
  const size = nodes(render()).find(node => node.type === "select" && nodes(node).some(child => child.type === "option" && child.props.value === 25));
  size.props.onChange({ target: { value: "25" } });
  render();
  assert.equal(requests.invoiceReconcileRuns.length, 3);
  assert.deepEqual(requests.invoiceReconcileRuns[2].args, [25, 0]);
});
