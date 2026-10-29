import { tenantFetch } from "./tenantTransport";

export type Shopper = { id: string; email: string; display_name: string };
export type ShopItem = { product_id: string; variant_id: string | null; name: string; quantity: number; unit_paise: number };
export type DeliveryAddress = { name: string; phone: string; address: string; city: string; state: string; pincode: string; country: "India" };
export type ShopOrder = {
  id: string;
  status: "awaiting_payment" | "paid" | "payment_review" | "shipping_pending" | "shipment_booked";
  items: ShopItem[];
  address: DeliveryAddress;
  subtotal_paise: number;
  shipping_paise: number;
  total_paise: number;
  provider_key_id: string;
  razorpay_order_id: string;
  razorpay_payment_id: string | null;
  shiprocket_order_id: number | null;
  shipment_id: number | null;
  awb: string | null;
  courier: string | null;
  shipping_error: string | null;
  created_at: string;
};
export type Quote = Pick<ShopOrder, "items" | "subtotal_paise" | "shipping_paise" | "total_paise">;
export type PaymentResult = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string };
type RazorpayOptions = {
  key: string; amount: number; currency: "INR"; order_id: string; name: string;
  prefill: { email: string; name: string; contact: string };
  handler: (result: PaymentResult) => void; modal: { ondismiss: () => void };
};
type RazorpayInstance = { open: () => void; on: (event: "payment.failed", callback: () => void) => void };
declare global {
  interface Window { Razorpay?: new (options: RazorpayOptions) => RazorpayInstance }
}

function csrf(cookie: string) {
  const value = document.cookie.split("; ").find(entry => entry.startsWith(cookie + "="))?.slice(cookie.length + 1);
  return value ? decodeURIComponent(value) : "";
}

export async function accountRequest<T>(path: string, options?: RequestInit, realm: "shop" | "platform" | "checkout-admin" = "shop"): Promise<T> {
  const response = await tenantFetch(`/api/${realm}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf(realm === "platform" ? "tenali_platform_csrf" : realm === "shop" ? "tenali_shopper_csrf" : "tenali_csrf"),
      ...(realm === "platform" ? { "X-Tenant-Slug": "" } : {}),
      ...options?.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const message = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail)
      ? body.detail.map((entry: { msg?: string }) => entry.msg || "Invalid input").join(" ") : "Unable to complete this request.";
    throw new Error(message);
  }
  return body as T;
}

export async function shopperSession(): Promise<Shopper | null> {
  const response = await tenantFetch("/api/shop/session");
  if (response.status === 401) return null;
  if (!response.ok) {
    const body = await response.json();
    throw new Error(typeof body.detail === "string" ? body.detail : "Unable to load shopper session");
  }
  return response.json();
}

let razorpayScript: Promise<void> | undefined;
export function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (razorpayScript) return razorpayScript;
  razorpayScript = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => {
      if (window.Razorpay) resolve();
      else { script.remove(); razorpayScript = undefined; reject(new Error("Razorpay checkout did not load.")); }
    };
    script.onerror = () => { script.remove(); razorpayScript = undefined; reject(new Error("Unable to load Razorpay. Check your connection.")); };
    document.head.appendChild(script);
  });
  return razorpayScript;
}

export function payOrder(order: ShopOrder, shopper: Shopper, storeName: string): Promise<PaymentResult | null> {
  return new Promise((resolve, reject) => {
    if (!window.Razorpay) { reject(new Error("Razorpay checkout is unavailable.")); return; }
    const checkout = new window.Razorpay({
      key: order.provider_key_id, amount: order.total_paise, currency: "INR", order_id: order.razorpay_order_id,
      name: storeName, prefill: { email: shopper.email, name: shopper.display_name, contact: order.address.phone },
      handler: resolve, modal: { ondismiss: () => resolve(null) },
    });
    checkout.on("payment.failed", () => reject(new Error("Payment failed. Check your orders and bank status before trying again.")));
    checkout.open();
  });
}

export const rupees = (paise: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(paise / 100);
export const orderStatus = (status: ShopOrder["status"]) => ({
  awaiting_payment: "Awaiting payment",
  paid: "Payment verified - awaiting fulfillment",
  payment_review: "Payment received - store review required; contact the store",
  shipping_pending: "Shipment submission pending reconciliation",
  shipment_booked: "Submitted to Shiprocket",
})[status];
