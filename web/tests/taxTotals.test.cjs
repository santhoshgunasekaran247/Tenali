const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = readFileSync(path.join(__dirname, "..", "src", "features", "taxTotals.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, { exports: exportsObject });
const { calculateLineTotals } = exportsObject;
const line = (quantity, rate, gst_rate) => ({ description: "Test", hsn: "8516", quantity, rate, gst_rate });
const totals = (result) => ({ subtotal: result.subtotal, gstTotal: result.gstTotal, total: result.total });

test("fractional quantities round half up in paise before GST", () => {
  assert.deepEqual(totals(calculateLineTotals([line(0.075, 27.4, 18)])),
    { subtotal: 2.06, gstTotal: 0.37, total: 2.43 });
  assert.deepEqual(totals(calculateLineTotals([line(0.09, 26.5, 18)])),
    { subtotal: 2.39, gstTotal: 0.43, total: 2.82 });
});

test("each line and its GST are rounded before aggregation", () => {
  assert.deepEqual(totals(calculateLineTotals([line(1, 0.05, 10), line(1, 0.05, 10)])),
    { subtotal: 0.1, gstTotal: 0.02, total: 0.12 });
  assert.deepEqual(totals(calculateLineTotals([line(1, 0.01, 50)])),
    { subtotal: 0.01, gstTotal: 0.01, total: 0.02 });
});

test("supported large amounts remain exact and overflow is not presented as a total", () => {
  const maximum = [line(100, 9999999999.99, 0), line(1, 0.99, 0)];
  assert.deepEqual(totals(calculateLineTotals(maximum)),
    { subtotal: 999999999999.99, gstTotal: 0, total: 999999999999.99 });
  const overflow = calculateLineTotals([...maximum, line(1, 0.01, 0)]);
  assert.ok(Number.isNaN(overflow.subtotal) && Number.isNaN(overflow.gstTotal) && Number.isNaN(overflow.total));
});

test("non-finite and negative inputs do not produce a valid-looking total", () => {
  for (const value of [NaN, Infinity, -1]) {
    assert.ok(Number.isNaN(calculateLineTotals([line(value, 1, 18)]).total));
    assert.ok(Number.isNaN(calculateLineTotals([line(1, value, 18)]).total));
    assert.ok(Number.isNaN(calculateLineTotals([line(1, 1, value)]).total));
  }
});

test("inclusive prices back out GST per line and match the server", () => {
  assert.deepEqual(totals(calculateLineTotals([line(1, 1180, 18)], true)),
    { subtotal: 1000, gstTotal: 180, total: 1180 });
  assert.deepEqual(totals(calculateLineTotals([line(0.075, 27.4, 18)], true)),
    { subtotal: 1.75, gstTotal: 0.31, total: 2.06 });
  assert.deepEqual(totals(calculateLineTotals([{ ...line(0.075, 27.4, 18), price_includes_gst: false }], true)),
    { subtotal: 2.06, gstTotal: 0.37, total: 2.43 });
  assert.deepEqual(totals(calculateLineTotals([line(2, 50, 0)], true)), { subtotal: 100, gstTotal: 0, total: 100 });
});
