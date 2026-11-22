const assert = require("node:assert/strict");
const { readFileSync, statSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const read = file => readFileSync(path.join(root, "src", file), "utf8");

function renderRoot(auth, base = "", customApi = "") {
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  const mocks = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: { createContext: () => ({}), useContext: () => auth },
    "react-router-dom": { Navigate: "Navigate" },
    "./tenantTransport": { tenantBase: () => base, tenantApiOrigin: () => customApi },
    "../pages/PlatformHomePage": { PlatformHomePage: "PlatformHomePage" },
  };
  const code = ts.transpileModule(read("features/auth.tsx"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, require: name => mocks[name] || {} });
  return exports.StorefrontRoot({ children: "storefront" });
}

test("platform home is public for visitors and signed-in users", () => {
  for (const user of [null, { tenant_slug: "acme" }]) {
    assert.equal(renderRoot({ loading: false, storefront: null, user }).type, "PlatformHomePage");
  }
});

test("tenant storefronts and tenant redirects remain intact", () => {
  assert.equal(renderRoot({ loading: false, storefront: { id: "c" }, user: null }, "/c/acme").props.children, "storefront");
  const missing = renderRoot({ loading: false, storefront: null, user: { tenant_slug: "acme" } }, "/c/acme");
  assert.equal(missing.type, "Navigate");
  assert.equal(missing.props.to, "/portal");
  const custom = renderRoot({ loading: false, storefront: null, user: { tenant_slug: "acme" } }, "", "https://api.store.test");
  assert.notEqual(custom.type, "PlatformHomePage");
});

test("marketing page has real routes, an accessible demo and a local video", () => {
  const page = read("pages/PlatformHomePage.tsx");
  for (const section of ["what-we-do", "how-it-works", "demo", "about", "contact"]) assert.match(page, new RegExp(`id="${section}"`));
  assert.match(page, /to="\/register"/);
  assert.match(page, /to="\/login"/);
  assert.match(page, /policyPath\("platform", "contact"\)/);
  assert.match(page, /policyRequest<PublicPolicy>\("\/legal\/platform\/contact"\)/);
  assert.match(page, /<video controls preload="metadata" playsInline/);
  assert.match(page, /id="demo-transcript"/);
  assert.ok(statSync(path.join(root, "public", "tenali-product-tour.webm")).size > 10000);
});
