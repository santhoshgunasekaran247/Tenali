const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const { renderToStaticMarkup } = require("react-dom/server");
const React = require("react");

function load(relative, overrides = {}) {
  const source = readFileSync(path.join(__dirname, "..", "src", relative), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, require: name => overrides[name] || require(name), ...overrides.globals,
  });
  return exports;
}

test("policy URLs distinguish platform from store and preserve all required policy kinds", () => {
  const policies = load("features/policies.ts", { "./tenantTransport": {} });
  assert.equal(policies.policyPath("platform", "privacy"), "/policies/platform/privacy");
  assert.equal(policies.policyPath("tenant", "returns"), "/policies/tenant/returns");
  assert.equal(policies.policyAdminPath("tenant"), "/company/policies");
  assert.equal(policies.policyAdminPath("platform"), "/platform/policies");
  assert.equal(policies.TENANT_POLICY_KINDS.length, 7);
  assert.equal(policies.PLATFORM_POLICY_KINDS.length, 4);
});

test("policy rendering treats tenant text as text, never active HTML", () => {
  const { PolicyDocument } = load("components/PolicyDocument.tsx");
  const markup = renderToStaticMarkup(React.createElement(PolicyDocument, {
    content: {
      title: "<script>alert(1)</script>", business_name: "Store & Co", address: "Chennai",
      contact_email: "help@example.com", jurisdiction: "Chennai", currency: "INR",
      body: '<img src=x onerror="alert(1)">\nSHIPPING\n3 business days',
    },
  }));
  assert.ok(!markup.includes("<script>"));
  assert.ok(!markup.includes("<img "));
  assert.ok(markup.includes("&lt;script&gt;"));
  assert.ok(markup.includes("3 business days"));
  assert.ok(markup.includes("help@example.com"));
});

test("platform editor uses platform CSRF and clears tenant routing; errors stay explicit", async () => {
  const calls = [];
  const policies = load("features/policies.ts", {
    "./tenantTransport": { tenantFetch: async (url, options) => {
      calls.push({ url, options });
      return { ok: false, json: async () => ({ detail: "Policy changed. Reload the latest draft before saving." }) };
    } },
    globals: { document: { cookie: "tenali_csrf=tenant-token; tenali_platform_csrf=platform-token" } },
  });
  await assert.rejects(() => policies.policyRequest("/platform/policies/privacy", { method: "PUT" }), /Policy changed/);
  assert.equal(calls[0].url, "/api/platform/policies/privacy");
  assert.equal(calls[0].options.headers["X-CSRF-Token"], "platform-token");
  assert.equal(calls[0].options.headers["X-Tenant-Slug"], "");
  await assert.rejects(() => policies.policyRequest("/company/policies/privacy", { method: "PUT" }), /Policy changed/);
  assert.equal(calls[1].options.headers["X-CSRF-Token"], "tenant-token");
});
