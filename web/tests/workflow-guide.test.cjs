const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

const src = file => readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");

function loadGuide() {
  const compiled = ts.transpileModule(src("features/workflowGuide.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports });
  return exports.nextSteps;
}

const nextSteps = loadGuide();
const paths = guidance => guidance.steps.map(step => step.path);

test("unpaid invoice suggests recording payment; a settled one does not", () => {
  const unpaid = nextSteps({ method: "POST", path: "/billing/invoices", ok: true, data: { collection_status: "UNPAID" } });
  assert.equal(unpaid.title, "Invoice created");
  assert.ok(paths(unpaid).includes("/portal/receivables"));
  assert.ok(paths(unpaid).includes("/portal/inventory?view=alerts"));
  const paid = nextSteps({ method: "POST", path: "/billing/invoices", ok: true, data: { collection_status: "SETTLED" } });
  assert.ok(!paths(paid).includes("/portal/receivables"));
});

test("cancellation with reversed payments points to refund settlement first", () => {
  const withRefund = nextSteps({ method: "POST", path: "/billing/invoices/abc-1/cancel", ok: true, data: { status: "CANCELLED", refunds: [{ id: "r1", amount: 10 }] } });
  assert.equal(withRefund.steps[0].path, "/portal/settlements/refunds");
  assert.match(withRefund.steps[0].label, /1 pending refund:/);
  assert.match(withRefund.note, /credit note/);
  const noRefund = nextSteps({ method: "POST", path: "/purchases/p1/cancel", ok: true, data: { status: "CANCELLED", refunds: [] } });
  assert.ok(!paths(noRefund).includes("/portal/settlements/refunds"));
});

test("purchase guidance follows receipt and payment state", () => {
  const pending = nextSteps({ method: "POST", path: "/purchases", ok: true, data: { receipt_status: "PENDING", payment_status: "UNPAID" } });
  assert.match(pending.steps[0].label, /Confirm receipt/);
  assert.ok(pending.steps.some(step => /Pay the vendor/.test(step.label)));
  const done = nextSteps({ method: "POST", path: "/purchases", ok: true, data: { receipt_status: "RECEIVED", payment_status: "PAID" } });
  assert.ok(!done.steps.some(step => /Pay the vendor|Confirm receipt/.test(step.label)));
});

test("period lock, reopen and closed-period failure lead through the close cycle", () => {
  const locked = nextSteps({ method: "POST", path: "/accounts/period-locks", ok: true, data: {} });
  assert.equal(locked.title, "Period closed");
  const reopened = nextSteps({ method: "POST", path: "/accounts/period-locks/l1/reopen", ok: true, data: {} });
  assert.equal(reopened.steps.at(-1).path, "/portal/accounts#period-locks");
  const blocked = nextSteps({ method: "POST", path: "/billing/invoices", ok: false, status: 422, message: "Posting invoice is blocked. Period 2025-04-01 to 2025-04-30 is closed." });
  assert.equal(blocked.title, "This date is in a closed period");
  assert.match(blocked.note, /2025-04-01 to 2025-04-30/);
  assert.ok(paths(blocked).includes("/portal/accounts#period-locks"));
});

test("failure guidance covers module access and stock; unknown results stay silent", () => {
  assert.equal(nextSteps({ method: "POST", path: "/x", ok: false, message: "Your role does not include the purchases module" }).steps[0].path, "/portal/team");
  assert.equal(nextSteps({ method: "POST", path: "/inventory/products/p/stock", ok: false, message: "Stock at MAIN cannot become negative (available 2)" }).title, "Not enough stock");
  assert.equal(nextSteps({ method: "POST", path: "/x", ok: false, message: "Something else" }), null);
  assert.equal(nextSteps({ method: "PUT", path: "/company", ok: true, data: {} }), null);
  assert.equal(nextSteps({ method: "GET", path: "/billing/invoices", ok: true, data: {} }), null);
  assert.equal(nextSteps({ method: "POST", path: "/billing/invoices/reconcile", ok: true, data: {} }), null);
  assert.equal(nextSteps({ method: "POST", path: "/accounts/transactions?x=1", ok: true, data: {} }).title, "Transaction posted");
});

test("api announces write results, the guide honours the company toggle, and settings expose it", () => {
  const api = src("api.ts");
  assert.match(api, /announce\(\{ method, path, ok: false/);
  assert.match(api, /announce\(\{ method, path, ok: true/);
  assert.match(api, /if \(result\.method === "GET"/);
  const guide = src("components/WorkflowGuide.tsx");
  assert.match(guide, /workflow_guidance_enabled !== false/);
  assert.match(guide, /if \(!enabled\.current\) return;/);
  assert.match(guide, /tone: "workflow"/);
  assert.match(src("features/auth.tsx"), /<WorkflowGuide\/><Outlet\/>/);
  const setup = src("pages/CompanySetupPage.tsx");
  assert.match(setup, /workflow_guidance_enabled: company\.workflow_guidance_enabled !== false/);
  assert.match(setup, /id="portal-settings"/);
});

test("single-person workflow includes stock, refunds and the period lock cycle", () => {
  const portal = src("pages/PortalPage.tsx");
  for (const id of ["eom-lock", "eom-reopen", "eom-stock", "eom-refunds", "eom-gst", "eoy-months", "eoy-lock", "start-refunds", "work-receipt", "eod-cash"]) {
    assert.match(portal, new RegExp(`id: "${id}"`));
  }
  assert.match(portal, /path: "\/portal\/accounts#period-locks"/);
  assert.match(portal, /adminMaintenanceLinks\.some\(item => item\.path === base\)/);
  assert.match(src("pages/AccountsPage.tsx"), /id="period-locks"/);
  assert.match(src("pages/InventoryPage.tsx"), /view==='alerts'\|\|view==='check'/);
});
