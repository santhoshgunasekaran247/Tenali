const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const testWindow = { confirm: () => true };
function harness(overrides = {}, request = async () => ({}), refresh = async () => {}) {
  const states = [], errors = [], messages = [], requests = [];
  let cursor = 0;
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "OrderActions.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const mocks = {
    react: { ...React, useEffect: () => {}, useState: initial => {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = value; }];
    } },
    "react-router-dom": { Link: ({ to, children, ...rest }) => React.createElement("a", { href: to, ...rest }, children) },
    "../api": {},
    "../features/shop": { paymentLabel: () => "Paid online", rupees: value => `INR ${value / 100}`, accountRequest: async (...args) => {
      requests.push(args); return request(...args);
    } },
  };
  vm.runInNewContext(compiled, { exports, window: testWindow, require: name => mocks[name] || require(name) });
  const order = { id: "order", store_id: "online", payment_method: "prepaid", status: "paid",
    fulfilment_method: "delivery", shipping_provider: "self", razorpay_payment_id: "pay_captured", total_paise: 12500,
    advance_transaction_id: null, ship_from_store_id: "warehouse", invoice_id: null,
    review_reason: "Advance not posted: set a settlement account", ...overrides };
  return {
    requests, errors, messages, exports,
    render(locked = false) {
      cursor = 0;
      return exports.OrderActions({ order, stores: [
        { id: "online", fulfilment_store_id: "warehouse" },
        { id: "warehouse", code: "WH", name: "Warehouse", holds_stock: true, is_active: true },
      ], accounts: [{ id: "clearing", nickname: "Razorpay clearing" }], locked,
      onError: message => errors.push(message),
      onDone: async message => { messages.push(message); await refresh(message); } });
    },
  };
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}
const button = (tree, text) => find(tree, node => node.type === "button" && node.props.children === text);
const flush = () => new Promise(resolve => setImmediate(resolve));

test("pending advances have a separate setup panel and explain blocked dispatch", () => {
  const tree = harness().render();
  const html = renderToStaticMarkup(tree);
  assert.match(html, /Record payment advance/);
  assert.match(html, /href="\/portal\/stores"/);
  assert.match(html, /does not charge the shopper again/);
  assert.match(html, /Post the verified payment advance above to enable dispatch/);
  assert.equal(button(tree, "Dispatch & invoice").props.disabled, true);
  assert.equal(button(tree, "Retry posting payment advance").props.disabled, false);
  assert.match(html, /<label[^>]*>Cancellation reason<input/);
  assert.doesNotMatch(html, /<label>Refund from<select/);
  assert.match(html, /before recording a refund and cancelling/);
});

test("posted advances enable dispatch and remove the retry panel", () => {
  const tree = harness({ advance_transaction_id: "advance", review_reason: null }).render();
  assert.equal(button(tree, "Dispatch & invoice").props.disabled, false);
  assert.equal(button(tree, "Retry posting payment advance"), undefined);
  assert.doesNotMatch(renderToStaticMarkup(tree), /Post the verified payment/);
});

test("captured refund requires account, provider reference and explicit confirmation", async () => {
  const h = harness({ advance_transaction_id: "advance", review_reason: null });
  let tree = h.render();
  assert.match(renderToStaticMarkup(tree), /does not initiate a refund/);
  const labelled = (node, text) => find(node, item => item.type === "label" && React.Children.toArray(item.props.children)[0] === text);
  const control = (label, type) => find(label, item => item.type === type);
  control(labelled(tree, "Cancellation reason"), "input").props.onChange({ target: { value: "Out of stock" } });
  tree = h.render();
  assert.equal(button(tree, "Confirm cancellation").props.disabled, true);
  control(labelled(tree, "Refund from"), "select").props.onChange({ target: { value: "clearing" } });
  tree = h.render();
  control(labelled(tree, "Razorpay refund ID"), "input").props.onChange({ target: { value: "rfnd_123" } });
  tree = h.render();
  assert.equal(button(tree, "Confirm cancellation").props.disabled, true);
  find(tree, node => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } });
  tree = h.render();
  assert.equal(button(tree, "Confirm cancellation").props.disabled, false);
  button(tree, "Confirm cancellation").props.onClick();
  await flush();
  assert.deepEqual(JSON.parse(h.requests[0][1].body), { reason: "Out of stock", refund_account_id: "clearing",
    refund_confirmed: true, refund_reference: "rfnd_123" });
});

