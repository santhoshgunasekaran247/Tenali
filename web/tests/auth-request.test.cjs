const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function load(tenantFetch) {
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "auth.tsx"), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const mocks = {
    react: { createContext: () => ({}) },
    "./tenantTransport": { tenantFetch },
  };
  vm.runInNewContext(code, { exports, SyntaxError, Error, require: name => mocks[name] || {} });
  return exports.authRequest;
}

test("auth requests retain successful responses and backend error details", async () => {
  const calls = [];
  const request = load(async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ user: "sample" }), { status: 200 });
  });
  assert.equal((await request("/login", { method: "POST" })).user, "sample");
  assert.equal(calls[0].url, "/api/auth/login");
  assert.equal(calls[0].options.method, "POST");
  const invalid = load(async () => new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 }));
  await assert.rejects(invalid("/login"), { message: "Invalid credentials" });
  const validation = load(async () => new Response(JSON.stringify({ detail: [{ msg: "Value error, Invalid workspace" }] }), { status: 422 }));
  await assert.rejects(validation("/login"), { message: "Invalid workspace" });
});

test("empty or malformed responses surface a useful authentication error", async () => {
  const unavailable = load(async () => new Response("", { status: 500 }));
  await assert.rejects(unavailable("/login"), { message: "The authentication request failed (HTTP 500). The server returned an invalid response. Please try again." });
  const malformed = load(async () => new Response("<html>", { status: 502 }));
  await assert.rejects(malformed("/login"), /HTTP 502/);
  const brokenSuccess = load(async () => new Response("", { status: 200 }));
  await assert.rejects(brokenSuccess("/login"), /authentication service returned an invalid response/);
});

test("transport failures are not disguised as JSON errors", async () => {
  const failure = new Error("Network unavailable");
  const request = load(async () => { throw failure; });
  await assert.rejects(request("/login"), error => error === failure);
});
