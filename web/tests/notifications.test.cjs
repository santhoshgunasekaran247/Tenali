const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");

function harness(initial = []) {
  let state = initial;
  const effects = [], timers = [], cleared = [];
  const react = {
    createContext: () => ({ Provider: () => null }),
    useState: () => [state, update => { state = typeof update === "function" ? update(state) : update; }],
    useCallback: callback => callback,
    useMemo: callback => callback(),
    useRef: () => ({ current: null }),
    useEffect: effect => effects.push(effect),
  };
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "Notifications.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    document: { body: {}, querySelectorAll: () => [] },
    window: { setTimeout: (callback, delay) => { timers.push({ callback, delay }); return timers.length; }, clearTimeout: id => cleared.push(id) },
    require: name => name === "react" ? react : name === "react-dom" ? { createPortal: element => element } : require(name),
  });
  return {
    effects, timers, cleared,
    provider: () => exports.NotificationProvider({ children: null }),
    notices: () => state,
  };
}

test("success alerts are accessible, auto-dismiss at exactly five seconds and cancel their timer on unmount", () => {
  const notice = { id: "one", tone: "success", content: "Invoice posted" };
  const h = harness([notice]);
  const provider = h.provider();
  const cardElement = provider.props.children[1].props.children[0];
  h.effects.length = 0;
  const card = cardElement.type(cardElement.props);
  assert.equal(card.props.role, "status");
  const cleanup = h.effects[0]();
  assert.equal(h.timers.length, 1);
  assert.equal(h.timers[0].delay, 5000);
  h.timers[0].callback();
  assert.equal(h.notices().length, 0);
  cleanup();
  assert.deepEqual(h.cleared, [1]);
});

test("errors remain until dismissed and repeated notice IDs replace rather than duplicate", () => {
  const notice = { id: "one", tone: "error", content: "Unable to save" };
  const h = harness([notice]);
  const provider = h.provider();
  provider.props.value.show({ ...notice, content: "Retry failed" });
  assert.equal(h.notices().length, 1);
  assert.equal(h.notices()[0].content, "Retry failed");
  const cardElement = provider.props.children[1].props.children[0];
  h.effects.length = 0;
  const card = cardElement.type(cardElement.props);
  assert.equal(card.props.role, "alert");
  h.effects[0]();
  assert.equal(h.timers.length, 0);
  const close = card.props.children[1];
  assert.equal(close.props["aria-label"], "Dismiss notification");
  close.props.onClick();
  assert.equal(h.notices().length, 0);
});
