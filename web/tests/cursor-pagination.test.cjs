const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");

const source = readFileSync(path.join(__dirname, "..", "src", "components", "CursorPagination.tsx"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, {
  exports: exportsObject,
  require: name => name === "react" ? { ...React, useId: () => "page-size" } : require(name),
});

function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}

test("cursor controls expose page sizes and navigate only when enabled", () => {
  const calls = [];
  const props = { size: 25, page: 0, hasNext: true, busy: false,
    onSize: size => calls.push(size), onPrevious: () => calls.push("previous"), onNext: () => calls.push("next") };
  let tree = exportsObject.CursorPagination(props);
  const button = label => find(tree, node => node.type === "button" && node.props.children === label);
  const select = find(tree, node => node.type === "select");
  assert.deepEqual(Array.from(select.props.children, option => option.props.value), [10, 25, 50, 100]);
  assert.equal(button("Previous").props.disabled, true);
  assert.equal(button("Next").props.disabled, false);
  button("Next").props.onClick();
  select.props.onChange({ target: { value: "50" } });
  tree = exportsObject.CursorPagination({ ...props, page: 1, hasNext: false });
  assert.equal(button("Previous").props.disabled, false);
  assert.equal(button("Next").props.disabled, true);
  button("Previous").props.onClick();
  tree = exportsObject.CursorPagination({ ...props, busy: true });
  assert.equal(button("Next").props.disabled, true);
  assert.equal(find(tree, node => node.type === "select").props.disabled, true);
  assert.deepEqual(calls, ["next", 50, "previous"]);
});
