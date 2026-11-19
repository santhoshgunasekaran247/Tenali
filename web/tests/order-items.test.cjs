const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function harness(productRequest = async () => ({ product: { image_url: "product.jpg" } })) {
  const states = [], effects = [], requests = [];
  let cursor = 0, company = "store-one";
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "OrderItems.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const mocks = {
    react: { useEffect: fn => effects.push(fn), useState: initial => {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = value; }];
    } },
    "react-router-dom": { Link: ({ to, children, ...rest }) => React.createElement("a", { href: to, ...rest }, children) },
    "../api": { api: { product: id => { requests.push(id); return productRequest(id); } } },
    "../features/auth": { useAuth: () => ({ storefront: { id: company } }) },
    "../features/catalog/utils": { toAssetUrl: value => value ? `/assets/${value}` : "" },
    "../features/shop": { rupees: value => `INR ${value / 100}` },
  };
  vm.runInNewContext(compiled, { exports, Error, require: name => mocks[name] || require(name) });
  return {
    ...exports, requests,
    image(props = {}) { cursor = 0; effects.length = 0; return exports.ProductImageLink({
      item: { product_id: "product", variant_id: "blue" }, name: "Blue gift set", ...props,
    }); },
    effects() { return effects.map(effect => effect()); },
    setCompany(value) { company = value; },
  };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test("cart images reuse loaded product data and preserve variant links", () => {
  const h = harness();
  const html = renderToStaticMarkup(h.image({ imageUrl: "cart.jpg", className: "cart-item-image" }));
  h.effects();
  assert.match(html, /href="\/products\/product\?variant=blue"/);
  assert.match(html, /src="\/assets\/cart.jpg"/);
  assert.match(html, /alt="Blue gift set"/);
  assert.equal(h.requests.length, 0);
});

test("gallery-only products have a thumbnail and IDs are safely encoded", () => {
  const h = harness();
  assert.equal(h.productImage({ gallery: ["gallery.jpg"], image_url: "" }), "gallery.jpg");
  assert.equal(h.productImage({ image_urls: " | photo.jpg | other.jpg", image_url: "" }), "photo.jpg");
  assert.equal(h.productPagePath({ product_id: "id/part", variant_id: "blue & gold" }), "/products/id%2Fpart?variant=blue%20%26%20gold");
});

test("existing orders load current catalogue thumbnails without changing saved item values", async () => {
  const h = harness(async () => ({ product: { gallery: ["current.jpg"] } }));
  h.image(); h.effects(); await flush();
  assert.match(renderToStaticMarkup(h.image()), /src="\/assets\/current.jpg"/);
  assert.deepEqual(h.requests, ["product"]);
  const html = renderToStaticMarkup(h.OrderItems({ items: [
    { product_id: "product", variant_id: "blue", name: "Original order name", quantity: 2, unit_paise: 12500 },
  ] }));
  assert.match(html, /Original order name/);
  assert.match(html, /Qty 2/);
  assert.match(html, /INR 250/);
  assert.equal((html.match(/href="\/products\/product\?variant=blue"/g) || []).length, 2);
});

test("unavailable products retain the product link and expose the image error", async () => {
  const h = harness(async () => { throw new Error("Product no longer available"); });
  h.image(); h.effects(); await flush();
  const html = renderToStaticMarkup(h.image());
  assert.match(html, /Image unavailable: Product no longer available/);
  assert.match(html, /href="\/products\/product\?variant=blue"/);
  assert.doesNotMatch(html, /<img/);
});

test("broken image URLs show a placeholder and workspace changes cannot show stale photos", async () => {
  const h = harness();
  const tree = h.image({ imageUrl: "broken.jpg" });
  tree.props.children.props.onError();
  assert.match(renderToStaticMarkup(h.image({ imageUrl: "broken.jpg" })), /Image unavailable/);
  h.image(); h.effects(); await flush();
  h.setCompany("store-two");
  assert.doesNotMatch(renderToStaticMarkup(h.image()), /<img/);
});

test("all order surfaces use the shared linked product presentation", () => {
  for (const file of ["CheckoutPage.tsx", "ShopperAccountPage.tsx", "CheckoutAdminPage.tsx"]) {
    assert.match(readFileSync(path.join(__dirname, "..", "src", "pages", file), "utf8"), /<OrderItems items=\{/);
  }
  const cart = readFileSync(path.join(__dirname, "..", "src", "pages", "CartPage.tsx"), "utf8");
  assert.match(cart, /<ProductImageLink/);
  assert.match(cart, /to=\{productPagePath\(item\)\}/);
});
