const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const source = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
function load(file, overrides = {}) {
  const exports = {};
  const compiled = ts.transpileModule(source(file), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(compiled, { exports, window: overrides.window, require: name => overrides[name] || require(name) });
  return exports;
}
const navigation = load("features/portalNavigation.ts");
const Link = ({ to, children, ...props }) => React.createElement("a", { ...props, href: to }, children);

test("online operations come first and provider setup has a separate admin menu", () => {
  const owner = navigation.visiblePortalEntries({ role: "owner", modules: [] });
  assert.equal(owner.filter(entry => entry.group === "Operations")[0].path, "/portal/checkout");
  assert.equal(owner.find(entry => entry.path === "/portal/checkout-setup").group, "Admin");
  const staff = navigation.visiblePortalEntries({ role: "staff", modules: ["orders"] });
  assert.ok(!staff.some(entry => ["/portal/checkout", "/portal/checkout-setup"].includes(entry.path)));
  assert.match(source("App.tsx"), /path="\/portal\/checkout-setup" element={<CheckoutAdminPage key="setup" setupOnly/);
  assert.match(source("pages/PortalPage.tsx"), /const operationsLinks[^=]*= \[\s*{ label: "Online Orders"/);
  assert.match(source("styles.css"), /\.checkout-orders-heading select \{ width: 100%; min-width: 0; max-width: 100%; \}/);
});

test("order management and provider setup render separately and retain administrator access", () => {
  const render = (setupOnly, role = "owner", shipping = "shiprocket") => {
    const { CheckoutAdminPage } = load("pages/CheckoutAdminPage.tsx", {
      "../features/auth": { useAuth: () => ({ user: { role, company_name: "Example", tenant_slug: "example" } }) },
      "../features/shop": { orderStatus: value => value },
      "../components/OrderActions": { useStoresAndAccounts: () => ({ stores: [], accounts: [] }) },
      "../components/DeleteTransactionDialog": { DeleteTransactionDialog: () => null },
      "../components/Notifications": { FloatingAlert: () => null },
      "react-router-dom": { Link },
      react: { ...React, useState: initial => [
        initial && typeof initial === "object" && "shipping_provider" in initial ? { ...initial, shipping_provider: shipping } : initial,
        () => {},
      ] },
      window: { location: { origin: "https://example.test", hostname: "example.test", protocol: "https:" } },
    });
    return renderToStaticMarkup(React.createElement(CheckoutAdminPage, { setupOnly }));
  };
  const orders = render(false);
  assert.match(orders, /<h1>Online Orders<\/h1>/);
  assert.match(orders, /aria-pressed="true"[^>]*>[\s\S]*?Manage orders/);
  assert.match(orders, /COD settlements/);
  assert.match(orders, /Enquiries/);
  assert.doesNotMatch(orders, /Connect Razorpay payments|Razorpay key secret|Setup &amp; activation/);
  const setup = render(true);
  assert.match(setup, /Payments &amp; Delivery Setup/);
  assert.match(setup, /Connect Razorpay payments/);
  assert.match(setup, /href="\/portal\/checkout"/);
  assert.doesNotMatch(setup, /Loading orders|Shopper orders|aria-pressed/);
  assert.match(render(true, "staff"), /Workspace administrator access is required/);
  assert.match(render(false, "staff"), /Workspace administrator access is required/);
  const self = render(true, "owner", "self");
  assert.match(self, /No Shiprocket account is required/);
  assert.match(self, /Flat shipping charge/);
  assert.doesNotMatch(self, /Shiprocket API-user password|Shiprocket API-user email|Check Shiprocket connection/);
});

test("self-shipping dispatch sends optional manual tracking without calling a shipping provider", async () => {
  const calls = [], errors = [];
  const { OrderActions } = load("components/OrderActions.tsx", {
    react: { ...React, useState: initial => [initial, () => {}], useEffect: () => {} },
    "../features/shop": { paymentLabel: value => value, accountRequest: async (...args) => { calls.push(args); } },
    "../api": {},
  });
  const order = { id: "order", status: "confirmed", payment_method: "cod", fulfilment_method: "delivery",
    shipping_provider: "self", ship_from_store_id: "warehouse", courier: "Own courier", awb: "TRACK-1" };
  const props = { order, stores: [{ id: "warehouse", holds_stock: true, is_active: true }], accounts: [],
    locked: false, onDone: async () => {}, onError: message => errors.push(message) };
  const element = OrderActions(props);
  const find = node => {
    if (!node || typeof node !== "object") return null;
    if (node.type === "button" && node.props.children === "Dispatch & invoice") return node;
    for (const child of React.Children.toArray(node.props?.children)) {
      const found = find(child);
      if (found) return found;
    }
    return null;
  };
  const button = find(element);
  assert.ok(button);
  button.props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/orders/order/dispatch");
  assert.deepEqual(JSON.parse(calls[0][1].body), { ship_from_store_id: "warehouse", courier: "Own courier", awb: "TRACK-1" });
  assert.deepEqual(errors, []);
  const html = renderToStaticMarkup(element);
  assert.match(html, /Self-shipping \/ own courier/);
  assert.match(html, /Courier \/ delivery service \(optional\)/);
  const providerHtml = renderToStaticMarkup(OrderActions({ ...props, order: { ...order, shipping_provider: "shiprocket" } }));
  assert.doesNotMatch(providerHtml, /Courier \/ delivery service \(optional\)/);
});

test("desktop and mobile navigation share direct links and respect module/role access", () => {
  const owner = navigation.visiblePortalEntries({ role: "owner", modules: [] });
  for (const route of ["/portal/billing", "/portal/inventory", "/portal/masters/brands",
    "/portal/masters/categories", "/portal/team", "/portal/parties", "/portal/ai"]) {
    assert.ok(owner.some(entry => entry.path === route));
  }
  const staff = navigation.visiblePortalEntries({ role: "staff", modules: ["billing"] });
  assert.ok(staff.some(entry => entry.path === "/portal/billing"));
  assert.ok(!staff.some(entry => entry.path === "/portal/team" || entry.path === "/portal/parties"));
  assert.equal(owner.find(entry => entry.path === "/portal/parties").label, "Contacts");
  const { PortalNavigation, TenaliLauncher } = load("components/PortalNavigation.tsx", {
    "../features/auth": { useAuth: () => ({ user: { role: "owner" } }) },
    "../features/portalNavigation": navigation,
    "react-router-dom": { useLocation: () => ({ pathname: "/portal/inventory" }),
      NavLink: ({ to, children }) => React.createElement(Link, { to }, children) },
  });
  const desktop = renderToStaticMarkup(React.createElement(PortalNavigation));
  const mobile = renderToStaticMarkup(React.createElement(PortalNavigation, { mobile: true }));
  assert.match(desktop, /portal-sidebar/);
  assert.match(mobile, /portal-mobile-links/);
  assert.equal(desktop.match(/href=/g).length, mobile.match(/href=/g).length);
  const launcher = renderToStaticMarkup(React.createElement(TenaliLauncher));
  assert.match(launcher, /href="\/portal\/ai"/);
  assert.match(launcher, /src="\/tenali-assistant.png"/);
  const groups = [...desktop.matchAll(/<details class="portal-nav-group"( open="")?><summary>([^<]+)/g)];
  assert.deepEqual(groups.map(group => group[2]), ["Operations", "Admin", "My Workspace"]);
  assert.deepEqual(groups.filter(group => group[1]).map(group => group[2]), ["Operations"]);
  assert.deepEqual(Array.from(navigation.portalEntries.filter(entry => !entry.group), entry => entry.label), ["Dashboard", "Tenali AI"]);
});

test("AI app help links only known internal destinations; HTML and external links remain text", () => {
  const { AssistantMessage } = load("components/AssistantMessage.tsx", {
    "../features/portalNavigation": navigation,
    "react-router-dom": { Link },
  });
  const html = renderToStaticMarkup(React.createElement(AssistantMessage, {
    content: 'Open [Contacts](/portal/parties). [Bad](javascript:alert(1)) <script>x</script> [Unknown](/portal/unknown)',
  }));
  assert.match(html, /href="\/portal\/parties"/);
  assert.equal((html.match(/<a /g) || []).length, 1);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("responsive workspace shell keeps module links in the mobile menu and AI launcher off the AI page", () => {
  assert.match(source("features/auth.tsx"), /portal-shell/);
  assert.match(source("features/auth.tsx"), /!portalHome \? <aside><PortalNavigation\/><\/aside> : null/);
  assert.match(source("features/auth.tsx"), /location\.pathname !== "\/portal\/ai"/);
  assert.match(source("components/Header.tsx"), /<PortalNavigation mobile \/>/);
  assert.match(source("components/Header.tsx"), /aria-controls="header-navigation"/);
  assert.match(source("styles.css"), /\.portal-shell > aside \{ display: none; \}/);
});

test("groups without permitted entries are omitted and the active nested module opens its group", () => {
  const render = (user, pathname) => {
    const { PortalNavigation } = load("components/PortalNavigation.tsx", {
      "../features/auth": { useAuth: () => ({ user }) },
      "../features/portalNavigation": navigation,
      "react-router-dom": { useLocation: () => ({ pathname }),
        NavLink: ({ to, children }) => React.createElement(Link, { to }, children) },
    });
    return renderToStaticMarkup(React.createElement(PortalNavigation));
  };
  const restricted = render({ role: "staff", modules: ["billing"] }, "/portal/billing");
  assert.doesNotMatch(restricted, /<summary>Admin/);
  assert.match(restricted, /<details class="portal-nav-group" open=""><summary>Operations/);
  const nested = render({ role: "owner" }, "/portal/masters/categories/");
  assert.match(nested, /<details class="portal-nav-group" open=""><summary>Admin/);
  assert.doesNotMatch(nested, /open=""><summary>Operations/);
});

test("launcher label is hidden until hover or keyboard focus", () => {
  const css = source("styles.css");
  assert.match(css, /\.tenali-launcher span \{[^}]*visibility: hidden; opacity: 0/);
  assert.match(css, /\.tenali-launcher:hover span, \.tenali-launcher:focus-visible span \{ visibility: visible; opacity: 1/);
  assert.match(source("components/PortalNavigation.tsx"), /aria-label="Ask Tenali AI for help"/);
  assert.match(css, /\.tenali-launcher \{[^}]*border: 0; background: transparent/);
  assert.match(css, /\.tenali-launcher img \{[^}]*object-fit: contain/);
});

test("launcher grows from its bottom-right corner on hover and keyboard focus with reduced-motion support", () => {
  const css = source("styles.css");
  assert.match(css, /\.tenali-launcher img \{[^}]*transform-origin: bottom right;[^}]*transition: transform 450ms/);
  assert.match(css, /\.tenali-launcher:hover img, \.tenali-launcher:focus-visible img \{ transform: scale\(2\.5\); \}/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*\.tenali-launcher img \{ transition: none; \}/);
});
