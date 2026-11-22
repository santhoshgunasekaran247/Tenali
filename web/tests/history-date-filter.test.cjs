const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");

test("history date filters offer presets and reject invalid custom ranges", () => {
  const states = [];
  let index = 0;
  const react = {...React, useState(initial) {
    const i = index++;
    if (!(i in states)) states[i] = initial;
    return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }];
  }};
  const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "..", "src", "components", "HistoryDateFilter.tsx"), "utf8"), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX},
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {exports, require: name => name === "react" ? react :
    name === "../features/workflowDates" ? {indiaDateKey: () => "2026-03-25"} : require(name)});
  const changes = [];
  const render = () => { index = 0; return exports.HistoryDateFilter({onChange: value => changes.push({...value})}); };
  const find = (node, predicate) => {
    if (!node || typeof node !== "object") return undefined;
    if (predicate(node)) return node;
    return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
  };
  const all = (node, predicate) => {
    if (!node || typeof node !== "object") return [];
    return [...(predicate(node) ? [node] : []), ...React.Children.toArray(node.props?.children).flatMap(child => all(child, predicate))];
  };
  let tree = render();
  find(tree, node => node.type === "select").props.onChange({target: {value: "month"}});
  assert.deepEqual(changes.pop(), {from: "2026-03-01", to: "2026-03-25"});
  tree = render();
  find(tree, node => node.type === "select").props.onChange({target: {value: "today"}});
  assert.deepEqual(changes.pop(), {from: "2026-03-25", to: "2026-03-25"});
  tree = render();
  find(tree, node => node.type === "select").props.onChange({target: {value: "custom"}});
  tree = render();
  const dates = all(tree, node => node.type === "input");
  dates[0].props.onChange({target: {value: "2026-04-01"}});
  dates[1].props.onChange({target: {value: "2026-03-01"}});
  tree = render();
  find(tree, node => node.type === "button").props.onClick();
  assert.equal(changes.length, 0);
  assert.ok(find(render(), node => node.props?.role === "alert"));
  dates[1].props.onChange({target: {value: "2026-04-30"}});
  tree = render();
  find(tree, node => node.type === "button").props.onClick();
  assert.deepEqual(changes.pop(), {from: "2026-04-01", to: "2026-04-30"});
});
