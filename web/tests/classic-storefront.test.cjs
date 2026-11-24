const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function load(file, mocks = {}, globals = {}) {
  const exports = {};
  const source = readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require: name => {
    if (!(name in mocks)) throw new Error(`Missing mock: ${name}`);
    return mocks[name];
  }, ...globals });
  return exports;
}

const element = (type, props) => ({ type, props });
const jsx = { jsx: element, jsxs: element, Fragment: "fragment" };
const { classicSections, CLASSIC_COPY_FIELDS } = load("features/catalog/classicStorefront.ts");
const themeHelpers = load("features/siteTheme.ts");
const previewHelpers = load("features/catalog/storefrontPreview.ts");
const textHelpers = load("features/catalog/storefrontText.ts");
const linkHelpers = load("features/catalog/storefrontLinks.ts", { "./storefrontText": textHelpers }, { URL });
const home = Object.fromEntries(Object.values(CLASSIC_COPY_FIELDS).flat().map(([key]) => [key, `Saved ${key}`]));
home.hero_service_one = "CURATE";
home.hero_service_two = "CUSTOMISE";
home.hero_service_three = "DELIVER";
const company = {
  id: "company", company_name: "Classic Store", tenant_slug: "classic-store", storefront_template: "current",
  email: "hello@example.test", site_theme: {}, invoice_settings: {},
  storefront_content: { home, navigation: { collection: "Our story" }, footer: { catalogue_label: "Catalogue" }, display: {} },
};
const data = {
  company, sections: [],
  categories: Array.from({ length: 5 }, (_, i) => ({ id: `c${i}`, category_slug: `cat-${i}`, category_title: `Category ${i}`, category_description: `Description ${i}` })),
  brands: [{ id: "b1", code: "brand", name: "Brand" }],
  best_sellers: [{ id: "p1", name: "Product 1" }],
  sru_specials: [{ id: "p2", name: "Product 2" }],
  catalog_products: [{ id: "p1", name: "Product 1" }, { id: "p2", name: "Product 2" }],
};

function all(node, predicate) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(item => all(item, predicate));
  return [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
}

function text(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node !== "object") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  return text(node.props?.children);
}

function renderHome(sections, overrides = {}) {
  let state = 0;
  const mocks = {
    "react/jsx-runtime": jsx,
    react: { useEffect() {}, useRef: () => ({ current: null }), useState: () => [state++ === 0 ? {
      ...data, ...overrides, sections: sections.filter(section => section.is_enabled),
      classic_sections_configured: sections.some(section => !!section.configuration.classic_slot),
    } : undefined, () => {}] },
    "react-router-dom": { Link: "Link", useLocation: () => ({ search: "", hash: "" }) },
    "../components/BulkPricingNote": { BulkPricingNote: "BulkPricingNote" },
    "../components/SiteFooter": { SiteFooter: "SiteFooter" },
    "../components/sectionScroll": {},
    "../api": {},
    "../features/catalog/constants": { FALLBACK_EMAIL: "", FALLBACK_PHONE: "" },
    "../features/catalog/components/ProductCard": { ProductCard: "ProductCard" },
    "../features/catalog/components/BrandCard": { BrandCard: "BrandCard" },
    "../components/ProductRail": { ProductRail: "ProductRail" },
    "../features/catalog/storefrontDisplay": { storefrontDisplay: () => ({ whatsapp_enquiry_enabled: true, show_bulk_pricing: true }) },
    "../features/catalog/StorefrontThemeHome": { StorefrontThemeHome: "StorefrontThemeHome" },
    "../features/catalog/utils": { toAssetUrl: value => value },
    "../features/catalog/storefrontText": textHelpers,
    "../features/catalog/storefrontLinks": linkHelpers,
    "lucide-react": { Package: "Package" },
    "../features/auth": { useAuth: () => ({ storefront: company }) },
    "../features/useCheckoutAvailability": { useCheckoutAvailability: () => ({ availability: { enabled: true } }) },
  };
  return load("pages/HomePage.tsx", mocks, { URLSearchParams }).HomePage();
}

test("Classic defaults retain the exact visible catalog selection and native hero when materialized", () => {
  const sections = classicSections(data);
  assert.deepEqual(Array.from(sections, section => section.section_type), ["hero", "categories", "products", "products", "brands"]);
  assert.deepEqual(Array.from(sections[1].category_ids), ["c0", "c1", "c2", "c3"]);
  const legacy = renderHome([]);
  const editable = renderHome(sections);
  const meaningful = tree => all(tree, node => ["h1", "h2", "h3", "ProductCard", "BulkPricingNote"].includes(node.type))
    .map(node => node.type === "ProductCard" ? node.props.product.id : node.type === "BulkPricingNote" ? node.props.heading : text(node));
  assert.deepEqual(meaningful(editable), meaningful(legacy));
  const hero = tree => all(tree, node => node.type === "section" && node.props.className.split(" ").includes("hero"))[0];
  assert.equal(text(hero(editable)), text(hero(legacy)));
  assert.deepEqual(all(editable, node => node.type === "Link").map(node => node.props.to),
    all(legacy, node => node.type === "Link").map(node => node.props.to));
});

