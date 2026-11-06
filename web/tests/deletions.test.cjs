const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function load(file) {
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "features", file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require, Number });
  return exports;
}

const deletions = load("deletions.ts");
const { reissueInvoice, cancellationStamp } = load("invoiceReissue.ts");

test("cancelled invoices get a PDF stamp with date and reason; active ones do not", () => {
  assert.equal(cancellationStamp({ status: "ISSUED", cancelled_at: null, cancellation_reason: null }), null);
  const stamp = cancellationStamp({ status: "CANCELLED", cancelled_at: "2026-11-06", cancellation_reason: "Wrong customer" });
  assert.equal(stamp.watermark, "CANCELLED");
  assert.match(stamp.detail, /^Cancelled on 06 Nov 2026 - Wrong customer$/);
  assert.equal(cancellationStamp({ status: "CANCELLED", cancelled_at: null, cancellation_reason: "x".repeat(200) }).detail.length, "Cancelled - ".length + 90);
});

const cancellation = load("cancellation.ts");

test("deletion wording is generic delete for every kind", () => {
  assert.equal(deletions.deletionWording("purchase").submit, "Delete permanently");
  assert.equal(deletions.deletionWording("invoice").submit, "Delete permanently");
});

test("cancelling a paid document explains reversal and refund settlement; unpaid does not", () => {
  const unpaid = cancellation.cancellationEffects("invoice", 0);
  assert.equal(unpaid.length, 1);
  assert.match(unpaid[0], /CANCELLED/);
  const paid = cancellation.cancellationEffects("invoice", 1500);
  assert.equal(paid.length, 3);
  assert.match(paid[1], /reversed \(nothing is deleted\).*pay back to the customer/);
  assert.match(cancellation.cancellationEffects("purchase", 10)[1], /vendor must return/);
  assert.equal(cancellation.refundDirectionLabel("PAY_CUSTOMER"), "Pay back to customer");
  assert.equal(cancellation.refundDirectionLabel("RECEIVE_VENDOR"), "Receive back from vendor");
});

test("cancel needs a reason, refund acknowledgement when paid, and the document number typed back", () => {
  const base = { reason: "Wrong customer", paid: 0, acknowledged: false, typed: "INV20261106001", number: "INV20261106001" };
  assert.equal(cancellation.canConfirmCancel(base), true);
  assert.equal(cancellation.canConfirmCancel({ ...base, reason: "  " }), false);
  assert.equal(cancellation.canConfirmCancel({ ...base, typed: "INV2026" }), false);
  assert.equal(cancellation.canConfirmCancel({ ...base, paid: 100 }), false);
  assert.equal(cancellation.canConfirmCancel({ ...base, paid: 100, acknowledged: true }), true);
});

const preview = (overrides = {}) => ({
  kind: "purchase", record_id: "p1", label: "Purchase B-1", cascade: false, can_delete: true, confirm_text: "DELETE B-1", token: "t",
  blockers: [], critical: [], warnings: [], deletes: [{ title: "Purchases", count: 1, items: [] }, { title: "Stock movements", count: 2, items: [] }],
  stock_changes: [], account_changes: [], ...overrides,
});

test("only owners and admins may delete transactions", () => {
  assert.equal(deletions.canDeleteTransactions("owner"), true);
  assert.equal(deletions.canDeleteTransactions("admin"), true);
  assert.equal(deletions.canDeleteTransactions("staff"), false);
  assert.equal(deletions.canDeleteTransactions(undefined), false);
});

test("review step blocks until blockers are cleared, critical children are included and the user acknowledges", () => {
  assert.equal(deletions.reviewState(preview({ blockers: ["Stock already sold"] }), true).ready, false);
  const critical = preview({ critical: [{ title: "Payments", count: 1 }] });
  assert.match(deletions.reviewState(critical, true).reason, /everything together/);
  assert.equal(deletions.reviewState({ ...critical, cascade: true }, true).ready, true);
  assert.equal(deletions.reviewState(preview(), false).ready, false);
  assert.equal(deletions.reviewState(preview(), true).ready, true);
  assert.equal(deletions.reviewState(preview({ can_delete: false }), true).ready, false);
});

test("typed confirmation must match exactly and totals count every record", () => {
  assert.equal(deletions.confirmationMatches(preview(), "  DELETE B-1 "), true);
  assert.equal(deletions.confirmationMatches(preview(), "delete b-1"), false);
  assert.equal(deletions.deletionTotal(preview()), 3);
  assert.equal(deletions.signed(3), "+3");
  assert.equal(deletions.signed(-2), "-2");
});

test("reissue copies a cancelled invoice into a new draft", () => {
  const invoice = {
    invoice_number: "INV20250101001", customer_party_id: "c1",
    document_data: {
      place_of_supply: "33", bill_to: { name: "Asha", address: "1 Main St" }, ship_to: { name: "Ravi", address: "2 Side St" },
      lines: [{ product_id: "p1", variant_id: null, description: "Kettle", hsn: "8516", quantity: "2", rate: "500", gst_rate: "18", price_includes_gst: true }],
    },
  };
  const result = reissueInvoice(invoice);
  assert.equal(result.sameShipping, false);
  assert.equal(result.form.shipping_name, "Ravi");
  assert.equal(result.form.place_of_supply, "33");
  assert.match(result.form.notes, /INV20250101001/);
  assert.deepEqual(JSON.parse(JSON.stringify(result.lines)), [{ product_id: "p1", variant_id: null, description: "Kettle", hsn: "8516", quantity: 2, rate: 500, gst_rate: 18, price_includes_gst: true }]);
  const same = reissueInvoice({ ...invoice, document_data: { ...invoice.document_data, ship_to: { name: "Asha", address: "1 Main St" } } });
  assert.equal(same.sameShipping, true);
  assert.equal(same.form.shipping_address, "");
});
