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
    "../../cartMode": load("features/cartMode.ts", {}),
    "../../../components/QuantityStepper": { QuantityStepper: props => React.createElement("quantity-stepper", { "data-value": props.value, "data-min": props.min, "data-max": props.max, "aria-label": props.label }) },
  });
  return {
    added, navigated, updated, removed,
    render(enabled = true, phone = "example", template, productCopy) { cursor = 0; return ProductCard({ product, phone, checkoutEnabled: enabled, template, productCopy }); },
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

test("product card theme changes keep the actual product photo and purchase actions", () => {
  const h = cardHarness({ image_url: "tenant-product.jpg" });
  for (const template of ["current", "marketplace"]) {
    const tree = h.render(true, "example", template);
    assert.equal(tree.props["data-product-theme"], template);
    const html = renderToStaticMarkup(tree);
    assert.match(html, /tenant-product\.jpg/);
    assert.match(html, /Add to Cart/);
    assert.match(html, /WhatsApp enquiry/);
  }
});

test("custom product button labels preserve add, variant and cart destinations", async () => {
  const copy = { add_to_cart: "Put in basket", choose_options: "Select a size", view_cart: "Open basket" };
  const plain = cardHarness();
  const button = find(plain.render(true, "", "marketplace", copy), node => node.type === "button" && node.props.children === "Put in basket");
  assert.ok(button);
  button.props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(plain.added[0].quantity, 2);
  assert.equal(plain.navigated.length, 0);
  const variants = cardHarness({ variants: [{ id: "size" }] });
  find(variants.render(true, "", "current", copy), node => node.type === "button" && node.props.children === "Select a size").props.onClick();
  assert.equal(variants.navigated[0], "/products/product");
  const existing = cardHarness({}, [{ product_id: "product", variant_id: null, quantity: 2 }]);
  const link = find(existing.render(true, "", "marketplace", copy), node => node.props?.children === "Open basket");
  assert.equal(link.props.to, "/cart");
});

test("product badges do not overlap a broken image placeholder", () => {
  const missing = cardHarness({ sru_special: true });
  const html = renderToStaticMarkup(missing.render());
  assert.match(html, /class="badge-special">Special/);
  assert.match(html, /No image/);
  assert.doesNotMatch(html, /<img/);
  const broken = cardHarness({ sru_special: true, image_url: "broken.jpg" });
  const image = find(broken.render(), node => node.type === "img");
  assert.ok(image);
  image.props.onError();
  const failed = renderToStaticMarkup(broken.render());
  assert.match(failed, /Image unavailable/);
  assert.match(failed, /class="badge-special">Special/);
  assert.doesNotMatch(failed, /<img/);
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

test("variant selection and valid price are required", async () => {
  for (const [current, existing, navigation] of [
    [{ variants: [{ id: "size" }] }, [], true],
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

test("cards add the chosen quantity without treating aggregate stock as checkout availability", async () => {
  const h = cardHarness({ stock_qty: 6 });
  const chooser = stepper(h.render());
  assert.deepEqual([chooser.props.value, chooser.props.min, chooser.props.max], ["2", 2, 100]);
  chooser.props.onChange("5");
  find(h.render(), node => node.type === "button").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.added[0].quantity, 5);
});

test("catalogue cards do not claim aggregate stock is available at checkout", async () => {
  for (const stock_qty of [0, 10]) {
    const h = cardHarness({ stock_qty });
    const html = renderToStaticMarkup(h.render());
    assert.doesNotMatch(html, />In stock</);
    find(h.render(), node => node.type === "button").props.onClick();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.added.length, 1);
  }
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
  assert.deepEqual(h.updated, [["product", 4], ["product", 9]]);
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


test("product page variant picker groups size/colour and keeps the parent selectable", () => {
  const { variantOptions, variantLayout, pickVariant } = load("features/catalog/variants.ts", {});
  const parent = { name: "Kurta", size: "M", colour: "Blue" };
  const variants = [
    { id: "v1", variant_name: "Kurta L Blue", size: "L", colour: "Blue", stock_qty: 4 },
    { id: "v2", variant_name: "Kurta M Red", size: "M", colour: "Red", stock_qty: 0 },
    { id: "v3", variant_name: "Kurta L Red", size: "L", colour: "Red", stock_qty: 2 },
  ];
  const options = variantOptions(parent, variants);
  assert.equal(options[0].id, "");
  const layout = variantLayout(options);
  assert.equal(layout.kind, "dimensions");
  assert.deepEqual(JSON.parse(JSON.stringify(layout.dimensions)), [{ key: "size", values: ["M", "L"] }, { key: "colour", values: ["Blue", "Red"] }]);
  // From the parent (M / Blue), clicking L keeps Blue; clicking Red keeps M.
  assert.equal(pickVariant(options, options[0], layout.dimensions, "size", "L").id, "v1");
  assert.equal(pickVariant(options, options[0], layout.dimensions, "colour", "Red").id, "v2");
  // From a variant, the parent's values lead back to the parent.
  assert.equal(pickVariant(options, options[1], layout.dimensions, "size", "M").id, "");

  // A parent without its own size cannot sit in a Size group, so every option is shown by name instead.
  const named = variantOptions({ name: "T-shirt" }, [{ id: "a", variant_name: "Small", size: "S" }, { id: "b", variant_name: "Large", size: "L" }]);
  assert.equal(variantLayout(named).kind, "names");
  assert.deepEqual([...named.map(option => option.label)], ["T-shirt", "Small", "Large"]);

  const page = readFileSync(path.join(__dirname, "..", "src", "pages", "ProductPage.tsx"), "utf8");
  assert.doesNotMatch(page, /<select value=\{variantId\}/);
  assert.match(page, /className="variant-chip"/);
  assert.match(page, /aria-pressed=\{pressed\}/);
  assert.match(page, /setSearch\(next, \{ replace: true \}\)/);
});

test("variant chips drop the repeated product name", () => {
  const { shortVariantLabel } = load("features/catalog/variants.ts", {});
  assert.equal(shortVariantLabel("Brass Lotus Diya - 3.5 inch", "Brass Lotus Diya"), "3.5 inch");
  assert.equal(shortVariantLabel("brass lotus diya (4.5 inch)", "Brass Lotus Diya"), "4.5 inch");
  assert.equal(shortVariantLabel("Brass Lotus Diya", "Brass Lotus Diya"), "Brass Lotus Diya");
  assert.equal(shortVariantLabel("Large", "Brass Lotus Diya"), "Large");
});

test("number boxes drop leading zeros and the product page keeps buying above the fold", () => {
  const { withoutLeadingZeros } = load("features/numberInputs.ts", {});
  assert.equal(withoutLeadingZeros("010"), "10");
  assert.equal(withoutLeadingZeros("007"), "7");
  assert.equal(withoutLeadingZeros("0"), "0");
  assert.equal(withoutLeadingZeros("0.5"), "0.5");
  assert.equal(withoutLeadingZeros("-05"), "-5");
  assert.match(readFileSync(path.join(__dirname, "..", "src", "main.tsx"), "utf8"), /installNumberInputs\(\);/);

  const page = readFileSync(path.join(__dirname, "..", "src", "pages", "ProductPage.tsx"), "utf8");
  assert.match(page, /className="product-cart-row"[\s\S]*<QuantityStepper[\s\S]*add_to_cart[\s\S]*whatsapp-btn/);
  assert.match(page, /<details className="detail-more" open>[\s\S]*inventory-specs/);
  assert.match(page, /pickup_heading[\s\S]*<NearbyStores [\s\S]*help_heading/);
  assert.doesNotMatch(page, /<details className="detail-more">/);
  const css = readFileSync(path.join(__dirname, "..", "src", "styles.css"), "utf8");
  assert.match(css, /\.detail-image-wrap \{ height: min\(calc\(100vh - 230px\), 520px\)/);
  assert.match(css, /\.detail-copy h1 \{ font-size: clamp\(22px, 2\.3vw, 32px\)/);
});

test("product editor can fix a saved product image with the AI photo models", () => {
  const editor = readFileSync(path.join(__dirname, "..", "src", "components", "InventoryForms.tsx"), "utf8");
  const client = readFileSync(path.join(__dirname, "..", "src", "api.ts"), "utf8");
  assert.match(client, /\/images\/enhance`/);
  assert.match(editor, /api\.inventoryEnhanceImage\(product\.id, imageUrl\)/);
  assert.match(editor, /Fix with AI/);
  assert.match(editor, /Save the product first, then fix this image/);
});


test("party search shows clickable matches and explains when nothing matches", () => {
  const { matchParties, PartySelect } = load("components/PartySelect.tsx", {});
  const vendors = [{ id: "a", legal_name: "Anand Traders", email: "sales@anand.in", phone: "+91 98400 11111" },
    { id: "b", legal_name: "Bala Metals", email: "", phone: "044-2345" }];
  assert.deepEqual([...matchParties(vendors, "anand")].map(v => v.id), ["a"]);
  assert.deepEqual([...matchParties(vendors, "98400")].map(v => v.id), ["a"]);
  assert.equal(matchParties(vendors, "").length, 2);
  const source = readFileSync(path.join(__dirname, "..", "src", "components", "PartySelect.tsx"), "utf8");
  assert.match(source, /className=\{party\.id === value \? "party-result is-selected" : "party-result"\}/);
  assert.match(source, /event\.key === "Enter"/);
  assert.equal(typeof PartySelect, "function");
  const editor = readFileSync(path.join(__dirname, "..", "src", "components", "InventoryForms.tsx"), "utf8");
  assert.match(editor, /emptyHint="Only vendors mapped to this product can be preferred/);
});

test("category and brand pages use a slim hero with a green WhatsApp action", () => {
  const page = readFileSync(path.join(__dirname, "..", "src", "pages", "BrandPage.tsx"), "utf8");
  const css = readFileSync(path.join(__dirname, "..", "src", "styles.css"), "utf8");
  assert.match(page, /className="catalog-hero catalog-hero-slim"/);
  assert.match(page, /productCount\(data\.products\.length\)/);
  assert.doesNotMatch(page, /\{email\} \u2192/);
  assert.match(css, /\.catalog-hero-slim \.btn\.whatsapp-btn \{ background: #25d366/);
});

test("without online payment the cart becomes a WhatsApp enquiry list", async () => {
  const { cartMode, cartWords, enquiryMessage, enquiryWhatsappLink } = load("features/cartMode.ts", {});
  assert.equal(cartMode(true, "+91 98400"), "buy");
  assert.equal(cartMode(false, "+91 98400"), "enquiry");
  assert.equal(cartMode(false, ""), "none");
  assert.equal(cartWords("enquiry").add, "Add to enquiry");
  assert.equal(cartWords("buy").add, "Add to Cart");
  const message = enquiryMessage("SRU Global", [{ name: "Diya", option: "4 inch", quantity: 12, price: "450" }, { name: "Lamp", quantity: 3 }]);
  assert.equal(message, [
    "Hello SRU Global,", "I would like a quote for the following items.", "",
    "*Enquiry list*",
    "1. *Diya*", "   Option: 4 inch", "   Qty: *12*", "   Listed: \u20b9450 each", "",
    "2. *Lamp*", "   Qty: *3*", "",
    "*Summary*", "Products: 2", "Total units: 15", "Listed value: \u20b95,400", "",
    "Please share your best price, availability and delivery details.",
    "_This is an enquiry, not an order._",
  ].join("\n"));
  assert.match(enquiryWhatsappLink("+91 98400 11111", message), /^https:\/\/wa\.me\/919840011111\?text=Hello%20SRU%20Global%2C%0A/);

  // Enquiry cards add without a price or stock and keep WhatsApp as a small icon.
  const h = cardHarness({ selling_price_display: "", stock_qty: 0 });
  const html = renderToStaticMarkup(h.render(false, "9840011111"));
  assert.match(html, /Add to enquiry/);
  assert.match(html, /whatsapp-icon-only/);
  assert.doesNotMatch(html, /Add to Cart/);
  await find(h.render(false, "9840011111"), node => node.type === "button").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.added.length, 1);
  assert.doesNotMatch(renderToStaticMarkup(cardHarness().render(false, "")), /Add to enquiry|Add to Cart/);

  const source = file => readFileSync(path.join(__dirname, "..", "src", file), "utf8");
  const cartPage = source("pages/CartPage.tsx");
  assert.match(cartPage, /enquiryMessage\(/);
  assert.match(cartPage, /Send enquiry on WhatsApp/);
  assert.match(cartPage, /does not place an order or take payment/);
  assert.match(source("pages/ProductPage.tsx"), /className="btn enquiry-add"/);
  assert.match(source("components/Header.tsx"), /useCartMode\(!inPortal\)/);
});

test("bulk notes fold open when cut off and the category hero stays compact", () => {
  const source = file => readFileSync(path.join(__dirname, "..", "src", file), "utf8");
  for (const file of ["pages/HomePage.tsx", "pages/BrandPage.tsx", "pages/ProductPage.tsx"]) assert.match(source(file), /<BulkPricingNote /, file);
  assert.match(source("components/BulkPricingNote.tsx"), /scrollWidth > element\.clientWidth/);
  assert.match(source("styles.css"), /\.bulk-pricing\.is-open \{ flex-wrap: wrap; white-space: normal; \}/);
  const brand = source("pages/BrandPage.tsx");
  assert.match(brand, /whatsapp-btn hero-whatsapp/);
  assert.doesNotMatch(brand, /get_best_pricing/);
  // A quiet back-link row, then the heading, description and bulk note stacked with spacing.
  assert.match(brand, /className="brand-page-nav catalog-toolbar"[\s\S]*catalog-count[\s\S]*className="catalog-choose"[\s\S]*<BulkPricingNote /);
  assert.match(source("styles.css"), /\.catalog-choose \{ display: grid; justify-items: start; gap: 8px/);
});
test("cart rows give the quantity stepper its full width so plus is never clipped", () => {
  const css = readFileSync(path.join(__dirname, "..", "src", "styles.css"), "utf8");
  assert.match(css, /\.cart-item \{ grid-template-columns: 80px minmax\(0, 1fr\) auto; \}/);
  assert.match(css, /\.cart-item-quantity \.quantity-stepper \{ grid-template-columns: 36px 52px 36px;/);
});