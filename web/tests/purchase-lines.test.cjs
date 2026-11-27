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

test("bulk upload resumes the saved job after an interrupted advance", async () => {
  const state = [], refs = [], effects = [];
  let stateIndex = 0, refIndex = 0, fail = true;
  const calls = [];
  const job = { id: "job", kind: "brands", processed: 0, total: 1, success: 0, failures: 0, completed: false, expires_at: "2030-01-01" };
  const react = {
    useState(initial) { const i = stateIndex++; if (!(i in state)) state[i] = initial;
      return [state[i], value => { state[i] = typeof value === "function" ? value(state[i]) : value; }]; },
    useRef(initial) { const i = refIndex++; return refs[i] || (refs[i] = { current: initial }); },
    useEffect(callback) { effects.push(callback); },
  };
  const api = {
    bulkJobs: async () => ({ items: calls.length ? [job] : [] }),
    bulkStart: async (kind, file, key) => { calls.push(["start", kind, file.name, key]); return job; },
    bulkAdvance: async id => { calls.push(["advance", id]); if (fail) { fail = false; throw new Error("Connection lost"); }
      return { ...job, processed: 1, success: 1, completed: true }; },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "components", "BulkWorkbookPanel.tsx"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, Error, crypto: { randomUUID: () => "stable-key" },
    require: name => name === "react" ? react : name === "../api" ? { api } :
      name === "react/jsx-runtime" ? { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) } : require(name) });
  const render = () => { stateIndex = 0; refIndex = 0; return exports.BulkWorkbookPanel({ selectedProducts: [], onImported() {} }); };
  const flush = () => new Promise(resolve => setImmediate(resolve));
  let tree = render();
  effects.splice(0).forEach(effect => effect());
  await flush();
  tree = render();
  const fileInput = find(tree, node => node.type === "input" && node.props.type === "file")[0];
  fileInput.props.onChange({ target: { files: [{ name: "items.xlsx", size: 100 }] } });
  tree = render();
  find(tree, node => node.type === "button" && text(node) === "Upload & process")[0].props.onClick();
  await flush(); await flush();
  tree = render();
  assert.match(text(tree), /Connection lost/);
  find(tree, node => node.type === "button" && text(node) === "Resume")[0].props.onClick();
  await flush(); await flush();
  assert.deepEqual(calls, [["start", "products", "items.xlsx", "stable-key"], ["advance", "job"], ["advance", "job"]]);
  assert.match(text(render()), /Import complete/);
});

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
  vm.runInNewContext(compiled, { exports, Error, require: name => mocks[name] || base[name] || stub });
  return exports;
}

function editorHarness(product, api = {}, lookups = { brands: [], categories: [], vendors: [] }) {
  const state = {};
  const hook = (key, initial) => {
    if (!(key in state)) state[key] = typeof initial === "function" ? initial() : initial;
    return [state[key], next => { state[key] = typeof next === "function" ? next(state[key]) : next; }];
  };
  let slot = 0;
  const { ProductEditor } = loadModule(["components", "InventoryForms.tsx"], {
    "../api": { api },
    "../features/drafts": { useDraftState: hook, useClearDrafts: () => () => {} },
    react: { useState: initial => hook(`useState${slot++}`, initial) },
  });
  const render = () => { slot = 0; return ProductEditor({ product, lookups, hsn: [], onSaved: () => {}, onClose: () => {} }); };
  const form = () => Object.entries(state).find(([key]) => key.endsWith("form"))[1];
  return { render, form };
}

test("typed brand/category names are created on save and retries reuse saved lookup IDs", async () => {
  const calls = [];
  let first = true;
  const editor = editorHarness(undefined, {
    inventoryCreateLookup: async (kind, name) => { calls.push([kind, name]); return { id: kind, name, code: kind }; },
    inventorySaveProduct: async payload => {
      calls.push(["product", payload.brand_id, payload.category_id]);
      if (first) { first = false; throw new Error("Product validation failed"); }
      return payload;
    },
  });
  const input = (tree, kind) => find(tree, node => node.type === "input" && node.props.list?.endsWith(kind))[0];
  input(editor.render(), "brands").props.onChange({ target: { value: "  New brand  " } });
  input(editor.render(), "categories").props.onChange({ target: { value: "New category" } });
  assert.equal(calls.length, 0, "Typing must not create records");
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.match(text(editor.render()), /Product validation failed/);
  input(editor.render(), "brands").props.onChange({ target: { value: "" } });
  input(editor.render(), "brands").props.onChange({ target: { value: "New brand" } });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(calls, [["brands", "New brand"], ["categories", "New category"],
    ["product", "brands", "categories"], ["product", "brands", "categories"]]);
});

