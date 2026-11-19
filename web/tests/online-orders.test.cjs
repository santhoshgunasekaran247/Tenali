const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

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
    "../features/shop": { paymentLabel: () => "Paid online", accountRequest: async (...args) => {
      requests.push(args); return request(...args);
    } },
  };
  vm.runInNewContext(compiled, { exports, require: name => mocks[name] || require(name) });
  const order = { id: "order", store_id: "online", payment_method: "prepaid", status: "paid",
    fulfilment_method: "delivery", shipping_provider: "self", razorpay_payment_id: "pay_captured",
    advance_transaction_id: null, ship_from_store_id: "warehouse", invoice_id: null,
    review_reason: "Advance not posted: set a settlement account", ...overrides };
  return {
    requests, errors, messages,
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
  assert.match(html, /<label>Refund from<select/);
});

test("posted advances enable dispatch and remove the retry panel", () => {
  const tree = harness({ advance_transaction_id: "advance", review_reason: null }).render();
  assert.equal(button(tree, "Dispatch & invoice").props.disabled, false);
  assert.equal(button(tree, "Retry posting payment advance"), undefined);
  assert.doesNotMatch(renderToStaticMarkup(tree), /Post the verified payment/);
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
