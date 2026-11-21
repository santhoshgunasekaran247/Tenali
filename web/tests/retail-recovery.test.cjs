const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function source(file) {
  return readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
}

function load(file, overrides = {}) {
  const exports = {};
  const compiled = ts.transpileModule(source(file), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(compiled, { exports, require: name => overrides[name] || require(name), Intl });
  return exports;
}

test("checklist scopes follow India midnight and April-March financial years", () => {
  const { indiaDateKey, workflowScope } = load("features/workflowDates.ts");
  assert.equal(indiaDateKey(new Date("2026-03-31T18:29:59Z")), "2026-03-31");
  assert.equal(indiaDateKey(new Date("2026-03-31T18:30:00Z")), "2026-04-01");
  assert.equal(indiaDateKey(new Date("2025-12-31T18:30:00Z")), "2026-01-01");
  assert.equal(workflowScope("start", "2026-04-01"), "2026-04-01");
  assert.equal(workflowScope("eom", "2026-04-01"), "2026-04");
  assert.equal(workflowScope("eoy", "2026-01-01"), "fy-2025");
  assert.equal(workflowScope("eoy", "2026-03-31"), "fy-2025");
  assert.equal(workflowScope("eoy", "2026-04-01"), "fy-2026");
  assert.match(source("pages/PortalPage.tsx"), /window\.setInterval\(refresh/);
  assert.match(source("pages/PortalPage.tsx"), /not a shared or audited close record/);
});

test("payment verification is limited to prepaid orders awaiting payment or expired", () => {
  const { canVerifyPayment } = load("features/shop.ts", { "./tenantTransport": {} });
  const order = { status: "expired", payment_method: "prepaid", razorpay_order_id: "order_123", razorpay_payment_id: null };
  assert.equal(canVerifyPayment(order), true);
  assert.equal(canVerifyPayment({ ...order, status: "awaiting_payment" }), true);
  assert.equal(canVerifyPayment({ ...order, status: "cancelled" }), true);
  assert.equal(canVerifyPayment({ ...order, status: "cancelled", razorpay_payment_id: "pay_123" }), false);
  assert.equal(canVerifyPayment({ ...order, status: "paid" }), false);
  assert.equal(canVerifyPayment({ ...order, payment_method: "cod" }), false);
  assert.equal(canVerifyPayment({ ...order, payment_method: "pay_at_pickup" }), false);
  assert.equal(canVerifyPayment({ ...order, razorpay_order_id: null }), false);
  for (const page of ["pages/ShopperAccountPage.tsx", "pages/CheckoutAdminPage.tsx"]) {
    assert.match(source(page), /canVerifyPayment\(order\)/);
    assert.match(source(page), /reconcile-payment/);
  }
});
