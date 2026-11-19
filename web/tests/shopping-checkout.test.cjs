const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(file, mocks) {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || require(name) });
  return exports;
}

function cardHarness(current = {}, existing = []) {
  const product = { id: "product", name: "Diya", minimum_order_quantity: 2, selling_price_display: "450",
    stock_qty: 10, image_url: "", ...current };
  const states = [], added = [], navigated = [];
  let cursor = 0;
  const { ProductCard } = load("features/catalog/components/ProductCard.tsx", {
    react: { ...React, useState: initial => {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = value; }];
    } },
    "react-router-dom": {
      useNavigate: () => value => navigated.push(value),
      Link: ({ to, children, ...rest }) => React.createElement("a", { href: to, ...rest }, children),
    },
    "../../auth": { useAuth: () => ({ storefront: { company_name: "Store" } }) },
    "../../cart": { useCart: () => ({ items: existing, add: item => {
      if (item.quantity > 100) throw new Error("Online orders support up to 100 units per item.");
      added.push(item);
    } }) },
    "../../../api": { api: { product: async () => ({ product }) } },
    "../utils": { moneyLabel: value => value, toAssetUrl: value => value, whatsappLink: () => "https://wa.me/example" },
    "../storefrontText": { storefrontText: value => value },
  });
  return {
    added, navigated,
    render(enabled = true) { cursor = 0; return ProductCard({ product, phone: "example", checkoutEnabled: enabled }); },
  };
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}

test("collection cards offer Add to Cart only when checkout is available, alongside WhatsApp", () => {
  const h = cardHarness();
  const enabled = renderToStaticMarkup(h.render());
  assert.match(enabled, /Add to Cart/);
  assert.match(enabled, /WhatsApp enquiry/);
  assert.doesNotMatch(renderToStaticMarkup(h.render(false)), /Add to Cart/);
});

test("quick add uses the minimum quantity and offers a cart link without navigating", async () => {
  const h = cardHarness();
  await find(h.render(), node => node.type === "button").props.onClick();
  // React event handlers deliberately do not return their asynchronous work.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.added.length, 1);
  assert.equal(h.added[0].quantity, 2);
  assert.equal(h.added[0].variant_id, null);
  assert.equal(h.navigated.length, 0);
  assert.match(renderToStaticMarkup(h.render()), /2 units added.*View cart/);
});

test("variant selection is required and existing cart stock is respected", async () => {
  for (const [current, existing, navigation] of [
    [{ variants: [{ id: "size" }] }, [], true],
    [{ stock_qty: 2 }, [{ product_id: "product", variant_id: null, quantity: 1 }], false],
    [{ selling_price_display: "" }, [], false],
    [{ minimum_order_quantity: 101, stock_qty: 200 }, [], false],
  ]) {
    const h = cardHarness(current, existing);
    find(h.render(), node => node.type === "button").props.onClick();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.added.length, 0);
    assert.equal(h.navigated.length, navigation ? 1 : 0);
    if (!navigation) assert.match(renderToStaticMarkup(h.render()), /role="alert"/);
  }
});

test("Enter on nested purchase controls does not activate the product card", () => {
  const h = cardHarness();
  const tree = h.render();
  tree.props.onKeyDown({ key: "Enter", target: {}, currentTarget: tree });
  assert.equal(h.navigated.length, 0);
  tree.props.onKeyDown({ key: "Enter", target: tree, currentTarget: tree });
  assert.equal(h.navigated.length, 1);
});

test("shopper-facing copy omits verification notices without changing staff identity warnings", () => {
  for (const file of ["components/FederatedShopperLogin.tsx", "pages/ShopperAccountPage.tsx"]) {
    assert.doesNotMatch(readFileSync(path.join(__dirname, "..", "src", file), "utf8"), /unverified/i);
  }
  assert.match(readFileSync(path.join(__dirname, "..", "src", "components", "OnlineCustomerLinks.tsx"), "utf8"), /unverified/);
});
