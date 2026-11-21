const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
const exportsObject = {};
vm.runInNewContext(ts.transpileModule(source("features/catalog/variants.ts"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports: exportsObject });

test("variant image leads the gallery and falls back dynamically to the parent", () => {
  const { variantGallery } = exportsObject;
  assert.deepEqual(Array.from(variantGallery(["main.jpg", "back.jpg"], "blue.jpg")), ["blue.jpg", "main.jpg", "back.jpg"]);
  assert.deepEqual(Array.from(variantGallery(["main.jpg", "back.jpg"], null)), ["main.jpg", "back.jpg"]);
  assert.deepEqual(Array.from(variantGallery(["main.jpg", "back.jpg"], "main.jpg")), ["main.jpg", "back.jpg"]);
  assert.deepEqual(Array.from(variantGallery([], "blue.jpg")), ["blue.jpg"]);
});

test("variant editor saves the image and offers a main-image fallback", () => {
  const form = source("components/InventoryForms.tsx");
  assert.match(form, /image_url: variant\?\.image_url \|\| null/);
  assert.match(form, /inventorySaveVariant\(product\.id,\{\.\.\.item,image_url:draft\.image_url/);
  assert.match(form, /Use main product image/);
  const page = source("pages/ProductPage.tsx");
  assert.match(page, /variantGallery\(parentGallery, product\.variants\?\.find\(item => item\.id === variantId\)\?\.image_url\)/);
  assert.match(page, /setVariantId\(id\); setPhotoIndex\(0\)/);
});

test("variant editor uploads a photo and can revert to its parent", async () => {
  const state = {}, calls = [];
  let slot = 0;
  const hook = (key, initial) => {
    if (!(key in state)) state[key] = typeof initial === "function" ? initial() : initial;
    return [state[key], next => { state[key] = typeof next === "function" ? next(state[key]) : next; }];
  };
  const element = (type, props) => ({ type, props });
  const mocks = {
    "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "fragment" },
    react: { useState: initial => hook(`state${slot++}`, initial) },
    "../features/drafts": { useDraftState: hook, useClearDrafts: () => () => {} },
    "../features/catalog/utils": { toAssetUrl: value => value },
    "../api": { api: { inventorySaveVariant: async (_id, payload) => { calls.push(payload); return {}; } } },
  };
  class FileReader {
    readAsDataURL() { this.result = "data:image/png;base64,photo"; this.onload(); }
  }
  const compiled = ts.transpileModule(source("components/InventoryForms.tsx"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, FileReader, Error, require: name => mocks[name] || new Proxy({}, { get: (_, key) => String(key) }) });
  const product = { id: "p", image_url: "main.jpg", image_urls: "", variants: [], offers: [] };
  const render = () => { slot = 0; return exports.ProductEditor({ product, variantMode: true,
    lookups: { brands: [], categories: [], vendors: [] }, hsn: [], onSaved() {}, onClose() {} }); };
  const all = (node, predicate) => {
    if (!node || typeof node !== "object") return [];
    if (Array.isArray(node)) return node.flatMap(child => all(child, predicate));
    return [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
  };
  let tree = render();
  assert.equal(all(tree, node => node.type === "img" && node.props.alt === "Main product image preview")[0].props.src, "main.jpg");
  all(tree, node => node.type === "input" && node.props.type === "file")[0].props.onChange({
    target: { files: [{ type: "image/png", size: 12 }], value: "image.png" },
  });
  await new Promise(resolve => setImmediate(resolve));
  tree = render();
  assert.equal(all(tree, node => node.type === "img" && node.props.alt === "Variant image preview")[0].props.src, "data:image/png;base64,photo");
  await all(tree, node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(calls[0].image_url, "data:image/png;base64,photo");
  all(render(), node => node.type === "button" && node.props.children === "Use main product image")[0].props.onClick();
  await all(render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(calls[1].image_url, null);
});

test("choosing variants switches the main photo and resets the gallery selection", () => {
  const product = { id: "p", name: "Shirt", minimum_order_quantity: 1, image_url: "main.jpg",
    gallery: ["main.jpg", "back.jpg"], stock_qty: 5, selling_price_display: "100",
    variants: [{ id: "blue", variant_name: "Blue", image_url: "blue.jpg", stock_qty: 2, selling_price_display: "100" },
      { id: "red", variant_name: "Red", image_url: null, stock_qty: 2, selling_price_display: "100" }] };
  const state = [product, { company_name: "Store" }, undefined, 0, "", "1", "", ""];
  let cursor = 0;
  const element = (type, props) => ({ type, props });
  const mocks = {
    react: { useState: initial => { const i = cursor++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = value; }]; },
      useEffect: () => {}, useMemo: fn => fn() },
    "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "fragment" },
    "react-router-dom": { Link: "link", useParams: () => ({ productId: "p" }), useSearchParams: () => [new URLSearchParams(), () => {}] },
    "../features/catalog/variants": exportsObject,
    "../features/auth": { useAuth: () => ({ storefront: { id: "shop" } }) },
    "../features/cart": { useCart: () => ({ items: [] }) },
    "../features/useCheckoutAvailability": { useCheckoutAvailability: () => ({ availability: { enabled: true } }) },
    "../features/cartMode": { cartMode: () => "checkout", cartWords: () => ({}) },
    "../features/catalog/utils": { toAssetUrl: value => value, moneyLabel: value => value, whatsappLink: () => "" },
    "../features/catalog/storefrontDisplay": { storefrontDisplay: () => ({ whatsapp_enquiry_enabled: false }) },
    "../features/catalog/storefrontText": { storefrontText: value => value },
  };
  const compiled = ts.transpileModule(source("pages/ProductPage.tsx"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, URLSearchParams, require: name => mocks[name] || new Proxy({}, { get: (_, key) => String(key) }) });
  const render = () => { cursor = 0; return exports.ProductPage(); };
  const findAll = (node, predicate) => {
    if (!node || typeof node !== "object") return undefined;
    if (Array.isArray(node)) return node.flatMap(child => findAll(child, predicate) || []);
    return [...(predicate(node) ? [node] : []), ...(findAll(node.props?.children, predicate) || [])];
  };
  const find = (node, predicate) => (findAll(node, predicate) || [])[0];
  const image = tree => find(find(tree, node => node.props?.className === "detail-image-wrap"), node => node.type === "img").props.src;
  let tree = render();
  assert.equal(image(tree), "main.jpg");
  find(tree, node => node.type === "button" && node.props.children === "Blue").props.onClick();
  tree = render();
  assert.equal(image(tree), "blue.jpg");
  findAll(tree, node => node.props?.["aria-label"] === "View photo {number}")[1].props.onClick();
  assert.equal(image(render()), "main.jpg");
  find(render(), node => node.type === "button" && node.props.children === "Red").props.onClick();
  tree = render();
  assert.equal(image(tree), "main.jpg");
});
