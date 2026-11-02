const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = readFileSync(path.join(__dirname, "..", "src", "features", "inventorySearch.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, { exports: exportsObject });
const { matchesInventorySearch } = exportsObject;
const product = {
  name: "Travel Bottle", sku: "BOT-10", portal_product_id: "PRD-001",
  item_name: null, brand_name: "Acme", category_name: "Gifts",
  variants: [{ variant_name: "Large Blue", sku: "BLUE-20", size: "1L", colour: "Blue" }],
};

test("search trims whitespace, ignores case and matches words in any order", () => {
  for (const search of ["", "  ", "  ACME   bottle ", "blue travel", "gifts 1l", "BOT-10", "prd-001", "BLUE-20"]) {
    assert.equal(matchesInventorySearch(product, search), true, search);
  }
});
test("all search words must match and literal punctuation is safe", () => {
  for (const search of ["bottle red", "not-here", "[", ".*"]) {
    assert.equal(matchesInventorySearch(product, search), false, search);
  }
});
test("missing optional fields and no variants do not break search", () => {
  const minimal = {name: "Sample", portal_product_id: "X", variants: []};
  assert.equal(matchesInventorySearch(minimal, "sample"), true);
  assert.equal(matchesInventorySearch(minimal, "blue"), false);
});