test("advance retry failures show the server reason without a success notification", async () => {
  const h = harness({}, async () => { throw new Error("Advance not posted: set a settlement account"); });
  button(h.render(), "Retry posting payment advance").props.onClick();
  await flush();
  assert.match(h.errors.at(-1), /set a settlement account/);
  assert.deepEqual(h.messages, [""]);
  assert.equal(h.requests[0][0], "/orders/order/post-advance");
  assert.equal(h.requests[0][2], "checkout-admin");
  assert.equal(button(h.render(), "Retry posting payment advance").props.disabled, false);
});

test("successful advance retry refreshes the order and locked actions cannot be submitted", async () => {
  const h = harness();
  assert.equal(button(h.render(true), "Retry posting payment advance").props.disabled, true);
  button(h.render(), "Retry posting payment advance").props.onClick();
  assert.equal(button(h.render(), "Retry posting payment advance").props.disabled, true);
  await flush();
  assert.deepEqual(h.messages, ["Online payment advance posted."]);
});

test("cancelled orders do not offer advance retry and COD does not require prepaid posting", () => {
  assert.equal(button(harness({ status: "cancelled" }).render(), "Retry posting payment advance"), undefined);
  const tree = harness({ payment_method: "cod", status: "confirmed", razorpay_payment_id: null }).render();
  assert.equal(button(tree, "Dispatch & invoice").props.disabled, false);
  assert.equal(button(tree, "Retry posting payment advance"), undefined);
});

const shiprocket = { shipping_provider: "shiprocket", advance_transaction_id: "advance", review_reason: null, provider_key_id: "rzp_live_x" };
const panel = (order, pkg = { weight: "", length: "", width: "", height: "" }) => {
  const { exports } = harness();
  const calls = [];
  const tree = exports.ShiprocketPanel({ order: { id: "order", payment_method: "prepaid", fulfilment_method: "delivery", ...shiprocket, ...order }, pkg,
    reconcileId: "", locked: false, onPackage: () => {}, onReconcileId: () => {}, onSubmit: () => calls.push("submit"), onRecover: () => calls.push("recover"), onRelease: () => calls.push("release") });
  return { tree, calls, html: tree ? renderToStaticMarkup(tree) : "" };
};
const filled = { weight: "0.5", length: "20", width: "15", height: "10" };

test("Shiprocket delivery orders cannot be dispatched before Shiprocket confirms the order", () => {
  const tree = harness(shiprocket).render();
  assert.equal(button(tree, "Dispatch & invoice").props.disabled, true);
  assert.match(renderToStaticMarkup(tree), /Submit the packed order to Shiprocket above first/);
  assert.equal(button(harness({ ...shiprocket, status: "shipment_booked", shiprocket_order_id: 77 }).render(), "Dispatch & invoice").props.disabled, false);
});

test("review orders cannot book a shipment until a warehouse passes stock review", async () => {
  const h = harness({ ...shiprocket, status: "fulfilment_review" });
  const tree = h.render();
  assert.match(renderToStaticMarkup(tree), /resolve the stock review before submitting to Shiprocket/);
  assert.equal(button(tree, "Resolve stock review").props.disabled, false);
  button(tree, "Resolve stock review").props.onClick();
  await flush();
  assert.equal(h.requests[0][0], "/orders/order/resolve-fulfilment");
  assert.deepEqual(JSON.parse(h.requests[0][1].body), { ship_from_store_id: "warehouse" });
  assert.equal(button(panel({ status: "fulfilment_review" }, filled).tree, "Submit packed order to Shiprocket"), undefined);
});