test("the editor preserves Classic edits and selections while fitting desktop and mobile previews", async () => {
  const state = [], effects = [], calls = [], refs = [];
  const savedCompany = { ...company, storefront_template: undefined, storefront_content: { ...company.storefront_content, links: {
    "hero.primary": { label: "Existing hero action", href: "/#contact" },
  } } };
  let slot = 0, refSlot = 0, firstRender = true, resize, observed, disconnected = false;
  const mocks = {
    "react/jsx-runtime": jsx,
    react: {
      useState: initial => {
        const index = slot++;
        if (!(index in state)) state[index] = initial;
        return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
      },
      useEffect: effect => { if (firstRender) effects.push(effect); },
      useMemo: fn => fn(), useCallback: fn => fn, useRef: () => refs[refSlot++] ||= { current: null },
    },
    "react-router-dom": { Link: "Link" },
    "lucide-react": Object.fromEntries(["ChevronDown", "ChevronUp", "Monitor", "Plus", "Save", "Smartphone", "Trash2", "Upload"].map(name => [name, name])),
    "../api": { api: {
      company: async () => savedCompany, storefrontSections: async () => [], storefrontPreview: async () => data,
      inventoryProducts: async () => ({ items: [] }), inventoryMasterEntries: async () => ({ items: [] }),
      updateCompany: async payload => { calls.push(payload); return { ...company, ...payload }; },
      saveStorefrontSections: async sections => { calls.push(sections); return { sections }; },
    } },
    "../components/Notifications": { FloatingAlert: "FloatingAlert" },
    "../components/PortalHomeLink": { PortalHomeLink: "PortalHomeLink" },
    "../features/siteTheme": themeHelpers,
    "../features/tenantTransport": { tenantBase: () => "/c/classic-store" },
    "../features/catalog/utils": { toAssetUrl: value => value },
    "../features/catalog/classicStorefront": { classicSections, CLASSIC_COPY_FIELDS },
    "../features/catalog/storefrontPreview": previewHelpers,
    "../features/catalog/boutiqueImages": load("features/catalog/boutiqueImages.ts"),
    "../features/catalog/storefrontLinks": linkHelpers,
  };
  const { StorefrontDesignPage } = load("pages/StorefrontDesignPage.tsx", mocks, {
    window: { addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { origin: "http://localhost" } }, Event: class {},
    ResizeObserver: class {
      constructor(callback) { resize = callback; }
      observe(node) { observed = node; }
      disconnect() { disconnected = true; }
    },
  });
  const render = () => { slot = 0; refSlot = 0; const result = StorefrontDesignPage(); firstRender = false; return result; };
  render();
  effects.forEach(effect => effect());
  await new Promise(resolve => setImmediate(resolve));
  let tree = render();
  const summaries = all(tree, node => node.type === "summary").map(text);
  for (const name of ["Header", "Hero", "Categories", "Best sellers", "Specials", "Brands", "Why", "Contact", "About / collection story", "Footer"]) {
    assert.ok(summaries.some(summary => summary.includes(name)), `Missing ${name}`);
  }
  assert.equal(all(tree, node => node.type === "h3" && text(node) === "Links & buttons").length, 0);
  const panel = name => all(tree, node => node.type === "details" &&
    all(node.props.children?.[0], child => child.type === "strong" && text(child) === name).length)[0];
  for (const [name, keys] of [
    ["Header", ["nav.cart", "nav.shopper_account", "nav.sign_in"]],
    ["Hero", ["section.classic-hero.hero.primary", "section.classic-hero.hero.secondary"]],
    ["Categories", ["category.card", "categories.more"]],
    ["Brands", ["brand.card"]],
    ["Why", ["why.contact"]],
    ["Contact", ["contact.whatsapp", "contact.email", "contact.phone"]],
    ["Footer", ["footer.categories", "footer.account", "footer.about", "catalog.explore"]],
  ]) {
    for (const key of keys) {
      assert.equal(all(panel(name), node => node.props.definition?.key === key).length, 1, `${key} belongs in ${name}`);
    }
  }
  for (const name of ["Best sellers", "Specials"]) {
    assert.ok(all(panel(name), node => node.type === "input" && node.props.value === "Add to Cart").length);
  }
  assert.equal(all(panel("Header"), node => node.type === "input" && node.props.value === "My Account").length, 1);
  assert.equal(all(tree, node => node.props.definition?.key === "why.contact").length, 1);
  assert.equal(all(tree, node => node.props.definition?.key === "hero.primary").length, 0);
  assert.equal(all(panel("Hero"), node => node.props.definition?.key === "section.classic-hero.hero.primary")[0]
    .props.definition.label, "Existing hero action");
  all(panel("Specials"), node => node.type === "input" && node.props.value === "Add to Cart")[0]
    .props.onChange({ target: { value: "Add to bag" } });
  tree = render();
  for (const name of ["Best sellers", "Specials"]) {
    assert.equal(all(panel(name), node => node.type === "input" && node.props.value === "Add to bag").length, 1);
  }
  const field = (tree, value) => all(tree, node => ["input", "textarea"].includes(node.type) && node.props.value === value)[0];
  for (const key of ["hero_heading_first", "why_heading_first", "contact_heading_first", "collection_heading_first"]) {
    assert.ok(field(tree, home[key]), `Default copy not loaded: ${key}`);
  }
  const fixed = all(tree, node => node.type === "details" && /Fixed at (top|bottom)/.test(text(node.props.children[0])));
  assert.equal(fixed.length, 2);
  fixed.forEach(node => assert.equal(all(node, child => child.props.className === "storefront-design-section-actions").length, 0));
  field(tree, home.hero_heading_first).props.onChange({ target: { value: "Edited Classic hero" } });
  field(render(), company.email).props.onChange({ target: { value: "Edited footer" } });
  tree = render();
  await all(tree, node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls[0].storefront_content.home.hero_heading_first, "Edited Classic hero");
  assert.equal(calls[0].storefront_content.footer.contact_text, "Edited footer");
  assert.equal(calls[0].storefront_content.product.add_to_cart, "Add to bag");
  assert.equal(calls[1].length, 5);
  assert.deepEqual(Array.from(calls[1][2].product_ids), ["p1"]);
  assert.equal(calls[1][0].configuration.classic_slot, "hero");
  all(render(), node => node.type === "button" && text(node) === "Hero")[0].props.onClick();
  await all(render(), node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls[3].length, 6);
  assert.equal(calls[3][0].configuration.classic_slot, "hero");
  assert.deepEqual(Array.from(calls[3][2].product_ids), ["p1"]);
  all(render(), node => node.type === "select" && node.props.value === "current")[0].props.onChange({ target: { value: "marketplace" } });
  assert.equal(all(render(), node => node.props["aria-label"] === "Accent colour")[0].props.value, "#ffd15a");
  assert.ok(all(render(), node => node.type === "input" && node.props.value === "Edited Classic hero").length);
  tree = render();
  for (const key of ["hero.primary", "hero.secondary", "quick.categories", "quick.about"]) {
    assert.equal(all(panel("Hero"), node => node.props.definition?.key === `section.classic-hero.${key}`).length, 1);
  }

  const canvas = all(render(), node => node.props.className === "storefront-preview-canvas")[0];
  const canvasElement = {};
  canvas.props.ref.current = canvasElement;
  const disconnect = effects[0]();
  assert.equal(observed, canvasElement);
  const dimensions = () => {
    const tree = render();
    return {
      frame: all(tree, node => node.props.className === "storefront-preview-frame")[0].props.style,
      iframe: all(tree, node => node.type === "iframe")[0].props.style,
    };
  };
  resize([{ contentRect: { width: 720, height: 572 } }]);
  assert.equal(dimensions().iframe.width, 1440);
  assert.equal(dimensions().iframe.transform, "scale(0.5)");
  assert.equal(dimensions().iframe.height, 1144);
  assert.equal(dimensions().frame.width, 720);
  assert.equal(dimensions().frame.height, 572);
  assert.match(text(render()), /1440px desktop.*50%.*Fit to panel/);
  all(render(), node => node.type === "button" && text(node) === "Mobile")[0].props.onClick();
  assert.equal(dimensions().iframe.width, 390);
  assert.equal(dimensions().iframe.transform, "scale(1)");
  resize([{ contentRect: { width: 280, height: 472 } }]);
  assert.equal(dimensions().frame.width, 280);
  assert.equal(dimensions().iframe.transform, `scale(${280 / 390})`);
  assert.equal(dimensions().iframe.height * (280 / 390), 472);
  all(render(), node => node.type === "button" && text(node) === "Desktop")[0].props.onClick();
  assert.equal(dimensions().iframe.width, 1440);
  assert.equal(dimensions().iframe.transform, `scale(${280 / 1440})`);
  resize([{ contentRect: { width: 1800, height: 572 } }]);
  assert.equal(dimensions().frame.width, 1440);
  assert.equal(dimensions().iframe.transform, "scale(1)");
  disconnect();
  assert.equal(disconnected, true);

  const messages = [];
  all(render(), node => node.type === "iframe")[0].props.ref.current = {
    contentWindow: { postMessage: message => messages.push(message) },
  };
  all(render(), node => node.type === "button" && text(node) === "Products")[0].props.onClick();
  all(render(), node => node.type === "iframe")[0].props.onLoad();
  const draft = messages.at(-1);
  assert.equal(draft.sections[2].products[0], data.catalog_products[0]);
  assert.equal(draft.sections.at(-1).product_ids.length, 0);
  assert.ok(draft.sections.at(-1).products.every(product => product.id.startsWith("storefront-preview-marketplace-")));
  const notice = () => all(render(), node => node.props.className === "storefront-preview-notice")[0];
  const sampleSwitch = all(notice(), node => node.type === "input")[0];
  sampleSwitch.props.onChange({ target: { checked: true } });
  all(render(), node => node.type === "iframe")[0].props.onLoad();
  assert.ok(messages.at(-1).sections[2].products.every(product => product.id.startsWith("storefront-preview-")));
  await all(render(), node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const saved = calls.at(-1);
  assert.equal(saved.at(-1).product_ids.length, 0);
  assert.equal(saved.at(-1).products, undefined);
  assert.deepEqual(Array.from(saved[2].product_ids), ["p1"]);
  assert.ok(!JSON.stringify(saved).includes("storefront-preview-"));
  const productPicker = all(render(), node => node.type === "select" && node.props.multiple && node.props.value.includes("p1"))[0];
  productPicker.props.onChange({ currentTarget: { selectedOptions: [{ value: "p2" }] } });
  assert.equal(all(notice(), node => node.type === "input")[0].props.checked, false);
  all(render(), node => node.type === "iframe")[0].props.onLoad();
  assert.equal(messages.at(-1).sections[2].products[0], data.catalog_products[1]);
  const actionField = all(render(), node => node.props.definition?.key === "section.classic-hero.hero.primary")[0];
  actionField.props.onChange({ label: "Shop new arrivals", href: "/#section-classic-specials" });
  await all(render(), node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.at(-2).storefront_content.links["section.classic-hero.hero.primary"].href, "/#section-classic-specials");
  assert.equal(calls.at(-2).storefront_content.links["section.classic-hero.hero.primary"].label, "Shop new arrivals");
  assert.equal(calls.at(-2).storefront_content.links["hero.primary"].label, "Existing hero action");
  assert.equal(all(render(), node => node.type === "PortalHomeLink").length, 0);
  const addMenu = () => all(render(), node => node.type === "button" && text(node) === "Add menu item")[0];
  addMenu().props.onClick();
  addMenu().props.onClick();
  assert.equal(addMenu().props.disabled, true);
  const menuField = all(render(), node => node.props.definition?.key === "menu-1")[0];
  menuField.props.onChange({ label: "Our brands", href: "/brand?view=brands" });
  const menuToggle = all(render(), node => node.type === "label" && text(node) === "Show Our brands")[0];
  all(menuToggle, node => node.type === "input")[0].props.onChange({ target: { checked: false } });
  await all(render(), node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const savedMenu = calls.at(-2).storefront_content.header_menu;
  assert.equal(savedMenu.length, 9);
  assert.equal(savedMenu.find(item => item.key === "menu-1").href, "/brand?view=brands");
  assert.equal(savedMenu.find(item => item.key === "menu-1").is_enabled, false);
  all(render(), node => node.type === "button" && text(node) === "Remove menu 9")[0].props.onClick();
  assert.equal(addMenu().props.disabled, false);
  const callsBefore = calls.length;
  all(render(), node => node.type === "select" && node.props.value === "marketplace")[0].props.onChange({ target: { value: "boutique" } });
  const journal = all(render(), node => node.props.label === "Journal image 1")[0];
  assert.ok(journal.props.value.includes("photo-1600166898405"));
  journal.props.onChange("https://example.com/my-journal.jpg");
  all(render(), node => node.props.label === "Journal image 2")[0].props.onChange(null);
  all(render(), node => node.type === "iframe")[0].props.onLoad();
  assert.equal(messages.at(-1).company.storefront_content.images.why_left, "https://example.com/my-journal.jpg");
  assert.equal(messages.at(-1).company.storefront_content.images.why_right, null);
  await all(render(), node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.at(-2).storefront_content.images.why_left, "https://example.com/my-journal.jpg");
  assert.equal(calls.at(-2).storefront_content.images.why_right, null);
  const callsAfterImages = calls.length;
  all(render(), node => node.props.definition?.key === "section.classic-hero.hero.primary")[0].props.onChange({ href: "javascript:alert(1)" });
  await all(render(), node => node.type === "button" && text(node).includes("Save design"))[0].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(callsAfterImages, callsBefore + 2);
  assert.equal(calls.length, callsAfterImages);
  assert.match(text(render()), /Fix the invalid destination/);
});

test("theme samples stay in preview copies and never replace explicit or unavailable product selections", () => {
  const empty = { ...data, categories: [], brands: [], catalog_products: [], best_sellers: [], sru_specials: [] };
  const sections = classicSections(empty);
  const before = JSON.stringify(sections);
  const firstNames = new Set();
  for (const template of ["current", "marketplace", "boutique", "heritage", "supermarket", "jewellery"]) {
    const preview = previewHelpers.storefrontPreviewSections(sections, empty, template);
    const shelves = preview.filter(section => section.section_type === "products");
    const products = shelves.flatMap(section => section.products);
    assert.equal(products.length, 8);
    assert.equal(new Set(products.map(product => product.id)).size, 8);
    assert.ok(products.every(product => product.id.startsWith(`storefront-preview-${template}-`) &&
      product.image_url.startsWith("https://images.unsplash.com/") && product.tags.includes("Sample")));
    assert.ok(shelves.every(section => section.product_ids.length === 0));
    firstNames.add(products[0].name);
  }
  assert.equal(firstNames.size, 6);
  assert.equal(JSON.stringify(sections), before);
  const selected = classicSections(data);
  selected[2].product_ids = ["p2", "p1"];
  selected[3].product_ids = ["no-longer-available"];
  const preview = previewHelpers.storefrontPreviewSections(selected, data, "marketplace");
  assert.deepEqual(Array.from(preview[2].products, product => product.id), ["p2", "p1"]);
  assert.equal(preview[2].products[0], data.catalog_products[1]);
  assert.equal(preview[3].products.length, 0);
  const showcase = previewHelpers.storefrontPreviewSections(selected, data, "boutique", true);
  assert.deepEqual(Array.from(showcase[2].product_ids), ["p2", "p1"]);
  assert.ok(showcase[2].products.every(product => product.id.startsWith("storefront-preview-boutique-")));
  assert.deepEqual(Array.from(selected[2].product_ids), ["p2", "p1"]);
  const hidden = sections.map(section => ({ ...section, is_enabled: false }));
  assert.ok(previewHelpers.storefrontPreviewSections(hidden, empty, "boutique")
    .every(section => section.products.length === 0));
});

test("preview shopping actions are blocked for keyboard and pointer input without blocking live shopping or scrolling", () => {
  const source = ts.createSourceFile("App.tsx", readFileSync(path.join(__dirname, "..", "src", "App.tsx"), "utf8"), ts.ScriptTarget.Latest);
  const mocks = { "react/jsx-runtime": jsx };
  for (const statement of source.statements.filter(ts.isImportDeclaration)) {
    const bindings = statement.importClause?.namedBindings;
    if (bindings && ts.isNamedImports(bindings)) {
      mocks[statement.moduleSpecifier.text] ||= {};
      for (const binding of bindings.elements) mocks[statement.moduleSpecifier.text][binding.name.text] = binding.name.text;
    }
  }
  let search = "?storefrontPreview=company", blocked = 0;
  mocks.react = { useState: initial => [initial, () => {}], useEffect() {} };
  mocks["react-router-dom"] = { Route: "Route", Routes: "Routes", useLocation: () => ({ pathname: "/", search }) };
  mocks["./features/auth"] = { useAuth: () => ({ user: null, storefront: company }) };
  mocks["./features/tenantTransport"] = { tenantBase: () => "", tenantApiOrigin: () => "" };
  const App = load("App.tsx", mocks, { URLSearchParams }).default;
  const event = { preventDefault() { blocked++; }, stopPropagation() { blocked++; } };
  const preview = App();
  preview.props.onClickCapture(event);
  preview.props.onSubmitCapture(event);
  preview.props.onKeyDownCapture({ ...event, key: "Enter" });
  preview.props.onKeyDownCapture({ ...event, key: " " });
  assert.equal(blocked, 8);
  preview.props.onKeyDownCapture({ ...event, key: "PageDown" });
  assert.equal(blocked, 8);
  search = "";
  const live = App();
  assert.equal(live.props.onClickCapture, undefined);
  assert.equal(live.props.onSubmitCapture, undefined);
  live.props.onKeyDownCapture({ ...event, key: "Enter" });
  assert.equal(blocked, 8);
});

test("hiding the default hero or all curated sections does not resurrect the legacy fallback", () => {
  const sections = classicSections(data);
  sections[0].is_enabled = false;
  assert.equal(all(renderHome(sections), node => node.type === "section" && node.props.className.split(" ").includes("hero")).length, 0);
  const hidden = renderHome(sections.map(section => ({ ...section, is_enabled: false })));
  assert.equal(all(hidden, node => node.type === "ProductCard").length, 0);
  assert.equal(all(hidden, node => node.type === "h1").length, 0);
  assert.ok(text(hidden).includes(home.collection_heading_first));
});

test("footer preview uses the draft text while untouched footers keep the contact email", () => {
  const { SiteFooter } = load("components/SiteFooter.tsx", {
    "react/jsx-runtime": jsx, "../features/auth": { useAuth: () => ({ storefront: company }) },
    "../features/catalog/storefrontText": textHelpers,
    "../features/catalog/storefrontLinks": linkHelpers,
    "react-router-dom": { Link: "Link" },
  });
  assert.match(text(SiteFooter()), /hello@example\.test/);
  assert.match(text(SiteFooter({ company: { ...company, storefront_content: {
    ...company.storefront_content, footer: { contact_text: "From {company_name}" },
  } } })), /From Classic Store/);
  const marketplaceFooter = SiteFooter({ company: { ...company, storefront_template: "marketplace" } });
  assert.equal(marketplaceFooter.props.className, "marketplace-footer");
  assert.match(text(marketplaceFooter), /hello@example\.test/);
  assert.ok(all(marketplaceFooter, node => node.type === "Link" && node.props.to === "/account").length);
  const boutiqueFooter = SiteFooter({ company: { ...company, storefront_template: "boutique",
    storefront_content: { ...company.storefront_content, links: { "footer.about": { label: "Our atelier", href: "/#why" } } } } });
  assert.ok(boutiqueFooter.props.className.includes("boutique-footer"));
  assert.ok(all(boutiqueFooter, node => node.type === "Link" && node.props.to === "/brand?view=brands").length);
  assert.ok(all(boutiqueFooter, node => node.type === "Link" && node.props.to === "/#why" && text(node) === "Our atelier").length);
});

function renderMarketplace(overrides = {}, template = "marketplace") {
  const expand = (type, props) => typeof type === "function" ? type(props) : element(type, props);
  const { StorefrontThemeHome } = load("features/catalog/StorefrontThemeHome.tsx", {
    "react/jsx-runtime": { jsx: expand, jsxs: expand },
    "react-router-dom": { Link: "Link" }, "lucide-react": { Package: "Package" },
    "../../components/ProductRail": { ProductRail: "ProductRail" },
    "./components/ProductCard": { ProductCard: "ProductCard" },
    "./components/BrandCard": { BrandCard: "BrandCard" },
    "./utils": { toAssetUrl: value => value }, "./classicStorefront": { classicSections },
    "./marketplaceImages": load("features/catalog/marketplaceImages.ts"),
    "./boutiqueImages": load("features/catalog/boutiqueImages.ts"),
    "./storefrontLinks": linkHelpers,
  });
  return StorefrontThemeHome({
    template, data: { ...data, ...overrides }, phone: "919876543210", email: company.email,
    checkoutEnabled: true, text: key => (overrides.company || company).storefront_content.home[key] || key, bulkNote: "Bulk pricing",
  });
}

test("homepage actions honour global and per-section settings and every selectable section has a stable anchor", () => {
  const sections = classicSections(data);
  const configured = { ...company, storefront_content: { ...company.storefront_content, links: {
    "hero.primary": { label: "See our arrivals", href: "/#section-classic-specials" },
    "hero.secondary": { label: "Read our story", href: "https://example.com/story" },
    "section.classic-hero.hero.primary": { label: "Explore this edit", href: "/#section-classic-brands" },
    "section.classic-best-sellers.section.view_all": { label: "See these products", href: "/brand?q=new" },
  } } };
  for (const template of ["current", "marketplace", "boutique", "heritage", "supermarket", "jewellery"]) {
    const store = { ...configured, storefront_template: template };
    const tree = template === "current" ? renderHome(sections, { company: store }) : renderMarketplace({ company: store, sections }, template);
    const links = all(tree, node => node.type === "Link");
    assert.ok(links.some(link => link.props.to === "/#section-classic-brands" && text(link) === "Explore this edit"), template);
    assert.ok(links.some(link => link.props.to === "https://example.com/story" && text(link) === "Read our story"), template);
    assert.ok(links.some(link => link.props.to === "/brand?q=new" && text(link) === "See these products"), template);
    const ids = new Set(all(tree, node => !!node.props.id).map(node => node.props.id));
    for (const target of linkHelpers.storefrontSectionTargets(sections, template)) {
      assert.ok(ids.has(target.href.split("#")[1]), `Missing ${target.href} in ${template}`);
    }
  }
  const hidden = sections.map(section => ({ ...section, is_enabled: section.section_type === "hero" }));
  assert.ok(!linkHelpers.storefrontSectionTargets(hidden, "current").some(target => target.href === "/#section-classic-brands"));
});

test("link defaults remain item-specific and unsafe destinations are not rendered", () => {
  const store = { ...company, storefront_content: { ...company.storefront_content, links: {
    "hero.primary": { label: "Visit {company_name}", href: "#contact" },
    "brand.card": { href: "javascript:alert(1)" },
  } } };
  const action = linkHelpers.storefrontLink(store, "hero.primary", "/", "Shop");
  assert.equal(action.to, "/#contact");
  assert.equal(action.children, "Visit Classic Store");
  assert.equal(linkHelpers.storefrontLink(store, "category.card", "/brand?category=one", "Browse").to, "/brand?category=one");
  assert.equal(linkHelpers.storefrontLink(store, "category.card", "/brand?category=two", "Browse").to, "/brand?category=two");
  assert.equal(linkHelpers.storefrontLink(store, "brand.card", "/brand?brand=actual", "Browse").to, "/brand?brand=actual");
  const cleared = { ...company, storefront_content: { ...company.storefront_content, links: {
    "section.classic-best-sellers.section.view_all": { label: " ", href: "" },
    "why.contact": { label: "", href: "" },
  } } };
  assert.equal(linkHelpers.hasStorefrontLinkOverride(cleared, "section.view_all", "classic-best-sellers"), false);
  assert.equal(all(renderHome(classicSections(data), { company: cleared }), node => node.type === "Link" && text(node) === "View all").length, 0);
  for (const href of ["/brand?category=all", "/#why", "#contact", "https://example.com/products", "mailto:hello@example.com", "tel:+919999999999"]) {
    assert.equal(linkHelpers.isStorefrontHref(href), true, href);
  }
  for (const href of ["javascript:alert(1)", "data:text/html,test", "//example.com", "/\\example.com", "#", "not a link", "https://example.com/\npath"]) {
    assert.equal(linkHelpers.isStorefrontHref(href), false, href);
  }
});

test("Marketplace hero buttons and both large panels have independent section controls", () => {
  const sections = classicSections(data);
  const actions = {
    "hero.primary": { label: "Primary button", href: "/#contact" },
    "hero.secondary": { label: "Secondary button", href: "/#brands" },
    "quick.categories": { label: "Category panel", href: "/#categories" },
    "quick.about": { label: "Story panel", href: "/#collection-special" },
  };
  const store = { ...company, storefront_template: "marketplace", storefront_content: {
    ...company.storefront_content, links: Object.fromEntries(Object.entries(actions).map(([key, value]) => [`section.classic-hero.${key}`, value])),
  } };
  const definitions = linkHelpers.storefrontLinkDefinitions(store, sections);
  const hero = all(renderMarketplace({ company: store, sections }), node => node.props.id === "section-classic-hero")[0];
  for (const [key, value] of Object.entries(actions)) {
    assert.ok(definitions.some(definition => definition.group === "Individual sections" && definition.key === `section.classic-hero.${key}`));
    assert.ok(all(hero, node => node.type === "Link" && node.props.to === value.href && text(node).includes(value.label)).length, key);
  }
});

test("Marketplace renders the reference layout with Classic selections and all existing content areas", () => {
  const tree = renderMarketplace();
  assert.equal(all(tree, node => node.props.className === "marketplace-quick-links").length, 1);
  assert.equal(all(tree, node => node.type === "h1").map(text)[0],
    `${home.hero_heading_first} ${home.hero_heading_second}`);
  assert.deepEqual(all(tree, node => node.type === "ProductCard").map(node => node.props.product.id), ["p1", "p2"]);
  const categoryLinks = all(tree, node => node.props.className === "marketplace-category-tile");
  assert.equal(categoryLinks.length, 4);
  assert.equal(categoryLinks[0].props.to, "/brand?category=cat-0");
  for (const key of ["why_description", "contact_description", "collection_heading_first", "collection_point_three_body"]) {
    assert.ok(text(tree).includes(home[key]), `Missing Classic content: ${key}`);
  }
  assert.ok(all(tree, node => node.type === "Link" && node.props.to === "https://wa.me/919876543210").length);
  const { MARKETPLACE_IMAGES } = load("features/catalog/marketplaceImages.ts");
  assert.ok(all(tree, node => node.type === "img" && node.props.src === MARKETPLACE_IMAGES.hero).length);
  assert.equal(all(tree, node => node.props.className === "marketplace-story-image").length, 2);
});

test("Marketplace preserves curated order, uploaded hero image, styles and disabled Classic sections", () => {
  const sections = classicSections(data);
  sections[0].image_url = "uploads/custom-hero.jpg";
  sections[0].configuration.background_color = "#112233";
  const tree = renderMarketplace({ sections: [sections[0], sections[4], sections[2]], classic_sections_configured: true });
  assert.ok(all(tree, node => node.type === "img" && node.props.src === "uploads/custom-hero.jpg").length);
  const hero = all(tree, node => node.props.className?.includes("theme-hero-marketplace"))[0];
  assert.equal(hero.props.style.backgroundColor, "#112233");
  assert.deepEqual(all(tree, node => node.type === "section").slice(0, 3).map(node => node.props.id),
    ["section-classic-hero", "brands", "best-sellers"]);
  assert.equal(all(tree, node => node.type === "ProductCard").length, 1);
  const hidden = renderMarketplace({ sections: [], classic_sections_configured: true });
  assert.equal(all(hidden, node => node.type === "h1" || node.type === "ProductCard").length, 0);
  const noHero = renderMarketplace({ sections: sections.slice(1), classic_sections_configured: true });
  assert.equal(all(noHero, node => node.type === "h1").length, 0);
});

test("Boutique uses the editorial reference with editable Classic content and catalogue actions", () => {
  const sections = classicSections(data);
  const store = { ...company, storefront_template: "boutique", storefront_content: {
    ...company.storefront_content,
    images: { why_left: "uploads/makers.jpg", why_right: "uploads/occasion.jpg" },
    links: {
      "category.card": { label: "Discover this collection" },
      "brand.card": { label: "Meet this brand" },
      "why.contact": { label: "Talk to our stylist", href: "/#contact" },
      "contact.phone": { label: "Call our studio", href: "tel:+919999999999" },
      "section.classic-brands.section.view_all": { label: "All our designers", href: "/brand?view=brands" },
    },
  } };
  const tree = renderMarketplace({ company: store, sections }, "boutique");
  assert.deepEqual(all(tree, node => node.type === "ProductCard").map(node => node.props.product.id), ["p1", "p2"]);
  const categories = all(tree, node => node.props.className === "boutique-category-card");
  assert.equal(categories.length, 4);
  assert.equal(categories[0].props.to, "/brand?category=cat-0");
  assert.ok(text(categories[0]).includes("Discover this collection"));
  const brand = all(tree, node => node.type === "BrandCard")[0];
  assert.equal(brand.props.template, "boutique");
  assert.equal(brand.props.href, "/brand?brand=brand");
  assert.equal(brand.props.action, "Meet this brand");
  for (const id of ["why", "contact", "collection-special"]) {
    assert.equal(all(tree, node => node.props.id === id).length, 1);
  }
  for (const key of ["hero_primary_action", "hero_secondary_action", "hero_service_three",
    "why_heading_first", "why_description", "collection_heading_first", "collection_point_three_body", "contact_description"]) {
    assert.ok(text(tree).includes(home[key]), `Missing editable Boutique content: ${key}`);
  }
  for (const src of ["uploads/makers.jpg", "uploads/occasion.jpg"]) {
    assert.ok(all(tree, node => node.type === "img" && node.props.src === src).length);
  }
  for (const [label, href] of [["All our designers", "/brand?view=brands"], ["Call our studio", "tel:+919999999999"],
    ["Talk to our stylist", "/#contact"]]) {
    assert.ok(all(tree, node => node.type === "Link" && node.props.to === href && text(node) === label).length, label);
  }
  assert.ok(linkHelpers.storefrontSectionTargets(sections, "boutique").some(target => target.href === "/#why"));
});

test("Boutique defaults, removed sections, uploaded images and mapping order match the designer", () => {
  const { BOUTIQUE_IMAGES } = load("features/catalog/boutiqueImages.ts");
  const defaults = renderMarketplace({}, "boutique");
  assert.ok(all(defaults, node => node.type === "img" && node.props.src === BOUTIQUE_IMAGES.hero).length);
  assert.equal(all(defaults, node => node.props.className === "boutique-category-card").length, 4);
  const sections = classicSections(data);
  sections[0].image_url = "uploads/boutique-cover.jpg";
  sections[0].configuration = { ...sections[0].configuration, image_ratio: "portrait", image_fit: "contain" };
  const tree = renderMarketplace({ sections: [sections[0], sections[4], sections[2]], classic_sections_configured: true }, "boutique");
  const hero = all(tree, node => node.props.id === "section-classic-hero")[0];
  assert.equal(hero.props["data-image-ratio"], "portrait");
  assert.equal(hero.props["data-image-fit"], "contain");
  assert.ok(all(hero, node => node.type === "img" && node.props.src === "uploads/boutique-cover.jpg").length);
  assert.deepEqual(all(tree, node => node.type === "section").slice(0, 3).map(node => node.props.id),
    ["section-classic-hero", "brands", "best-sellers"]);
  for (const overrides of [
    { sections: [], classic_sections_configured: true },
    { sections: sections.map(section => ({ ...section, is_enabled: false })) },
    { sections: sections.slice(1), classic_sections_configured: true },
    { sections: [{ ...sections[2], configuration: {}, section_key: "custom-edit" }] },
  ]) {
    assert.equal(all(renderMarketplace(overrides, "boutique"), node => node.type === "h1").length, 0);
  }
});

test("Marketplace header retains search routing, cart quantities and enquiry mode", () => {
  const state = [], navigations = [];
  let slot = 0, mode = "buy";
  const store = { ...company, storefront_template: "marketplace" };
  const { Header } = load("components/Header.tsx", {
    "react/jsx-runtime": jsx,
    react: {
      useState: initial => {
        const index = slot++;
        if (!(index in state)) state[index] = initial;
        return [state[index], value => { state[index] = value; }];
      }, useEffect() {}, useRef: current => ({ current }),
    },
    "react-router-dom": { Link: "Link", useLocation: () => ({ pathname: "/", search: "" }), useNavigate: () => value => navigations.push(value) },
    "lucide-react": { Search: "Search" }, "../api": {},
    "../features/auth": { useAuth: () => ({ storefront: store, user: null }) },
    "../features/catalog/utils": { toAssetUrl: value => value },
    "../features/catalog/storefrontLinks": linkHelpers,
    "../features/siteTheme": {}, "../features/catalog/storefrontDisplay": {},
    "../features/tenantTransport": { tenantBase: () => "/c/classic-store" },
    "../features/catalog/storefrontText": textHelpers,
    "../features/cart": { useCart: () => ({ items: [{ quantity: 3 }] }) },
    "../features/useCheckoutAvailability": { useCartMode: () => ({ mode }) },
    "../features/cartMode": load("features/cartMode.ts"),
    "./WorkspaceBar": { WorkspaceBar: "WorkspaceBar" }, "./PortalNavigation": { PortalNavigation: "PortalNavigation" },
  });
  const render = previewCompany => { slot = 0; return Header({ menuOpen: false, onMenuToggle() {}, previewCompany }); };
  const tree = render();
  assert.ok(tree.props.className.includes("header-marketplace"));
  assert.equal(all(tree, node => node.props.className === "marketplace-departments").length, 1);
  assert.ok(text(all(tree, node => node.props.to === "/cart")[0]).includes("(3)"));
  all(tree, node => node.type === "input")[0].props.onChange({ target: { value: " blue mug " } });
  all(render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(navigations[0], "/brand?q=blue%20mug");
  mode = "enquiry";
  assert.ok(all(render(), node => node.props.className?.includes("header-enquiry-link")).length);
  store.storefront_content = { ...company.storefront_content, header_menu: [
    { key: "custom", label: "Our brands", href: "/brand?view=brands", is_enabled: true },
    { key: "hidden", label: "Hidden menu", href: "/#contact", is_enabled: false },
  ] };
  const menu = all(render(), node => node.props.className === "marketplace-departments")[0];
  assert.deepEqual(all(menu, node => node.type === "Link").map(node => [text(node), node.props.to]), [["Our brands", "/brand?view=brands"]]);
  store.storefront_content = { ...company.storefront_content, header_menu: [] };
  assert.equal(all(render(), node => node.props.className === "marketplace-departments").length, 0);
  assert.ok(all(render(), node => node.props.to === "/cart").length);
  const preview = render({ storefront_template: "marketplace", storefront_content: { ...company.storefront_content,
    header_menu: [{ key: "preview", label: "Preview menu", href: "/#contact", is_enabled: true }] } });
  assert.ok(all(preview, node => node.type === "Link" && text(node) === "Preview menu" && node.props.to === "/#contact").length);
  store.storefront_template = "boutique";
  store.storefront_content = { ...company.storefront_content };
  const boutique = render();
  assert.ok(boutique.props.className.includes("header-boutique"));
  assert.equal(all(boutique, node => node.props.className === "storefront-primary-menu").length, 0);
  assert.equal(all(boutique, node => node.props.className === "boutique-navigation").length, 1);
  assert.ok(text(all(boutique, node => node.props.to === "/cart")[0]).includes("(3)"));
  all(boutique, node => node.type === "input")[0].props.onChange({ target: { value: " linen kurta " } });
  all(render(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(navigations.at(-1), "/brand?q=linen%20kurta");
  store.storefront_content = { ...company.storefront_content, header_menu: [] };
  assert.equal(all(render(), node => node.props.className === "boutique-navigation").length, 0);
});

test("sample palettes follow the chosen design while custom colours survive theme changes", () => {
  const { storefrontSiteTheme, DEFAULT_SITE_THEME } = themeHelpers;
  const marketplace = storefrontSiteTheme(DEFAULT_SITE_THEME, "marketplace");
  assert.equal(marketplace.accent_color, "#ffd15a");
  assert.equal(marketplace.primary_color, "#173c59");
  assert.equal(storefrontSiteTheme(marketplace, "current").accent_color, DEFAULT_SITE_THEME.accent_color);
  const custom = { ...marketplace, accent_color: "#8844aa" };
  assert.equal(storefrontSiteTheme(custom, "current").accent_color, "#8844aa");
  assert.notEqual(storefrontSiteTheme(undefined, "boutique").primary_color, marketplace.primary_color);
  const painted = {};
  const { setSavedSiteTheme } = load("features/siteTheme.ts", {}, {
    document: { documentElement: { style: { setProperty: (key, value) => { painted[key] = value; } } } },
  });
  setSavedSiteTheme(DEFAULT_SITE_THEME, "marketplace");
  assert.equal(painted["--site-accent"], marketplace.accent_color);
  assert.equal(painted["--site-on-accent"], "#000000");
  setSavedSiteTheme(custom, "marketplace");
  assert.equal(painted["--site-accent"], "#8844aa");
});

test("brand cards have distinct themes and a failed logo falls back without losing the brand link", () => {
  let failed = "";
  const { BrandCard } = load("features/catalog/components/BrandCard.tsx", {
    "react/jsx-runtime": jsx, react: { useState: () => [failed, value => { failed = value; }] },
    "react-router-dom": { Link: "Link" }, "../utils": { toAssetUrl: value => value },
  });
  const props = { brand: { id: "brand", name: "Our Brand", code: "brand & co" }, caption: "Our collection", action: "Explore" };
  let classic = BrandCard(props);
  assert.equal(classic.props.to, "/brand?brand=brand%20%26%20co");
  all(classic, node => node.type === "img")[0].props.onError();
  classic = BrandCard(props);
  assert.equal(all(classic, node => node.type === "img").length, 0);
  assert.ok(text(classic).includes("OB"));
  const marketplace = BrandCard({ ...props, template: "marketplace" });
  assert.equal(marketplace.props["data-brand-theme"], "marketplace");
  assert.equal(all(marketplace, node => node.props.className === "logo-box").length, 0);
  assert.ok(text(marketplace).includes("Our collection"));
  const boutique = BrandCard({ ...props, template: "boutique", action: "View this studio →" });
  assert.equal(text(all(boutique, node => node.type === "em")[0]), "View this studio →");
  assert.equal(boutique.props.to, classic.props.to);
});

test("brand view-all actions use the brand directory and preserve explicit overrides", () => {
  const sections = classicSections(data);
  const tree = renderMarketplace({ sections });
  const shelf = all(tree, node => node.props.id === "brands")[0];
  assert.equal(all(shelf, node => node.type === "Link" && text(node).includes("View all"))[0].props.to, "/brand?view=brands");
  const store = { ...company, storefront_content: { ...company.storefront_content, links: {
    "section.classic-brands.section.view_all": { href: "/brand?brand=featured" },
  } } };
  const overridden = all(renderHome(sections, { company: store }), node => node.props.id === "brands")[0];
  assert.equal(all(overridden, node => node.type === "Link" && text(node) === "View all")[0].props.to, "/brand?brand=featured");
});

function renderCatalogPage(catalogData, query) {
  let state = 0;
  const { BrandPage } = load("pages/BrandPage.tsx", {
    "react/jsx-runtime": jsx, react: { useEffect() {}, useState: () => [state++ === 0 ? catalogData : undefined, () => {}] },
    "react-router-dom": { Link: "Link", useSearchParams: () => [new URLSearchParams(query)] },
    "../components/BulkPricingNote": {}, "../components/SiteFooter": { SiteFooter: "SiteFooter" },
    "../api": {}, "../features/catalog/constants": { FALLBACK_EMAIL: "", FALLBACK_PHONE: "" },
    "../features/catalog/components/ProductCard": { ProductCard: "ProductCard" }, "../features/catalog/components/BrandCard": { BrandCard: "BrandCard" },
    "../features/catalog/storefrontDisplay": { storefrontDisplay: () => ({ whatsapp_enquiry_enabled: false }) },
    "../features/catalog/productGroups": load("features/catalog/productGroups.ts"),
    "../features/catalog/utils": { toAssetUrl: value => value }, "../features/tenantTransport": { tenantBase: () => "/c/classic-store" },
    "../features/catalog/storefrontText": textHelpers, "../features/auth": { useAuth: () => ({ storefront: catalogData.company }) },
    "lucide-react": { MessageCircle: "MessageCircle", Package: "Package" },
    "../features/useCheckoutAvailability": { useCheckoutAvailability: () => ({}) },
  }, { URLSearchParams });
  return BrandPage();
}

test("all-brands directory renders brands rather than category cards and handles an empty catalogue", () => {
  const render = brands => renderCatalogPage({ ...data, brands, products: [] }, "view=brands");
  const tree = render(data.brands);
  assert.equal(all(tree, node => node.type === "BrandCard")[0].props.brand.id, "b1");
  assert.equal(all(tree, node => node.props.heading === "All brands").length, 1);
  assert.equal(all(tree, node => node.props.className === "category-card").length, 0);
  assert.match(text(render([])), /No brands available yet/);
});

test("Boutique listing headers are text-only while catalogue card images and actions remain available", () => {
  const category = { ...data.categories[0], image_url: "https://example.test/category.jpg" };
  const product = { ...data.catalog_products[0], image_url: "https://example.test/product.jpg" };
  const store = { ...company, storefront_template: "boutique", storefront_content: { ...company.storefront_content,
    catalog: { all_categories_heading_first: "Shop by", all_categories_heading_second: "category", back_home: "Back to home",
      product_count: "{count} products" },
  } };
  for (const query of ["category=all", `category=${category.category_slug}`, "view=brands", "q=gift"]) {
    const tree = renderCatalogPage({ ...data, company: store, selected_category: category, categories: [category], products: [product] }, query);
    const banner = all(tree, node => typeof node.type === "function" && node.type.name === "CatalogThemeBanner")[0];
    const header = banner.type(banner.props);
    assert.equal(all(header, node => ["img", "figure", "Package"].includes(node.type)).length, 0, query);
    assert.equal(text(all(header, node => node.type === "h1")[0]), banner.props.heading);
    assert.ok(text(header).includes(banner.props.count));
    if (query === "category=all") {
      assert.equal(all(header, node => node.type === "a" && text(node) === "Back to home")[0].props.href, "/c/classic-store/#categories");
      assert.equal(all(tree, node => node.type === "img")[0].props.src, category.image_url);
    } else if (query !== "view=brands") {
      assert.equal(all(tree, node => node.type === "ProductCard")[0].props.product.image_url, product.image_url);
    }
    const marketplace = banner.type({ ...banner.props, template: "marketplace", image: category.image_url });
    assert.equal(all(marketplace, node => node.type === "img")[0].props.src, category.image_url);
  }
});
