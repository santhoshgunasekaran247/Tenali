export type CancelKind = "invoice" | "purchase";

const rupees = (value: number) => `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** What cancelling a document will do, in the order the user should read it. */
export function cancellationEffects(kind: CancelKind, paid: number) {
  const effects = [kind === "invoice"
    ? "The invoice stays in the GST series, marked CANCELLED; its PDF shows CANCELLED. Billed stock returns to the store."
    : "The bill is marked CANCELLED. Received stock is removed from the store."];
  if (paid > 0) {
    effects.push(kind === "invoice"
      ? `${rupees(paid)} received will be reversed (nothing is deleted) and listed under Refund settlements as money to pay back to the customer.`
      : `${rupees(paid)} paid will be reversed (nothing is deleted) and listed under Refund settlements as money the vendor must return.`);
    effects.push("Confirm each refund there once the money has actually moved, choosing the account and mode used.");
  }
  return effects;
}

/** Double confirmation: a reason, explicit acknowledgement of any refund, and the document number typed back. */
export function canConfirmCancel({ reason, paid, acknowledged, typed, number }:
  { reason: string; paid: number; acknowledged: boolean; typed: string; number: string }) {
  return Boolean(reason.trim()) && (paid <= 0 || acknowledged) && typed.trim() === number.trim();
}

export const refundDirectionLabel = (direction: "PAY_CUSTOMER" | "RECEIVE_VENDOR") =>
  direction === "PAY_CUSTOMER" ? "Pay back to customer" : "Receive back from vendor";
