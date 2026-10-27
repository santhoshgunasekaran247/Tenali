import type { InvoiceSettings } from "../types";

export const DEFAULT_INVOICE_SETTINGS: InvoiceSettings = {
  title: "TAX INVOICE",
  thank_you_note: "Thank you for letting us be a part of your celebration.",
  signatory_label: "Authorized Signatory",
  signatory_name: "",
  signatory_designation: "",
  signature_image: null,
  footer_text: "SOURCED WITH INTEGRITY \u2022 DELIVERED GLOBALLY.",
  primary_color: "#142b4a",
  accent_color: "#b88932",
  footer_text_color: "#ffffff",
  bill_to_label: "BILL TO",
  ship_to_label: "SHIP TO",
  amount_in_words_label: "Total in Words",
  logo_width_mm: 65,
  signature_width_mm: 34,
};