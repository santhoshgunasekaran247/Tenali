const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function loadGate(auth) {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "StorefrontGate.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const Fragment = Symbol("Fragment");
  const element = (type, props) => ({ type, props });
  const exports = {};
  const mocks = {
    "react/jsx-runtime": { jsx: element, jsxs: element, Fragment },
    "react-router-dom": { Link: "Link" },
    "../features/auth": { useAuth: () => auth },
  };
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || require(name) });
  return exports.StorefrontGate;
}

function text(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  return text(node.props && node.props.children);
}

function links(node, found = []) {
  if (Array.isArray(node)) node.forEach(child => links(child, found));
  else if (node && typeof node === "object") {
    if (node.type === "Link") found.push(node.props.to);
    links(node.props && node.props.children, found);
  }
  return found;
}

const store = { id: "company-a", company_name: "Acme Traders", nickname: "Acme", phone: "+919876543210", email: "hello@acme.test" };
const page = { type: "Page", props: {} };

test("an open storefront renders its page unchanged", () => {
  for (const storefront of [{ ...store }, { ...store, storefront_enabled: true }, null]) {
    const rendered = loadGate({ loading: false, user: null, storefront })({ children: page });
    assert.equal(rendered.props.children, page);
  }
});

test("a disabled storefront hides the page and shows contact and order tracking", () => {
  const rendered = loadGate({ loading: false, user: null, storefront: { ...store, storefront_enabled: false } })({ children: page });
  assert.notEqual(rendered.props.children, page);
  const copy = text(rendered);
  assert.match(copy, /currently unavailable/);
  assert.match(copy, /\+919876543210/);
  assert.match(copy, /hello@acme\.test/);
  assert.deepEqual(links(rendered), ["/account"]);
});

test("the workspace team gets a link to turn the storefront back on", () => {
  const rendered = loadGate({ loading: false, user: { company_id: "company-a" }, storefront: { ...store, storefront_enabled: false } })({ children: page });
  assert.deepEqual(links(rendered), ["/account", "/portal/company#storefront-visibility"]);
  const otherWorkspace = loadGate({ loading: false, user: { company_id: "company-b" }, storefront: { ...store, storefront_enabled: false } })({ children: page });
  assert.deepEqual(links(otherWorkspace), ["/account"]);
});

test("company setup saves the storefront switch and storefront routes are gated", () => {
  const setup = readFileSync(path.join(__dirname, "..", "src", "pages", "CompanySetupPage.tsx"), "utf8");
  assert.match(setup, /storefront_enabled: company\.storefront_enabled !== false/);
  assert.match(setup, /id="storefront-visibility"/);
  const app = readFileSync(path.join(__dirname, "..", "src", "App.tsx"), "utf8");
  for (const page of ["HomePage", "CheckoutPage", "CartPage", "ProductPage"]) {
    assert.match(app, new RegExp(`<StorefrontGate><${page} /></StorefrontGate>`));
  }
  assert.equal((app.match(/<StorefrontGate><BrandPage \/><\/StorefrontGate>/g) || []).length, 2);
  assert.match(app, /path="\/account" element={<ShopperAccountPage \/>}/);
});
