const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

test("history client uses tenant transport and encodes filters and failures", async () => {
  const calls = [];
  let ok = true;
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "historyClient.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, URLSearchParams, Error,
    require: name => name === "./tenantTransport" ? { tenantFetch: async url => {
      calls.push(url);
      return { ok, status: 403, json: async () => ({ items: [], next_cursor: null }),
        text: async () => '{"detail":"Forbidden"}', blob: async () => "csv" };
    } } : require(name) });
  const client = exports.historyClient;
  await client.audit({ from_date: "2026-01-01", page_size: 10, cursor: "a+b", to_date: "" });
  let url = new URL(calls[0], "https://example.test");
  assert.equal(url.pathname, "/api/reports/audit-events");
  assert.equal(url.searchParams.get("cursor"), "a+b");
  assert.equal(url.searchParams.has("to_date"), false);
  await client.invoices({ from_date: "2026-01-01", page_size: 25 });
  await client.quotations({ to_date: "2026-01-31", page_size: 25 });
  assert.match(calls[1], /\/billing\/invoices\?/);
  assert.match(calls[2], /\/billing\/quotations\?/);
  assert.equal(await client.reconcileCsv(), "csv");
  assert.equal(await client.salesRegisterCsv({ all_time: true, store_id: "abc", collection_status: "PARTIAL" }), "csv");
  url = new URL(calls[4], "https://example.test");
  assert.equal(url.searchParams.get("all_time"), "true");
  assert.equal(url.searchParams.get("store_id"), "abc");
  ok = false;
  await assert.rejects(client.audit({ page_size: 10 }), /Forbidden/);
  await assert.rejects(client.reconcileCsv(), /Forbidden/);
});
