const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

test("quotation PDF is labelled as a quotation and includes its notes", async () => {
  const text = [], tables = [], titles = [], saved = [];
  class PDF {
    setProperties(value) { titles.push(value.title); }
    splitTextToSize(value) { return [value]; }
    getNumberOfPages() { return 1; }
    getTextWidth() { return 10; }
    text(value) { text.push(value); }
    save(value) { saved.push(value); }
  }
  for (const method of ["setFont", "setFontSize", "setTextColor", "setDrawColor", "setLineWidth",
    "line", "rect", "setFillColor", "setPage", "addPage"]) PDF.prototype[method] = () => {};
  const overrides = {
    jspdf: { jsPDF: PDF, GState: class {} },
    "jspdf-autotable": { default: (_pdf, options) => { tables.push(options); options.didDrawPage({ cursor: { y: 50 } }); } },
    "./catalog/utils": { toAssetUrl: value => value },
    "./invoiceReissue": { cancellationStamp: () => null },
    "./invoiceSettings": { DEFAULT_INVOICE_SETTINGS: {
      title: "TAX INVOICE", primary_color: "#112233", accent_color: "#445566",
      signature_width_mm: 30, logo_width_mm: 20, footer_text_color: "#ffffff",
      bill_to_label: "Bill to", ship_to_label: "Ship to", amount_in_words_label: "Amount in words",
    } },
  };
  const source = readFileSync(path.join(__dirname, "..", "src", "features", "invoicePdf.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, require: name => overrides[name] || require(name) });
  const quote = { id: "1", company_id: "c", store_id: "s", customer_party_id: "p",
    quotation_number: "QUO-123", quotation_date: "2026-11-15", reference: null,
    notes: "Valid for 7 days", created_at: "2026-11-15",
    document_data: { seller: { company_name: "Seller", invoice_settings: {} },
      bill_to: { name: "Customer", address: "Address" }, ship_to: { name: "Customer", address: "Address" },
      place_of_supply: "33 - Tamil Nadu", interstate: false,
      lines: [{ description: "Widget", hsn: "1234", quantity: "1", rate: "100", gst_rate: "0",
        taxable: "100", cgst: "0", sgst: "0", igst: "0", total: "100" }],
      subtotal: "100", gst_total: "0", total: "100" } };
  await exports.downloadQuotationPdf(quote);
  assert.equal(titles[0], "QUOTATION QUO-123");
  assert.ok(text.includes("QUOTATION"));
  assert.ok(JSON.stringify(tables).includes("Quotation No: QUO-123"));
  assert.ok(JSON.stringify(tables).includes("Notes: Valid for 7 days"));
  assert.deepEqual(saved, ["QUO-123.pdf"]);
});