test("existing brand/category names are matched case-insensitively and may be cleared", async () => {
  const saved = [];
  const editor = editorHarness(undefined, { inventorySaveProduct: async payload => { saved.push(payload); return payload; } },
    { brands: [{ id: "b1", name: "Acme" }], categories: [{ id: "c1", name: "Home" }], vendors: [] });
  const input = (tree, kind) => find(tree, node => node.type === "input" && node.props.list?.endsWith(kind))[0];
  input(editor.render(), "brands").props.onChange({ target: { value: " acme " } });
  input(editor.render(), "categories").props.onChange({ target: { value: "HOME" } });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual([saved[0].brand_id, saved[0].category_id], ["b1", "c1"]);
  input(editor.render(), "brands").props.onChange({ target: { value: "" } });
  input(editor.render(), "categories").props.onChange({ target: { value: "HOM" } });
  input(editor.render(), "categories").props.onChange({ target: { value: "" } });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(saved[1].brand_id, null);
  assert.equal(saved[1].category_id, null);
  assert.deepEqual(Array.from(saved[1].category_ids), []);
});

test("lookup creation errors stop product saving and remain visible", async () => {
  let posted = false;
  const editor = editorHarness(undefined, {
    inventoryCreateLookup: async () => { throw new Error("Brand access denied"); },
    inventorySaveProduct: async () => { posted = true; },
  });
  find(editor.render(), node => node.type === "input" && node.props.list?.endsWith("brands"))[0]
    .props.onChange({ target: { value: "New brand" } });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(posted, false);
  assert.match(text(editor.render()), /Brand access denied/);
});

test("new brand details are passed when the brand is created with the product", async () => {
  const calls = [];
  const editor = editorHarness(undefined, {
    inventoryCreateLookup: async (...args) => { calls.push(args); return { id: "b1", name: args[1], code: "brand" }; },
    inventorySaveProduct: async payload => { calls.push(["product", payload.brand_id]); return payload; },
  });
  find(editor.render(), node => node.type === "input" && node.props.list?.endsWith("brands"))[0]
    .props.onChange({ target: { value: "New brand" } });
  find(editor.render(), node => node.type === "textarea" && node.props.maxLength === 2000)[0]
    .props.onChange({ target: { value: "  Brand details  " } });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["brands", "New brand", { description: "Brand details", is_active: true }], ["product", "b1"],
  ]);
});

test("product labels can select existing labels and add a new one", async () => {
  const saved = [];
  const editor = editorHarness(undefined, { inventorySaveProduct: async payload => { saved.push(payload); return payload; } },
    { brands: [], categories: [], vendors: [], tags: ["Featured", "Handcrafted"] });
  const labelSelect = tree => find(tree, node => node.type === "select" && node.props.multiple)[0];
  assert.deepEqual(options(labelSelect(editor.render())), ["Featured", "Handcrafted"]);
  labelSelect(editor.render()).props.onChange({ currentTarget: { selectedOptions: [{ value: "Featured" }, { value: "Handcrafted" }] } });
  const newLabel = find(find(editor.render(), node => node.type === "label" && text(node).startsWith("New label"))[0], node => node.type === "input")[0];
  newLabel.props.onChange({ target: { value: "Seasonal" } });
  find(editor.render(), node => node.type === "button" && text(node) === "Add label")[0].props.onClick();
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(Array.from(saved[0].tags), ["Featured", "Handcrafted", "Seasonal"]);
});

test("product editor saves multiple categories and a primary category", async () => {
  const saved = [];
  const editor = editorHarness(undefined, { inventorySaveProduct: async payload => { saved.push(payload); return payload; } },
    { brands: [], categories: [{ id: "c1", name: "Kitchen" }, { id: "c2", name: "Gifts" }], vendors: [], tags: [] });
  const field = find(editor.render(), node => node.type === "label" && text(node).startsWith("Additional categories"))[0];
  find(field, node => node.type === "select")[0].props.onChange({
    currentTarget: { selectedOptions: [{ value: "c1" }, { value: "c2" }] },
  });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(saved[0].category_id, "c1");
  assert.deepEqual(Array.from(saved[0].category_ids), ["c1", "c2"]);
});

test("product editor saves the selected image background", async () => {
  const saved = [];
  const editor = editorHarness(undefined, { inventorySaveProduct: async payload => { saved.push(payload); return payload; } });
  find(find(editor.render(), node => node.type === "label" && text(node).startsWith("Product image background"))[0],
    node => node.type === "select")[0].props.onChange({ target: { value: "#add8e6" } });
  await find(editor.render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(saved[0].image_background, "#add8e6");
});

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
