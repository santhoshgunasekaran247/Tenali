const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function transport(hostname = "sourcedbysru.in", enabled = true) {
  const calls = [];
  const exports = {};
  const responses = [];
  const code = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "features", "tenantTransport.ts"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(code, {
    exports, URL, Request, Headers, Map,
    __TENALI_CUSTOM_DOMAINS__: enabled,
    __TENALI_PLATFORM_HOSTS__: ["tenali.biz", "tenali-web.onrender.com"],
    window: { location: { hostname, protocol: "https:", origin: `https://${hostname}`, pathname: "/" } },
    document: { cookie: "tenali_csrf=frontend-cookie-must-not-leak" },
    fetch: async (input, options) => {
      calls.push({ input, options });
      return responses.shift() || new Response("{}");
    },
  });
  return { ...exports, calls, responses };
}

test("custom domains use their paired API with credentialed requests and realm-specific CSRF", async () => {
  const api = transport();
  api.responses.push(new Response("{}", { headers: {
    "X-Tenali-Staff-CSRF": "staff-token", "X-Tenali-Shopper-CSRF": "shop-token",
  } }));
  await api.tenantFetch("/api/auth/session");
  assert.equal(api.calls[0].input, "https://api.sourcedbysru.in/api/auth/session");
  assert.equal(api.calls[0].options.credentials, "include");
  assert.equal(api.calls[0].options.headers.get("X-CSRF-Token"), null);
  await api.tenantFetch("/api/shop/orders", { method: "POST", headers: { "X-CSRF-Token": "", "Content-Type": "application/json" } });
  assert.equal(api.calls[1].options.headers.get("X-CSRF-Token"), "shop-token");
  await api.tenantFetch("/api/products", { method: "POST" });
  assert.equal(api.calls[2].options.headers.get("X-CSRF-Token"), "staff-token");
});

test("platform, original Render frontend and feature-disabled deployments stay same-origin", async () => {
  for (const [host, enabled] of [["tenali.biz", true], ["tenali-web.onrender.com", true], ["sourcedbysru.in", false]]) {
    const api = transport(host, enabled);
    await api.tenantFetch("/api/auth/session");
    assert.equal(api.calls[0].input, "/api/auth/session");
    assert.equal(api.calls[0].options.credentials, "same-origin");
  }
});

test("Request/URL inputs and Headers preserve body, method and headers", async () => {
  const api = transport();
  const input = new Request("https://sourcedbysru.in/api/products", {
    method: "POST", body: '{"name":"test"}', headers: { "X-Original": "yes" },
  });
  await api.tenantFetch(input, { headers: new Headers({ "X-Extra": "yes" }) });
  assert.equal(api.calls[0].input.url, "https://api.sourcedbysru.in/api/products");
  assert.equal(api.calls[0].input.method, "POST");
  assert.equal(await api.calls[0].input.text(), '{"name":"test"}');
  assert.equal(api.calls[0].options.headers.get("X-Original"), "yes");
  assert.equal(api.calls[0].options.headers.get("X-Extra"), "yes");
  await api.tenantFetch(new URL("https://sourcedbysru.in/api/catalog/list?q=a"));
  assert.equal(api.calls[1].input, "https://api.sourcedbysru.in/api/catalog/list?q=a");
});

test("external URLs are never rewritten to a tenant API", async () => {
  const api = transport();
  await api.tenantFetch("https://example.net/public");
  assert.equal(api.calls[0].input, "https://example.net/public");
  assert.equal(api.calls[0].options.credentials, "same-origin");
});
