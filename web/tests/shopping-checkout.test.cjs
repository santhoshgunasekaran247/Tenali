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
  const states = [], added = [], navigated = [], updated = [], removed = [];
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
    }, setQuantity: (item, quantity) => updated.push([item.product_id, quantity]), remove: item => removed.push(item.product_id) }) },
    "../../../api": { api: { product: async () => ({ product }) } },
    "../utils": { moneyLabel: value => value, toAssetUrl: value => value, whatsappLink: () => "https://wa.me/example" },
    "../storefrontText": { storefrontText: value => value },
    "../../../components/QuantityStepper": { QuantityStepper: props => React.createElement("quantity-stepper", { "data-value": props.value, "data-min": props.min, "data-max": props.max, "aria-label": props.label }) },
  });
  return {
    added, navigated, updated, removed,
    render(enabled = true, phone = "example") { cursor = 0; return ProductCard({ product, phone, checkoutEnabled: enabled }); },
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
    [{ stock_qty: 1 }, [], false],
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

const stepper = tree => find(tree, node => node.type?.name === "QuantityStepper" || (typeof node.type === "function" && "onChange" in (node.props || {})));

test("cards add the chosen quantity with plus/minus, bounded by the minimum and stock", async () => {
  const h = cardHarness({ stock_qty: 6 });
  const chooser = stepper(h.render());
  assert.deepEqual([chooser.props.value, chooser.props.min, chooser.props.max], ["2", 2, 6]);
  chooser.props.onChange("5");
  find(h.render(), node => node.type === "button").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.added[0].quantity, 5);
});

test("items already in the cart show an in-cart stepper that updates or removes the cart line", () => {
  const h = cardHarness({ stock_qty: 6 }, [{ product_id: "product", variant_id: null, quantity: 3 }]);
  const html = renderToStaticMarkup(h.render());
  assert.match(html, /In cart/);
  assert.doesNotMatch(html, /Add to Cart/);
  const control = stepper(h.render());
  assert.equal(control.props.value, "3");
  control.props.onChange("4");
  assert.deepEqual(h.updated, [["product", 4]]);
  control.props.onChange("9");
  assert.deepEqual(h.updated, [["product", 4]]);
  control.props.onBelowMin();
  assert.deepEqual(h.removed, ["product"]);
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

const classed = (tree, name) => find(tree, node => String(node.props?.className || "").split(" ").includes(name));

test("cards show price and MRP on one line and keep Add to Cart beside WhatsApp", () => {
  const h = cardHarness({ mrp_display: "600" });
  const tree = h.render();
  const price = renderToStaticMarkup(classed(tree, "price-block"));
  assert.match(price, /class="our-price".*450.*class="mrp".*600/);
  const buttons = renderToStaticMarkup(classed(tree, "product-card-buttons"));
  assert.match(buttons, /Add to Cart.*whatsapp-btn.*WhatsApp enquiry/);
  assert.doesNotMatch(renderToStaticMarkup(cardHarness({ mrp_display: "450" }).render()), /class="mrp"/);
});

test("cards omit WhatsApp when the store turns enquiries off", () => {
  const html = renderToStaticMarkup(cardHarness().render(true, ""));
  assert.match(html, /Add to Cart/);
  assert.doesNotMatch(html, /whatsapp/i);
});

test("storefront display settings default safely and products group in catalogue order", () => {
  const { storefrontDisplay } = load("features/catalog/storefrontDisplay.ts", {});
  assert.deepEqual({ ...storefrontDisplay(undefined) }, { show_bulk_pricing: true, whatsapp_enquiry_enabled: true, corner_style: "rounded" });
  assert.deepEqual({ ...storefrontDisplay({ storefront_content: { display: { show_bulk_pricing: false, whatsapp_enquiry_enabled: false, corner_style: "square" } } }) },
    { show_bulk_pricing: false, whatsapp_enquiry_enabled: false, corner_style: "square" });
  const { groupProducts } = load("features/catalog/productGroups.ts", {});
  const groups = groupProducts([{ id: 1, brand_name: "B" }, { id: 2, brand_name: "A" }, { id: 3, brand_name: "B" }], product => product.brand_name);
  assert.equal(JSON.stringify(groups.map(group => [group.name, group.products.map(product => product.id)])), JSON.stringify([["B", [1, 3]], ["A", [2]]]));
});

test("storefront pages honour the bulk-pricing and WhatsApp toggles and use horizontal rails", () => {
  const source = file => readFileSync(path.join(__dirname, "..", "src", file), "utf8");
  for (const file of ["pages/HomePage.tsx", "pages/BrandPage.tsx", "pages/ProductPage.tsx"]) {
    const page = source(file);
    assert.match(page, /show_bulk_pricing \?/, file);
    assert.match(page, /whatsapp_enquiry_enabled \?|whatsapp_enquiry_enabled\?/, file);
  }
  assert.equal((source("pages/HomePage.tsx").match(/<ProductRail /g) || []).length, 3);
  assert.match(source("pages/HomePage.tsx"), /<ProductRail [^>]*className="brand-rail"/);
  assert.match(source("components/ProductRail.tsx"), /data-more-next=/);
  assert.match(source("styles.css"), /\.product-rail\[data-more-next\] \.product-rail-track \{[^}]*mask-image/);
  assert.match(source("styles.css"), /grid-auto-columns: calc\(\(100vw - var\(--rail-bleed\) - 2 \* var\(--rail-gap\)\) \/ 2\.2\)/);
  assert.doesNotMatch(source("pages/BrandPage.tsx"), /<ProductRail /);
  assert.match(source("pages/BrandPage.tsx"), /className="product-grid compact-product-grid"/);
  assert.match(source("pages/CompanySetupPage.tsx"), /id="storefront-display"[\s\S]*show_bulk_pricing[\s\S]*whatsapp_enquiry_enabled[\s\S]*corner_style/);
  assert.match(source("components/Header.tsx"), /applyCornerStyle\(storefrontDisplay\(/);
});
