const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

test("editing a store never submits immutable invoice IDs or other server-owned fields", () => {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "pages", "StoresPage.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const mocks = { "../api": {}, "../features/drafts": {}, "../components/Notifications": {} };
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || require(name) });
  const payload = exports.storeInput({
    id: "store", company_id: "company", invoice_code: "01", holds_stock: true, is_default: true,
    code: "MAIN", name: "Main", kind: "offline", fulfilment_store_id: null, allows_pickup: false,
    address: "Chennai", state_code: "33", pincode: "600001", latitude: null, longitude: null,
    gst_number: null, whatsapp_number: null, settlement_account_id: null, is_active: true,
  });
  for (const key of ["id", "company_id", "invoice_code", "holds_stock", "is_default"]) assert.ok(!(key in payload));
  assert.equal(payload.code, "MAIN");
  assert.equal(payload.address, "Chennai");
  assert.equal(Object.keys(payload).length, 14);
});
