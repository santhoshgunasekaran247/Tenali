const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function indicator() {
  const listeners = {};
  const attributes = new Map();
  const root = { setAttribute: (key) => attributes.set(key, true), removeAttribute: key => attributes.delete(key), hasAttribute: key => attributes.has(key) };
  const document = { documentElement: root, addEventListener: (type, handler) => { listeners[type] = handler; } };
  const timers = [];
  const window = { setTimeout: callback => { timers.push(callback); return timers.length; }, clearTimeout: () => {} };
  class Element {}
  const exports = {};
  const code = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "features", "busyIndicator.ts"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(code, { exports, document, window, Element, Date, Map, Promise });
  exports.installBusyIndicator();
  const button = Object.assign(new Element(), { attrs: {}, setAttribute(key, value) { this.attrs[key] = value; }, removeAttribute(key) { delete this.attrs[key]; } });
  button.closest = () => button;
  return { ...exports, listeners, attributes, timers, button };
}

test("a pressed button shows loading until its request settles and the page shows progress", async () => {
  const busy = indicator();
  busy.listeners.click({ type: "click", target: busy.button });
  let finish;
  const request = busy.trackRequest(() => new Promise(resolve => { finish = resolve; }));
  assert.equal(busy.button.attrs["aria-busy"], "true");
  busy.timers.forEach(callback => callback());
  assert.equal(busy.attributes.has("data-busy"), true);
  finish("done");
  assert.equal(await request, "done");
  assert.equal(busy.button.attrs["aria-busy"], undefined);
  assert.equal(busy.attributes.has("data-busy"), false);
});

test("background requests without a recent click stay silent and failures still clear loading", async () => {
  const busy = indicator();
  assert.equal(await busy.trackRequest(async () => "poll"), "poll");
  assert.equal(busy.timers.length, 0);
  busy.listeners.click({ type: "click", target: busy.button });
  await assert.rejects(busy.trackRequest(async () => { throw new Error("failed"); }));
  assert.equal(busy.button.attrs["aria-busy"], undefined);
  assert.equal(busy.attributes.has("data-busy"), false);
});
