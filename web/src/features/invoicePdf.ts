import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { Invoice } from "../types";
import { toAssetUrl } from "./catalog/utils";
import { DEFAULT_INVOICE_SETTINGS } from "./invoiceSettings";

function colorRgb(value: string): [number, number, number] {
  return [1, 3, 5].map((offset) => parseInt(value.slice(offset, offset + 2), 16)) as [number, number, number];
}
const SMALL = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

function integerWords(value: number): string {
  if (value === 0) return "Zero";
  for (const [divisor, label] of [[10000000, "Crore"], [100000, "Lakh"], [1000, "Thousand"], [100, "Hundred"]] as const) {
    if (value >= divisor) {
      const remainder = value % divisor;
      return `${integerWords(Math.floor(value / divisor))} ${label}${remainder ? ` ${integerWords(remainder)}` : ""}`;
    }
  }
  return value < 20 ? SMALL[value] : `${TENS[Math.floor(value / 10)]}${value % 10 ? ` ${SMALL[value % 10]}` : ""}`;
}

export function amountInWords(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  const paise = Number(fraction.padEnd(2, "0").slice(0, 2));
  return `Indian Rupees ${integerWords(Number(whole))}${paise ? ` and ${integerWords(paise)} Paise` : ""} Only`;
}

async function loadInvoiceImage(url: string, label: string): Promise<{ data: string; ratio: number }> {
  const image = new Image();
  image.crossOrigin = "anonymous";
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error(`Invoice ${label} could not be loaded. Check Company Setup and API availability.`));
    image.src = url;
  });
  const canvas = document.createElement("canvas");
  canvas.width = Math.min(image.naturalWidth, 1000);
  canvas.height = Math.max(1, Math.round(image.naturalHeight * canvas.width / image.naturalWidth));
  const context = canvas.getContext("2d");
  if (!context) throw new Error(`Unable to prepare invoice ${label}.`);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return { data: canvas.toDataURL("image/png"), ratio: image.naturalWidth / image.naturalHeight };
}