test("an order with a shipment in progress cannot be cancelled locally", () => {
  for (const order of [{ status: "shipping_pending" }, { status: "shipment_booked" },
    { status: "fulfilment_review", shiprocket_order_id: 123 }]) {
    const tree = harness({ ...shiprocket, ...order }).render();
    assert.doesNotMatch(renderToStaticMarkup(tree), /<summary>Cancel order<\/summary>/);
    assert.match(renderToStaticMarkup(tree), /shipping provider and support/);
  }
});
test("paid Shiprocket orders show an inline submit panel that needs package dimensions", () => {
  const empty = panel({ status: "paid" });
  assert.equal(button(empty.tree, "Submit packed order to Shiprocket").props.disabled, true);
  const ready = panel({ status: "paid" }, filled);
  const submit = button(ready.tree, "Submit packed order to Shiprocket");
  assert.equal(submit.props.disabled, false);
  submit.props.onClick();
  assert.deepEqual(ready.calls, ["submit"]);
});

test("orders dispatched before Shiprocket submission can still be submitted or recovered", () => {
  const late = panel({ status: "dispatched", invoice_id: "invoice", shiprocket_order_id: null }, filled);
  assert.match(late.html, /dispatched before it was submitted to Shiprocket/);
  assert.equal(button(late.tree, "Submit packed order to Shiprocket").props.disabled, false);
  assert.match(late.html, /Recover shipment \/ update tracking/);
  const uncertain = panel({ status: "dispatched", shiprocket_order_id: null, shipping_error: "Provider response uncertain" }, filled);
  assert.equal(button(uncertain.tree, "Submit packed order to Shiprocket"), undefined);
  assert.match(uncertain.html, /Provider response uncertain/);
  assert.match(uncertain.html, /Recover shipment/);
});

test("unconfirmed submissions can be released after a confirmation, and rejected ones resubmitted directly", () => {
  const uncertain = panel({ status: "delivered", shiprocket_order_id: null, shipping_error: "Provider response uncertain. Reconcile in Shiprocket using the Tenali order ID." }, filled);
  const release = button(uncertain.tree, "Not in Shiprocket: allow resubmission");
  try {
    testWindow.confirm = () => false;
    release.props.onClick();
    assert.deepEqual(uncertain.calls, []);
    testWindow.confirm = () => true;
    release.props.onClick();
    assert.deepEqual(uncertain.calls, ["release"]);
  } finally { testWindow.confirm = () => true; }
  const rejected = panel({ status: "dispatched", shiprocket_order_id: null, shipping_error: "Shiprocket rejected the request. No shipment was created." }, filled);
  assert.equal(button(rejected.tree, "Submit packed order to Shiprocket").props.disabled, false);
  assert.equal(button(rejected.tree, "Not in Shiprocket: allow resubmission"), undefined);
  assert.match(rejected.html, /No shipment was created/);
  assert.equal(button(panel({ status: "paid" }, filled).tree, "Not in Shiprocket: allow resubmission"), undefined);
  assert.ok(button(panel({ status: "shipping_pending" }).tree, "Not in Shiprocket: allow resubmission"));
});

test("booked shipments show Shiprocket references and test payments never submit", () => {
  const booked = panel({ status: "dispatched", shiprocket_order_id: 991, shipment_id: 552, awb: "AWB1", courier: "Delhivery" });
  assert.match(booked.html, /991/); assert.match(booked.html, /552/); assert.match(booked.html, /AWB1/); assert.match(booked.html, /Delhivery/);
  assert.equal(button(booked.tree, "Submit packed order to Shiprocket"), undefined);
  const test = panel({ status: "paid", provider_key_id: "rzp_test_x" }, filled);
  assert.equal(button(test.tree, "Submit packed order to Shiprocket"), undefined);
  assert.match(test.html, /test payment/);
  assert.equal(panel({ shipping_provider: "self", status: "paid" }).tree, null);
});

test("unbooked orders marked delivered can still be submitted and Mark delivered waits for Shiprocket", () => {
  const delivered = panel({ status: "delivered", invoice_id: "invoice", shiprocket_order_id: null }, filled);
  assert.match(delivered.html, /marked delivered but was never submitted/);
  assert.equal(button(delivered.tree, "Submit packed order to Shiprocket").props.disabled, false);
  const unbooked = harness({ ...shiprocket, status: "dispatched", invoice_id: "invoice", shiprocket_order_id: null }).render();
  assert.equal(button(unbooked, "Mark delivered"), undefined);
  const booked = harness({ ...shiprocket, status: "dispatched", invoice_id: "invoice", shiprocket_order_id: 991 }).render();
  assert.ok(button(booked, "Mark delivered"));
});
