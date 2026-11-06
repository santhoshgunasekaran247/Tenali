import type { Invoice, InvoiceLineInput } from "../types";

/** Text stamped on a cancelled invoice's PDF, or null while the invoice is active. */
export function cancellationStamp(invoice: Pick<Invoice, "status" | "cancelled_at" | "cancellation_reason">) {
  if (invoice.status !== "CANCELLED") return null;
  const when = invoice.cancelled_at
    ? new Date(`${invoice.cancelled_at.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
    : "";
  const reason = (invoice.cancellation_reason || "").trim();
  return { watermark: "CANCELLED", detail: `Cancelled${when ? ` on ${when}` : ""}${reason ? ` - ${reason.length > 90 ? `${reason.slice(0, 87)}...` : reason}` : ""}` };
}

/** Form values for a corrected invoice copied from a cancelled one. The new invoice gets a fresh number. */
export function reissueInvoice(invoice: Invoice) {
  const document = invoice.document_data;
  const lines: InvoiceLineInput[] = (document?.lines || []).map(line => ({
    product_id: line.product_id || null, variant_id: line.variant_id || null, description: line.description, hsn: line.hsn,
    quantity: Number(line.quantity), rate: Number(line.rate), gst_rate: Number(line.gst_rate),
    ...(line.price_includes_gst != null ? { price_includes_gst: line.price_includes_gst } : {}),
  }));
  const shipping = document?.ship_to;
  const sameShipping = !shipping || (shipping.name === document?.bill_to.name && shipping.address === document?.bill_to.address);
  return {
    form: {
      customer_party_id: invoice.customer_party_id,
      billing_address: document?.bill_to.address || "",
      shipping_name: sameShipping ? "" : shipping?.name || "",
      shipping_address: sameShipping ? "" : shipping?.address || "",
      place_of_supply: document?.place_of_supply || "",
      notes: `Reissue of cancelled invoice ${invoice.invoice_number}`,
    },
    lines,
    sameShipping,
  };
}
