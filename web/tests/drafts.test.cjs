const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function draftHarness() {
  let context, cursor = 0, states = [], refs = [];
  const react = {
    createContext() { context = { current: null, Provider: () => null }; return context; },
    useContext: value => value.current,
    useCallback: callback => callback,
    useRef(initial) { const i = cursor++; return refs[i] ||= { current: initial }; },
    useState(initial) {
      const i = cursor++;
      if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
      return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
    },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "drafts.tsx"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => name === "react" ? react : require(name) });
  function workspace() {
    states = []; refs = []; cursor = 0;
    const tree = exports.WorkspaceDraftProvider({ children: null });
    context.current = tree.props.value;
    states = []; refs = []; cursor = 0;
  }
  workspace();
  return {
    ...exports,
    workspace,
    mount() { states = []; cursor = 0; },
    render(key, initial) { cursor = 0; return exports.useDraftState(key, initial); },
    size() { return context.current.size; },
  };
}

test("drafts survive navigation but reset with a new authentication/workspace provider", () => {
  const harness = draftHarness();
  const [, update] = harness.render("billing.form", { notes: "" });
  update(previous => ({ ...previous, notes: "unsaved invoice" }));
  harness.mount();
  assert.equal(harness.render("billing.form", { notes: "" })[0].notes, "unsaved invoice");
  harness.workspace();
  assert.equal(harness.render("billing.form", { notes: "" })[0].notes, "");
});

test("state keys isolate pages, functional updates compose, and resets persist", () => {
  const harness = draftHarness();
  let [value, update] = harness.render("invoice.lines", 0);
  update(previous => previous + 1);
  update(previous => previous + 2);
  assert.equal(harness.render("invoice.lines", 0)[0], 3);
  harness.mount();
  assert.equal(harness.render("purchase.lines", 10)[0], 10);
  harness.mount();
  [value, update] = harness.render("invoice.lines", 0);
  assert.equal(value, 3);
  update(0);
  harness.mount();
  assert.equal(harness.render("invoice.lines", 99)[0], 0);
});

test("idempotency keys restore without creating a second key and entity drafts can be discarded", () => {
  const harness = draftHarness();
  let generated = 0;
  const key = () => `key-${++generated}`;
  assert.equal(harness.render("billing.requestKey", key)[0], "key-1");
  harness.mount();
  assert.equal(harness.render("billing.requestKey", key)[0], "key-1");
  assert.equal(generated, 1);
  harness.mount();
  harness.render("product.new.form", { name: "test" });
  harness.useClearDrafts()("product.new.");
  assert.equal(harness.size(), 1);
});

test("changing an entity key in a mounted editor does not reuse another entity's values", () => {
  const harness = draftHarness();
  const [, update] = harness.render("brand.form", "original");
  update("brand draft");
  assert.equal(harness.render("category.form", "category")[0], "category");
  assert.equal(harness.render("brand.form", "original")[0], "brand draft");
});
