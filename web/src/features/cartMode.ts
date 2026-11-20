/**
 * "buy": the cart is a shopping cart paid online.
 * "enquiry": online payment is off but WhatsApp enquiries are on, so the cart becomes an enquiry list sent on WhatsApp.
 * "none": neither is available.
 */
export type CartMode = "buy" | "enquiry" | "none";

export function cartMode(checkoutEnabled: boolean, whatsappPhone?: string | null): CartMode {
  return checkoutEnabled ? "buy" : whatsappPhone && whatsappPhone.replace(/\D/g, "") ? "enquiry" : "none";
}

export function cartWords(mode: CartMode | null) {
  return mode === "enquiry"
    ? { list: "Enquiry list", title: "Your Enquiry List", add: "Add to enquiry", added: "added to your enquiry list", inList: "In enquiry", view: "View enquiry list" }
    : { list: "Cart", title: "Your Cart", add: "Add to Cart", added: "added to your cart", inList: "In cart", view: "View cart" };
}

export type EnquiryLine = { name: string; option?: string | null; quantity: number; price?: string | null };

/**
 * WhatsApp text listing every enquiry line with its quantity, laid out for reading on a phone:
 * WhatsApp *bold* headings, one product per block and blank lines between sections. It says plainly that it is not an order.
 */
export function enquiryMessage(storeName: string, lines: EnquiryLine[]): string {
  const inr = (value: number) => `\u20b9${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
  const units = lines.reduce((total, line) => total + line.quantity, 0);
  let listed = 0;
  const items = lines.map((line, index) => {
    const unit = Number(line.price);
    const priced = Number.isFinite(unit) && unit > 0;
    if (priced) listed += unit * line.quantity;
    const detail = [`   Qty: *${line.quantity}*`];
    if (line.option) detail.unshift(`   Option: ${line.option}`);
    if (priced) detail.push(`   Listed: ${inr(unit)} each`);
    return [`${index + 1}. *${line.name}*`, ...detail].join("\n");
  });
  const summary = [`Products: ${lines.length}`, `Total units: ${units}`];
  if (listed > 0) summary.push(`Listed value: ${inr(listed)}`);
  return [
    `Hello ${storeName},`,
    "I would like a quote for the following items.",
    "",
    "*Enquiry list*",
    items.join("\n\n"),
    "",
    "*Summary*",
    summary.join("\n"),
    "",
    "Please share your best price, availability and delivery details.",
    "_This is an enquiry, not an order._",
  ].join("\n");
}
export function enquiryWhatsappLink(phone: string, message: string): string {
  return `https://wa.me/${phone.replace(/\D/g, "")}?text=${encodeURIComponent(message)}`;
}
