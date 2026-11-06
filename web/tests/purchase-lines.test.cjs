const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function loadEditor() {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "TaxLinesEditor.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const element = (type, props) => ({ type, props });
  const exports = {};
  const mocks = {
    "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "Fragment" },
    "react-router-dom": { Link: "Link" },
    "lucide-react": { Plus: "Plus", Trash2: "Trash2" },
    "../features/taxTotals": { calculateLineTotals: () => ({ subtotal: 0, gstTotal: 0, total: 0 }) },
  };
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || require(name) });
  return exports.TaxLinesEditor;
}

function find(node, predicate, found = []) {
  if (Array.isArray(node)) node.forEach(child => find(child, predicate, found));
  else if (node && typeof node === "object") {
    if (predicate(node)) found.push(node);
    find(node.props && node.props.children, predicate, found);
  }
  return found;
}

function text(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  return text(node.props && node.props.children);
}

const masters = [{ id: "h1", code: "7408", description: "Copper", gst_rate: 18 }];
const product = (id, extra = {}) => ({ id, name: id, portal_product_id: `PRD-${id}`, is_active: true, variants: [],
  offers: [{ vendor_id: "vendor", is_active: true, buying_price: 100 }], hsn_code: "7408", catalog_price: 120, ...extra });
const products = [product("tagged"), product("untagged", { hsn_code: null }), product("draft", { is_draft: true })];
const selects = tree => find(tree, node => node.type === "select");
const options = select => find(select, node => node.type === "option").map(option => option.props.value);

function render(line, vendorId) {
  const changes = [];
  const tree = loadEditor()({ lines: [{ description: "", hsn: "", quantity: 1, rate: 0, gst_rate: 0, ...line }], masters, products, vendorId, onChange: next => changes.push(next) });
  return { tree, changes };
}

test("HSN is locked only when the selected product already has one", () => {
  const tagged = render({ product_id: "tagged", hsn: "7408" });
  assert.equal(selects(tagged.tree)[1].props.disabled, true);
  const untagged = render({ product_id: "untagged" });
  assert.equal(selects(untagged.tree)[1].props.disabled, false);
  assert.match(text(untagged.tree), /saved to the product/);
});

test("sales hide draft products; purchases offer drafts and a new-item option", () => {
  const sale = options(selects(render({}).tree)[0]);
  assert.deepEqual(sale, ["", "tagged", "untagged"]);
  const purchase = render({}, "vendor");
  assert.deepEqual(options(selects(purchase.tree)[0]), ["", "__new__", "tagged", "untagged", "draft"]);
  assert.match(text(purchase.tree), /Manual lines are not added to stock/);
  selects(purchase.tree)[0].props.onChange({ target: { value: "__new__" } });
  assert.equal(purchase.changes[0][0].new_product, true);
  assert.equal(purchase.changes[0][0].product_id, null);
});

test("choosing an existing product clears the new-item flag", () => {
  const purchase = render({ new_product: true, description: "Copper wire" }, "vendor");
  assert.equal(selects(purchase.tree)[0].props.value, "__new__");
  assert.match(text(purchase.tree), /draft product named after the description/);
  selects(purchase.tree)[0].props.onChange({ target: { value: "tagged" } });
  assert.deepEqual([purchase.changes[0][0].product_id, purchase.changes[0][0].new_product, purchase.changes[0][0].rate], ["tagged", false, 100]);
});

test("purchase form sends the goods-received choice, unticked by default", () => {
  const page = readFileSync(path.join(__dirname, "..", "src", "pages", "PurchasesPage.tsx"), "utf8");
  assert.match(page, /received_now: false,/);
  assert.match(page, /received_now: form\.received_now && form\.receipt_type !== "SERVICE"/);
  assert.match(page, /Goods received now/);
});

function loadDraftMerge() {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "pages", "InventoryPage.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const element = (type, props) => ({ type, props });
  const exports = {};
  const stub = new Proxy({}, { get: (_, name) => name === "__esModule" ? false : String(name) });
  const mocks = { "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "Fragment" } };
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || stub });
  return exports.DraftMerge;
}

