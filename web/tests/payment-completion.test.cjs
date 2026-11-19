const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const order = {
  id: "local-order", payment_method: "prepaid", status: "awaiting_payment",
  provider_key_id: "rzp_test_fixture", razorpay_order_id: "order_fixture",
  razorpay_payment_id: null, total_paise: 100, address: { phone: "9876543210" },
};
const paid = { ...order, status: "paid", razorpay_payment_id: "pay_fixture" };
const shopper = { display_name: "Shopper", email: "shopper@example.invalid" };
const result = { razorpay_order_id: "order_fixture", razorpay_payment_id: "pay_fixture", razorpay_signature: "signature" };

function harness(respond = async () => ({ status: 200, body: paid })) {
  let options, failure;
  const timers = new Map(), calls = [];
  let nextTimer = 0, closed = 0;
  const exports = {};
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "features", "shop.ts"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(compiled, {
    exports, AbortController,
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    document: { cookie: "" },
    window: { Razorpay: class {
      constructor(value) { options = value; }
      on(event, callback) { if (event === "payment.failed") failure = callback; }
      open() {}
      close() { closed++; options.modal.ondismiss(); }
    } },
    require: () => ({ tenantFetch: async (url, init) => {
      calls.push({ url, init });
      const { status, body } = await respond(url, init);
      return { ok: status < 400, status, json: async () => body };
    } }),
  });
  return {
    calls, timers, get closed() { return closed; },
    start(signal) { return exports.payOrder(order, shopper, "Store", signal); },
    success() { options.handler(result); },
    dismiss() { options.modal.ondismiss(); },
    fail() { failure(); },
    async tick(delay) {
      const entry = [...timers.entries()].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, `No ${delay}ms timer scheduled`);
      timers.delete(entry[0]); entry[1].callback();
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

test("success callback verifies the payment before completing", async () => {
  const h = harness();
  const pending = h.start();
  h.success();
  const verified = await pending;
  assert.equal(verified.status, "paid");
  assert.equal(h.calls[0].url, "/api/shop/orders/local-order/confirm");
  assert.deepEqual(JSON.parse(h.calls[0].init.body), result);
  assert.equal(h.timers.size, 0);
});

test("a lost browser callback still completes when the webhook records payment", async () => {
  const h = harness();
  const pending = h.start();
  await h.tick(3000);
  assert.equal((await pending).razorpay_payment_id, "pay_fixture");
  assert.equal(h.calls[0].url, "/api/shop/orders/local-order");
  assert.equal(h.closed, 1);
  assert.equal(h.timers.size, 0);
});

test("a slow confirmation cannot hide a payment already verified by the webhook", async () => {
  const h = harness(url => url.endsWith("/confirm") ? new Promise(() => {}) : Promise.resolve({ status: 200, body: paid }));
  const pending = h.start();
  h.success();
  await h.tick(3000);
  assert.equal((await pending).status, "paid");
  assert.equal(h.timers.size, 0);
});

test("a failed browser confirmation recovers through the server without starting another payment", async () => {
  const h = harness(async url => url.endsWith("/confirm")
    ? { status: 502, body: { detail: "Provider unavailable" } } : { status: 200, body: paid });
  const pending = h.start();
  h.success();
  assert.equal((await pending).status, "paid");
  assert.deepEqual(h.calls.map(call => call.url), [
    "/api/shop/orders/local-order/confirm", "/api/shop/orders/local-order/reconcile-payment",
  ]);
  assert.equal(h.timers.size, 0);
});

test("missing callback and webhook trigger bounded server-side reconciliation", async () => {
  const h = harness();
  const pending = h.start();
  await h.tick(180000);
  assert.equal((await pending).status, "paid");
  assert.equal(h.calls[0].url, "/api/shop/orders/local-order/reconcile-payment");
  assert.equal(h.calls[0].init.method, "POST");
  assert.equal(h.timers.size, 0);
});

test("closing the modal checks for a captured payment before returning cancellation", async () => {
  const h = harness();
  const pending = h.start();
  h.dismiss();
  assert.equal((await pending).status, "paid");
  assert.match(h.calls[0].url, /reconcile-payment$/);
  const cancelled = harness(async () => ({ status: 409, body: { detail: "No single captured payment was confirmed." } }));
  const cancellation = cancelled.start();
  cancelled.dismiss();
  assert.equal(await cancellation, null);
  assert.equal(cancelled.timers.size, 0);
});

test("unverified responses never become payment success", async () => {
  for (const body of [order, { ...paid, id: "another-order" }, { ...paid, status: "refunded" }]) {
    const h = harness(async () => ({ status: 200, body }));
    const pending = h.start();
    const rejected = assert.rejects(pending, /not.*verified|could not.*verif/i);
    h.success();
    await rejected;
    assert.equal(h.timers.size, 0);
  }
});

test("pending polls never claim success and stop when the shopper leaves", async () => {
  const h = harness(async () => ({ status: 200, body: order }));
  const controller = new AbortController();
  const pending = h.start(controller.signal);
  const rejected = assert.rejects(pending, /cancel/i);
  await h.tick(3000);
  await h.tick(3000);
  assert.equal(h.closed, 0);
  assert.equal(h.calls.length, 2);
  controller.abort();
  await rejected;
  assert.equal(h.timers.size, 0);
});

test("a payment failure releases the UI and ignores late SDK callbacks", async () => {
  const h = harness();
  const pending = h.start();
  const rejected = assert.rejects(pending, /Payment failed.*My Orders/);
  h.fail();
  await rejected;
  h.success();
  assert.equal(h.calls.length, 0);
  assert.equal(h.timers.size, 0);
});

test("an unresponsive recovery request releases the UI with a no-double-payment warning", async () => {
  const h = harness(() => new Promise(() => {}));
  const pending = h.start();
  const rejected = assert.rejects(pending, /My Orders|pay again/);
  await h.tick(180000);
  await h.tick(30000);
  await rejected;
  assert.equal(h.timers.size, 0);
});

test("leaving the page cancels verification polling and ignores late success callbacks", async () => {
  const h = harness();
  const controller = new AbortController();
  const pending = h.start(controller.signal);
  const rejected = assert.rejects(pending, /cancel/i);
  controller.abort();
  await rejected;
  h.success();
  assert.equal(h.calls.length, 0);
  assert.equal(h.timers.size, 0);
});
