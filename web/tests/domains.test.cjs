const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const source = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
function compile(file, context) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source(file), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, ...context });
  return exports;
}

test("domain portal shows automatic hosting, DNS instructions and truthful pending states", () => {
  const data = {
    items: [{ id: "domain", hostname: "sourcedbysru.in", verified_at: "2026-01-01",
      hosting_status: "tls_pending", hosting_error: "Waiting for certificate",
      dns_records: [{ type: "CNAME", name: "api.sourcedbysru.in", value: "tenali-api.onrender.com" }] }],
    automatic_hosting: true,
  };
  const page = compile("pages/DomainsPage.tsx", { location: { origin: "https://tenali.biz" }, require: name =>
    name === "react" ? { ...React, useState: initial => [initial && typeof initial === "object" && "items" in initial ? data : initial, () => {}] } :
    name === "../features/auth" ? { useAuth: () => ({ user: { role: "owner", tenant_slug: "sourcebysru", company_id: "company" } }) } :
    name === "../features/drafts" ? { useDraftState: () => ["", () => {}] } :
    name === "../components/Notifications" ? { FloatingAlert: () => null } :
    name === "../components/PortalHomeLink" ? { PortalHomeLink: () => null } : require(name),
  });
  const html = renderToStaticMarkup(React.createElement(page.DomainsPage));
  assert.match(html, /No Render account is needed/);
  assert.match(html, /Waiting for DNS \/ HTTPS/);
  assert.match(html, /api.sourcedbysru.in/);
  assert.match(html, /tenali-api.onrender.com/);
  assert.match(html, /GoDaddy/);
  assert.match(html, /Verify &amp; connect/);
  assert.doesNotMatch(html, /Open storefront/);
  assert.match(source("pages/DomainsPage.tsx"), /setInterval/);
});

test("custom-domain social login uses the central callback and a one-time API relay, not third-party cookies or opener", async () => {
  let interval;
  const popup = { location: {}, close() {} };
  const calls = [];
  const config = { enabled: true, providers: ["google"], callbackOrigin: "https://tenali.biz" };
  const module = compile("features/shopperFederation.ts", {
    URL, URLSearchParams, Date, clearTimeout() {}, crypto: { randomUUID: () => "nonce-fixture" },
    BroadcastChannel: class { close() {} },
    window: {
      location: { origin: "https://sourcedbysru.in" }, open: () => popup,
      setTimeout: () => 1, setInterval: callback => { interval = callback; return 2; }, clearInterval() {},
    },
    require: name => {
      assert.equal(name, "./tenantTransport");
      return { tenantApiOrigin: () => "https://api.sourcedbysru.in", tenantFetch: async (url, options) => {
        calls.push({ url, options });
        return new Response(JSON.stringify(url.endsWith("/poll")
          ? { pending: false, result: { accessToken: "fixture-access", email: "fixture@example.com", expiresAt: 9999999999 } }
          : { id: "relay-fixture", key: "secret-fixture" }));
      } };
    },
  });
  const login = module.socialLogin(config, "google");
  await new Promise(setImmediate);
  const url = new URL(popup.location.href);
  assert.equal(url.origin, "https://tenali.biz");
  assert.equal(url.searchParams.get("return_origin"), "https://sourcedbysru.in");
  assert.ok(!url.search.includes("secret-fixture"));
  assert.equal(new URLSearchParams(url.hash.slice(1)).get("relay_key"), "secret-fixture");
  interval();
  const user = await login;
  assert.equal(await user.getIdToken(), "fixture-access");
  assert.equal(calls[1].url, "/api/auth/social-relays/relay-fixture/poll");
  assert.deepEqual(JSON.parse(calls[1].options.body), { key: "secret-fixture" });
});