test("draft merge needs a target, and a variant when the target has variants", () => {
  const DraftMerge = loadDraftMerge();
  const draft = product("draft", { is_draft: true, stock_qty: 4 });
  const plain = product("plain");
  const sized = product("sized", { variants: [{ id: "v1", variant_name: "Large", is_active: true }, { id: "v2", variant_name: "Old", is_active: false }] });
  const inactive = product("gone", { is_active: false });
  const props = (value, onMerge = () => {}) => ({ draft, products: [draft, plain, sized, inactive], value, busy: false, onChange: () => {}, onMerge });
  const button = tree => find(tree, node => node.type === "button")[0];
  const empty = DraftMerge(props({ target: "", variant: "" }));
  assert.deepEqual(options(selects(empty)[0]), ["", "plain", "sized"]);
  assert.equal(button(empty).props.disabled, true);
  const ready = DraftMerge(props({ target: "plain", variant: "" }));
  assert.equal(button(ready).props.disabled, false);
  assert.match(text(ready), /4 in stock/);
  const needsVariant = DraftMerge(props({ target: "sized", variant: "" }));
  assert.deepEqual(options(selects(needsVariant)[1]), ["", "v1"]);
  assert.equal(button(needsVariant).props.disabled, true);
  assert.equal(button(DraftMerge(props({ target: "sized", variant: "v1" }))).props.disabled, false);
});

test("required fields are marked by the border only, without a text label", () => {
  const css = readFileSync(path.join(__dirname, "..", "src", "styles.css"), "utf8");
  assert.doesNotMatch(css, /\* Required/);
  assert.match(css, /input\[required\], select\[required\], textarea\[required\] \{ border-inline-start/);
});

function loadModule(file, mocks) {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", ...file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const element = (type, props) => ({ type, props });
  const exports = {};
  const stub = new Proxy({}, { get: (_, name) => name === "__esModule" ? false : String(name) });
  const base = { "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "Fragment" } };
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || base[name] || stub });
  return exports;
}

function editorHarness(product) {
  const state = {};
  const hook = (key, initial) => {
    if (!(key in state)) state[key] = typeof initial === "function" ? initial() : initial;
    return [state[key], next => { state[key] = typeof next === "function" ? next(state[key]) : next; }];
  };
  let slot = 0;
  const { ProductEditor } = loadModule(["components", "InventoryForms.tsx"], {
    "../features/drafts": { useDraftState: hook, useClearDrafts: () => () => {} },
    react: { useState: initial => hook(`useState${slot++}`, initial) },
  });
  const render = () => { slot = 0; return ProductEditor({ product, lookups: { brands: [], categories: [], vendors: [] }, hsn: [], onSaved: () => {}, onClose: () => {} }); };
  const form = () => Object.entries(state).find(([key]) => key.endsWith("form"))[1];
  return { render, form };
}

test("setting a reorder level turns reorder alerts on and keeps the target valid", () => {
  const product = { id: "p1", name: "HD9270/70", attributes: {}, image_urls: "", offers: [], variants: [], reorder_enabled: false, reorder_level: 0, reorder_target: 0 };
  const editor = editorHarness(product);
  const level = tree => find(find(tree, node => node.type === "label" && /^Reorder At \/ Below/.test(text(node)))[0], node => node.type === "input")[0];
  level(editor.render()).props.onChange({ target: { value: "10" } });
  assert.deepEqual([editor.form().reorder_enabled, editor.form().reorder_level, editor.form().reorder_target], [true, 10, 10]);
});

test("a product with a level but alerts off is flagged in the editor", () => {
  const product = { id: "p2", name: "HD9270/70", attributes: {}, image_urls: "", offers: [], variants: [], reorder_enabled: false, reorder_level: 10, reorder_target: 10 };
  assert.match(text(editorHarness(product).render()), /Reorder alerts are off/);
});

test("transfer opened from a product starts with that product and the store holding its stock", () => {
  const state = {};
  let slot = 0;
  const { StockTransferDialog } = loadModule(["components", "StockTransferDialog.tsx"], {
    react: { useState: initial => { const key = slot++; if (!(key in state)) state[key] = typeof initial === "function" ? initial() : initial; return [state[key], () => {}]; }, useEffect: () => {}, useRef: () => ({ current: null }) },
  });
  const stores = [{ id: "main", code: "MAIN", name: "Main", is_default: true }, { id: "t2", code: "T2", name: "Second" }];
  const products = [{ id: "kettle", name: "Kettle", is_active: true, variants: [], store_stocks: [{ store_id: "t2", quantity: 9 }, { store_id: "main", quantity: 0 }] }];
  const tree = StockTransferDialog({ products, stores, productId: "kettle", onClose: () => {}, onDone: () => {} });
  const values = selects(tree).map(select => select.props.value);
  assert.deepEqual(values.slice(0, 3), ["t2", "main", "kettle"]);
  assert.match(text(tree), /9/);
  slot = 0; for (const key of Object.keys(state)) delete state[key];
  const plain = StockTransferDialog({ products, stores, onClose: () => {}, onDone: () => {} });
  assert.deepEqual(selects(plain).map(select => select.props.value).slice(0, 3), ["main", "t2", ""]);
});
