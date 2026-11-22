const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function render(period, storeId = "", overridesData = {}) {
  const data = {
    from_date: "2026-01-01", to_date: "2026-01-31", inventory: null, orders: null,
    sales: { total: 100, invoices: 1, top_items: [] },
    purchases: { total: 125, bills: 1, pending_receipts: 0, quantity_to_receive: 0 },
    cash_flow: storeId ? null : { inflow: 80, outflow: 50, net: 30 }, outflow: storeId ? null : { total: 50, entries: 2 },
    receivables: null, borrowing_outstanding: null, refunds_pending: null, ...overridesData,
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

test("outstanding balances appear first, grouped by scope and linked to follow-up", () => {
  const data = {
    receivables: { open: 3, outstanding: 1250, reminders_due: 2, bad_debt: 1 },
    borrowing_outstanding: 25000,
    refunds_pending: { customer_amount: 200, customer_count: 1, vendor_amount: 300, vendor_count: 2 },
  };
  const html = render("month", "", data);
  assert.ok(html.indexOf("Outstanding &amp; follow-up") < html.indexOf("Monthly financial overview"));
  assert.ok(html.indexOf("Monthly financial overview") < html.indexOf("Sales orders by channel") || !html.includes("Sales orders by channel"));
  assert.match(html, /Current balances and follow-ups across all dates/);
  assert.match(html, /<h3>Collections<\/h3>/);
  assert.match(html, /<h3>Borrowing &amp; refunds<\/h3>/);
  assert.match(html, /Borrowed less repaid/);
  for (const text of ["Open receivables", "Reminders due", "Bad debt cases", "Net borrowing outstanding", "Refunds to pay customers", "Vendor refunds to receive"]) {
    assert.equal(html.split(text).length - 1, 1);
  }
  assert.match(html, /href="\/portal\/receivables\?status=OPEN"/);
  const selected = render("day", "store 1", { receivables: data.receivables });
  assert.match(selected, /selected store/);
  assert.match(selected, /href="\/portal\/receivables\?status=OPEN&amp;store_id=store%201"/);
  assert.match(selected, /href="\/portal\/receivables\?focus=reminders&amp;store_id=store%201"/);
  assert.doesNotMatch(selected, /Borrowing &amp; refunds/);
  assert.doesNotMatch(render("day"), /Outstanding &amp; follow-up/);
});
