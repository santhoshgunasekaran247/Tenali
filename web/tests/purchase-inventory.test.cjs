const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function load(file, overrides) {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, Error, require: name => overrides[name] || require(name) });
  return exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const component = () => null;
const flush = () => new Promise(resolve => setImmediate(resolve));

test("purchase inventory displays before other requests finish and survives a history failure", async () => {
  const states = [], refs = [], effects = [], requests = {};
  let cursor = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
      return [states[i], action => { states[i] = typeof action === "function" ? action(states[i]) : action; }];
    },
    useRef(initial) { const i = cursor++; return refs[i] ||= { current: initial }; },
    useEffect(effect) { cursor++; if (!effects.length) effects.push(effect); },
  };
  const api = Object.fromEntries(["parties", "accounts", "purchases", "hsnMasters", "inventoryProducts"].map(name => [
    name, () => new Promise((resolve, reject) => { requests[name] = { resolve, reject }; }),
  ]));
  const { PurchasesPage } = load("pages/PurchasesPage.tsx", {
    react,
    "../api": { api },
    "../features/drafts": { useDraftState: (_key, initial) => react.useState(initial) },
    "../features/postingKey": { postingKey: () => "key" },
    "../features/taxTotals": { calculateLineTotals: () => ({ subtotal: 0, gstTotal: 0, total: 0 }) },
    "../features/stores": { StoreSelect: component, useStores: () => ({ stores: [], stockStores: [], selectedId: "", error: "" }) },
    "../components/TaxLinesEditor": { TaxLinesEditor: component, newTaxLine: () => ({ description: "", quantity: 1, rate: 0, gst_rate: 0 }) },
    "../components/Notifications": { FloatingAlert: component },
    "../components/PortalHomeLink": { PortalHomeLink: component },
    "../components/PartySelect": { PartySelect: component },
    "../components/Attachments": { AttachmentPicker: component, AttachmentManager: component },
    "../components/DeleteTransactionDialog": { DeleteTransactionDialog: component },
    "../features/auth": { useAuth: () => ({ user: { role: "owner" } }) },
    "../features/deletions": { canDeleteTransactions: () => true },
  });
  const render = () => { cursor = 0; return PurchasesPage(); };
  render(); effects[0]();
  requests.inventoryProducts.resolve({ items: [{ id: "product-1", name: "Kettle" }] });
  await flush();
  assert.equal(nodes(render()).find(node => node.props?.products).props.products[0].id, "product-1");
  requests.purchases.reject(new Error("History unavailable"));
  await flush();
  const tree = render();
  assert.equal(nodes(tree).find(node => node.props?.products).props.products.length, 1);
  assert.ok(nodes(tree).some(node => String(node.props?.children).includes("Purchase history: History unavailable")));
});

test("vendor filtering explains unmapped inventory and excludes inactive-variant-only mappings", () => {
  const { TaxLinesEditor, newTaxLine } = load("components/TaxLinesEditor.tsx", {
    "react-router-dom": { Link: component },
    "../features/taxTotals": { calculateLineTotals: () => ({ subtotal: 0, gstTotal: 0, total: 0 }) },
  });
  const offer = { vendor_id: "vendor-1", is_active: true };
  const products = [
    { id: "mapped", name: "Mapped", is_active: true, offers: [offer], variants: [] },
    { id: "unmapped", name: "Unmapped", is_active: true, offers: [], variants: [] },
    { id: "inactive-variant", name: "Inactive mapping", is_active: true, offers: [], variants: [
      { is_active: false, offers: [offer] }, { is_active: true, offers: [] },
    ] },
  ];
  const render = vendorId => TaxLinesEditor({ lines: [newTaxLine()], masters: [], products, vendorId, onChange() {} });
  const vendorOptions = nodes(render("vendor-1")).filter(node => node.type === "option").map(node => node.props.value);
  assert.ok(vendorOptions.includes("mapped"));
  assert.ok(!vendorOptions.includes("unmapped"));
  assert.ok(!vendorOptions.includes("inactive-variant"));
  const empty = render("vendor-2");
  assert.ok(nodes(empty).some(node => node.props?.to === "/portal/inventory"));
  assert.ok(JSON.stringify(empty).includes("No active products are mapped"));
  const salesOptions = nodes(render(undefined)).filter(node => node.type === "option").map(node => node.props.value);
  assert.ok(salesOptions.includes("unmapped"), "Sales inventory must not require vendor mappings");
});
