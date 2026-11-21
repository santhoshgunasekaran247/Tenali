const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(file, overrides = {}) {
  const exports = {};
  const source = readFileSync(path.join(__dirname, "..", "src", ...file.split("/")), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(compiled, { exports, require: name => overrides[name] || require(name) });
  return exports;
}

const messages = load("features/aiMessages.ts");
const { AssistantMessage } = load("components/AssistantMessage.tsx", {
  "../features/aiMessages": messages,
  "../features/portalNavigation": { portalEntries: [{ path: "/portal/billing" }] },
  "react-router-dom": { Link: ({ to, children }) => React.createElement("a", { href: to }, children) },
});
const render = content => renderToStaticMarkup(React.createElement(AssistantMessage, { content: messages.readableMessage(content) }));

test("verified totals appear before expandable records, with dates and warnings visible", () => {
  const html = render("From your Tenali records — Invoices (2)\n" +
    "• I01: total ₹1.00 · status posted\n• I02: total ₹1,000.00 · status posted\n" +
    "This month = 2026-11-01 to 2026-11-21.\nTotal: ₹1,001.00\n\n" +
    "From your Tenali records — Transactions (10+)\n• Payment: amount ₹1.00\n" +
    "More records match; ask with a narrower name, store or date.");
  assert.ok(html.indexOf("Total: ₹1,001.00") < html.indexOf("View 2 records"));
  assert.match(html, /This month = 2026-11-01 to 2026-11-21/);
  assert.match(html, /More records match/);
  assert.match(html, /<details class="ai-record-details"><summary>View 2 records<\/summary>/);
  assert.match(html, /I01: total ₹1.00/);
  assert.match(html, /Transactions \(10\+\)/);
});

test("incomplete and empty results never gain an invented total", () => {
  const partial = render("From your Tenali records — Invoices (1+)\n• I01: total ₹100.00\nMore records match; ask with a narrower name, store or date.");
  assert.doesNotMatch(partial, /ai-record-total/);
  assert.match(partial, /View 1 record/);
  const empty = render("From your Tenali records — Invoices (0)\n• No matching records.");
  assert.doesNotMatch(empty, /ai-record-total|<details/);
  assert.match(empty, /No matching records/);
});

test("ordinary replies, links and old stored results remain readable", () => {
  const ordinary = render("Open [Billing](/portal/billing) to continue.");
  assert.match(ordinary, /href="\/portal\/billing"/);
  assert.doesNotMatch(ordinary, /ai-record-result/);
  const legacy = render('Checking.\n\nVerified Tenali lookup (read only):\n{"capability":"accounts","items":[{"account_name":"Main","current_balance":"1000.00"}],"more_matches":false}');
  assert.match(legacy, /Accounts \(1\)/);
  assert.match(legacy, /Main: current balance ₹1,000.00/);
});

test("ledger entries explain money direction and display readable labelled details", () => {
  const html = render("From your Tenali records — Transactions (3)\n" +
    "• amount ₹17,920.00 · from account name Main Account · direction outflow · payment mode bank · category purchase_payment · transaction date 14 Nov 2026 · source type purchase_payment\n" +
    "• amount ₹10,000.00 · to account name Main Account · direction inflow · category borrow_settlement · transaction date 14 Nov 2026 · source type borrowing · reversed\n" +
    "• amount ₹500.00 · from account name Main Account · to account name Savings · direction transfer · source type reversal\n" +
    "Total amount: ₹28,420.00");
  assert.match(html, /₹17,920.00<\/strong><span>Money out/);
  assert.match(html, /₹10,000.00<\/strong><span>Money in/);
  assert.match(html, /₹500.00<\/strong><span>Transfer/);
  assert.match(html, /<dt>From account<\/dt><dd>Main Account<\/dd>/);
  assert.match(html, /<dt>Category<\/dt><dd>purchase payment<\/dd>/);
  assert.match(html, /<dt>Source<\/dt><dd>borrowing<\/dd>/);
  assert.match(html, /<dt>Status<\/dt><dd>Reversed<\/dd>/);
  assert.match(html, /<dt>Source<\/dt><dd>reversal<\/dd>/);
  assert.doesNotMatch(html, /Total amount: ₹28,420.00|purchase_payment|borrow_settlement/);
  assert.match(html, /not a sales or cash-flow total/);
});

test("legacy ledger rows are formatted and ambiguous rows are never discarded", () => {
  const legacy = render('Verified Tenali lookup (read only):\n{"capability":"transactions","items":[{"amount":"17920.00","from_account_name":"Main Account","direction":"OUTFLOW","category":"purchase_payment","transaction_date":"2026-11-14"}],"more_matches":false}');
  assert.match(legacy, /₹17,920.00<\/strong><span>Money out/);
  assert.match(legacy, /<dt>Date<\/dt><dd>14 Nov 2026<\/dd>/);
  const ambiguous = "amount ₹100.00 · direction outflow · unexpected field value";
  assert.match(render(`From your Tenali records — Transactions (1)\n• ${ambiguous}`), /unexpected field value/);
  assert.doesNotMatch(render(`From your Tenali records — Transactions (1)\n• ${ambiguous}`), /ai-ledger-item/);
});
