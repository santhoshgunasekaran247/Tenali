const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function harness() {
  const states = [], deps = [];
  let cursor = 0, effects = [];
  const react = { ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in states)) states[index] = initial;
      return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
    },
    useId: () => "page-size",
    useEffect(effect, next) {
      const index = cursor++;
      if (!deps[index] || next.some((value, i) => value !== deps[index][i])) {
        deps[index] = next; effects.push(effect);
      }
    },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "components", "PaginatedTableBody.tsx"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => name === "react" ? react : require(name) });
  return rows => {
    cursor = 0;
    const tree = exports.PaginatedTableBody({ children: rows });
    const pending = effects; effects = []; pending.forEach(effect => effect());
    return tree;
  };
}
function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return React.Children.toArray(node.props?.children).map(child => find(child, predicate)).find(Boolean);
}
const makeRows = n => Array.from({ length: n }, (_, index) =>
  React.createElement("tr", { key: `record-${index}` }, React.createElement("td", null, `Record ${index + 1}`)));
const html = tree => renderToStaticMarkup(React.createElement("table", null, tree));

test("page sizes, boundaries, and filtering work on loaded rows", () => {
  const render = harness(), rows = makeRows(32);
  let tree = render(rows), text = html(tree);
  assert.match(text, /1–10 of 32 loaded rows/);
  assert.match(text, /Record 10/);
  assert.doesNotMatch(text, /Record 11/);
  const next = () => find(tree, node => node.type === "button" && node.props.children === "Next");
  next().props.onClick();
  tree = render(rows); assert.match(html(tree), /11–20 of 32 loaded rows/);
  find(tree, node => node.type === "select").props.onChange({ target: { value: "25" } });
  tree = render(rows); assert.match(html(tree), /1–25 of 32 loaded rows/);
  next().props.onClick();
  tree = render(rows); assert.match(html(tree), /26–32 of 32 loaded rows/);
  assert.equal(next().props.disabled, true);
  render(rows.slice(0, 3));
  tree = render(rows.slice(0, 3));
  assert.match(html(tree), /1–3 of 3 loaded rows/);
});

test("empty or loading placeholders remain visible without counting as records", () => {
  const render = harness();
  const placeholder = React.createElement("tr", null, React.createElement("td", { colSpan: 5 }, "No records"));
  const text = html(render(placeholder));
  assert.match(text, /No records/);
  assert.doesNotMatch(text, /loaded rows/);
});

test("stock breakdown keeps store and variant balances separate", () => {
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "inventoryStockRows.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports });
  const rows = exports.inventoryStockRows({
    id: "p", store_stocks: [{ store_id: "s1", store_name: "Shop", store_code: "S", quantity: 3 }],
    variants: [
      { id: "v1", variant_name: "Blue", store_stocks: [
        { store_id: "s1", store_name: "Shop", store_code: "S", quantity: 2 },
        { store_id: "w1", store_name: "Warehouse", store_code: "W", quantity: 7 },
      ] },
      { id: "v2", variant_name: "Red", store_stocks: [] },
    ],
  });
  assert.equal(rows.length, 3);
  assert.equal(rows[0].name, "Base product");
  assert.equal(rows[1].name, "Blue");
  assert.equal(rows[1].store.store_name, "Shop");
  assert.equal(rows[2].store.store_name, "Warehouse");
  assert.equal(rows[2].store.quantity, 7);
  assert.equal(new Set(rows.map(row => row.key)).size, rows.length);
});