export async function createInvoicePdf(invoice: Invoice): Promise<jsPDF> {
  const data = invoice.document_data;
  if (!data?.lines.length) throw new Error("This legacy invoice has no saved product details for a tax invoice.");
  const settings = { ...DEFAULT_INVOICE_SETTINGS, ...data.seller.invoice_settings };
  const NAVY = colorRgb(settings.primary_color);
  const GOLD = colorRgb(settings.accent_color);
  const [logo, signature] = await Promise.all([
    data.seller.logo_url ? loadInvoiceImage(toAssetUrl(data.seller.logo_url), "logo") : null,
    settings.signature_image ? loadInvoiceImage(toAssetUrl(settings.signature_image), "signature") : null,
  ]);
  const pdf = new jsPDF({ unit: "mm", format: "a4", compress: true });
  pdf.setProperties({ title: `${settings.title} ${invoice.invoice_number}`, author: data.seller.company_name });
  const money = (value: string | number) => Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  let endY = 42;
  const table = (options: Parameters<typeof autoTable>[1]) => {
    autoTable(pdf, {
      margin: { left: 15, right: 15, top: 42, bottom: 29 },
      styles: { font: "helvetica", fontSize: 9, textColor: NAVY, cellPadding: 3, overflow: "linebreak" },
      ...options,
      didDrawPage: (hook) => { endY = hook.cursor?.y || endY; },
    });
  };
  const seller = data.seller;
  const invoiceDate = new Date(`${invoice.invoice_date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  table({
    startY: 42, theme: "plain", columnStyles: { 0: { cellWidth: 100 }, 1: { cellWidth: 80 } },
    body: [[
      [seller.company_name, seller.address, `GSTIN: ${seller.gst_number || ""}`,
        seller.udyam_number ? `Udyam: ${seller.udyam_number}` : "",
        [seller.phone, seller.email].filter(Boolean).join(" | "), seller.website].filter(Boolean).join("\n"),
      `Invoice No: ${invoice.invoice_number}\nDate: ${invoiceDate}\nPlace of Supply: ${data.place_of_supply}${invoice.reference ? `\nReference: ${invoice.reference}` : ""}`,
    ]],
  });
  table({
    startY: endY + 4, theme: "grid",
    head: [[settings.bill_to_label, settings.ship_to_label]],
    headStyles: { fillColor: NAVY, textColor: 255 },
    columnStyles: { 0: { cellWidth: 90 }, 1: { cellWidth: 90 } },
    body: [[
      `${data.bill_to.name}\n${data.bill_to.address}${data.bill_to.gst_number ? `\nGSTIN: ${data.bill_to.gst_number}` : "\nUnregistered customer"}`,
      `${data.ship_to.name}\n${data.ship_to.address}`,
    ]],
  });
  const taxHeaders = data.interstate ? ["IGST"] : ["CGST", "SGST"];
  table({
    startY: endY + 6, theme: "grid",
    head: [["#", "Product / Description", "HSN", "Qty", "Rate", ...taxHeaders, "Total"]],
    headStyles: { fillColor: NAVY, textColor: 255, fontSize: 8 },
    styles: { fontSize: 8, cellPadding: 2.5, textColor: NAVY, overflow: "linebreak" },
    columnStyles: { 0: { cellWidth: 8 }, 1: { cellWidth: data.interstate ? 52 : 42 }, 2: { cellWidth: 19 } },
    body: data.lines.map((line, index) => [
      String(index + 1), line.description, line.hsn, line.quantity, money(line.rate),
      ...(data.interstate
        ? [`${money(line.igst)}\n(${Number(line.gst_rate)}%)`]
        : [`${money(line.cgst)}\n(${Number(line.gst_rate) / 2}%)`, `${money(line.sgst)}\n(${Number(line.gst_rate) / 2}%)`]),
      money(line.total),
    ]),
  });
  const taxSum = (key: "cgst" | "sgst" | "igst") => money(data.lines.reduce((sum, line) => sum + Math.round(Number(line[key]) * 100), 0) / 100);
  table({
    startY: endY + 4, theme: "plain", pageBreak: "avoid",
    columnStyles: { 0: { cellWidth: 130, halign: "right" }, 1: { cellWidth: 50, halign: "right" } },
    body: [
      ["Taxable Value (INR)", money(data.subtotal)],
      ...(data.interstate ? [["IGST", taxSum("igst")]] : [["CGST", taxSum("cgst")], ["SGST", taxSum("sgst")]]),
      ["Total GST", money(data.gst_total)],
      [{ content: "Invoice Total (INR)", styles: { fontStyle: "bold", fillColor: NAVY, textColor: 255 } }, { content: money(data.total), styles: { fontStyle: "bold", fillColor: NAVY, textColor: 255 } }],
    ],
  });
  table({ startY: endY + 4, theme: "plain", body: [[{
    content: `${settings.amount_in_words_label}: ${amountInWords(data.total)}`,
    styles: { fontStyle: "bold" },
  }]] });
  pdf.setFont("helvetica", "normal");
  pdf.setFontSize(9);
  const noteLines: string[] = settings.thank_you_note ? pdf.splitTextToSize(settings.thank_you_note, 117) : [];
  const companyLines: string[] = pdf.splitTextToSize(
    [seller.company_name, seller.address, seller.gst_number ? `GSTIN: ${seller.gst_number}` : ""].filter(Boolean).join("\n"), 117
  );
  const signatoryLines: string[] = [settings.signatory_label, settings.signatory_name, settings.signatory_designation]
    .filter(Boolean).flatMap((value) => pdf.splitTextToSize(value, 53));
  const signatureWidth = signature ? Math.min(settings.signature_width_mm, 28 * signature.ratio) : settings.signature_width_mm;
  const signatureHeight = signature ? signatureWidth / signature.ratio : 24;
  const closingHeight = Math.max(noteLines.length * 4 + companyLines.length * 4 + 12, signatureHeight + signatoryLines.length * 4 + 12);
  if (endY + closingHeight + 8 > 263) { pdf.addPage(); endY = 42; }
  const closingTop = Math.max(endY + 6, 263 - closingHeight);
  pdf.setDrawColor(225, 222, 216);
  pdf.setLineWidth(0.3);
  pdf.line(15, closingTop, 195, closingTop);
  pdf.setTextColor(...NAVY);
  if (noteLines.length) pdf.text(noteLines, 15, closingTop + 6, { lineHeightFactor: 1.26 });
  pdf.text(companyLines, 15, closingTop + noteLines.length * 4 + 10, { lineHeightFactor: 1.26 });
  if (signature) pdf.addImage(signature.data, "PNG", 168 - signatureWidth / 2, closingTop + 4, signatureWidth, signatureHeight);
  pdf.text(signatoryLines, 168, closingTop + signatureHeight + 10, { align: "center", lineHeightFactor: 1.26 });
  pdf.setFontSize(7.5);
  const footerLines: string[] = settings.footer_text ? pdf.splitTextToSize(settings.footer_text, 172) : [];
  const footerHeight = Math.max(7, footerLines.length * 3.2 + 3);
  const pages = pdf.getNumberOfPages();
  for (let page = 1; page <= pages; page += 1) {
    pdf.setPage(page);
    if (logo) {
      const logoWidth = Math.min(settings.logo_width_mm, 20 * logo.ratio);
      pdf.addImage(logo.data, "PNG", 15, 13, logoWidth, logoWidth / logo.ratio);
    }
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(20);
    pdf.setFontSize(Math.min(20, 20 * 100 / Math.max(100, pdf.getTextWidth(settings.title))));
    pdf.setTextColor(...NAVY);
    pdf.text(settings.title, 195, 24, { align: "right" });
    pdf.setDrawColor(...GOLD);
    pdf.setLineWidth(0.7);
    pdf.line(15, 37, 195, 37);
    pdf.setFont("helvetica", "normal");
    if (footerLines.length) {
      pdf.setFillColor(...NAVY);
      pdf.rect(15, 269, 180, footerHeight, "F");
      pdf.setTextColor(...colorRgb(settings.footer_text_color));
      pdf.setFontSize(7.5);
      pdf.text(footerLines, 105, 273, { align: "center", lineHeightFactor: 1.2 });
    }
    pdf.setTextColor(...NAVY);
    pdf.setFontSize(7);
    pdf.text(`${invoice.invoice_number}  |  Page ${page} of ${pages}`, 105, 290, { align: "center" });
  }
  return pdf;
}

export async function downloadInvoicePdf(invoice: Invoice): Promise<void> {
  const pdf = await createInvoicePdf(invoice);
  pdf.save(`${invoice.invoice_number.replace(/[^a-zA-Z0-9_-]/g, "_")}.pdf`);
}