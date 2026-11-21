const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function render(period, storeId = "") {
  const data = {
    from_date: "2026-01-01", to_date: "2026-01-31", inventory: null, orders: null,
    sales: { total: 100, invoices: 1, top_items: [] },
    purchases: { total: 125, bills: 1, pending_receipts: 0, quantity_to_receive: 0 },
    cash_flow: storeId ? null : { inflow: 80, outflow: 50, net: 30 }, outflow: storeId ? null : { total: 50, entries: 2 },
    receivables: null, borrowing_outstanding: null, refunds_pending: null,
  };
  const values = [period, "2026-01", "2026-01-10", "2026-01-01", "2026-01-31", storeId, [], data, "", false, 0];
  const overrides = {
    react: { ...React, useState: () => [values.shift(), () => {}], useEffect: () => {} },
    "react-router-dom": { Link: ({ to, children, ...props }) => React.createElement("a", { ...props, href: to }, children) },
    "../features/auth": { useAuth: () => ({ user: {} }) },
    "../api": { api: {} },
    "../components/Notifications": { FloatingAlert: ({ children }) => children },
    "./Notifications": { FloatingAlert: ({ children }) => children },
    "../features/catalog/utils": { toAssetUrl: value => value },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "components", "OperationsDashboard.tsx"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => overrides[name] || require(name) });
  return renderToStaticMarkup(React.createElement(exports.OperationsDashboard));
}

test("daily, monthly and custom views show the financial overview and limitations", () => {
  for (const [period, label] of [["day", "Daily"], ["month", "Monthly"], ["range", "Date range"]]) {
    const html = render(period);
    assert.match(html, new RegExp(`${label} financial overview`));
    assert.match(html, /Net account cash flow/);
    assert.match(html, /It is not profit/);
    assert.doesNotMatch(html, /Estimated profit \/ loss/);
    assert.match(html, /Account outflow/);
    assert.match(html, /Transfers between accounts are excluded/);
  }
  assert.match(render("range"), /From date/);
  assert.match(render("range"), /To date/);
  assert.match(render("day"), /Reporting date/);
  assert.match(render("month", "store"), /unavailable for a single store/);
});
