import { tenantFetch } from "./tenantTransport";

export type Shopper = { id: string; email: string; display_name: string; phone: string | null };
export type ShopItem = { product_id: string; variant_id: string | null; name: string; quantity: number; unit_paise: number };
export type DeliveryAddress = { name: string; phone: string; address: string; city: string; state: string; pincode: string; country: "India" };
export type OrderStatus = "awaiting_payment" | "paid" | "cod_requested" | "confirmed" | "fulfilment_review" | "shipping_pending" | "shipment_booked"
  | "dispatched" | "delivered" | "ready_for_pickup" | "collected" | "expired" | "cancelled" | "refunded";
export type PaymentMethod = "prepaid" | "cod" | "pay_at_pickup";
export type FulfilmentMethod = "delivery" | "pickup";
export type PickupStore = { id: string; code: string; name: string; address: string | null; pincode: string | null; whatsapp_number: string | null };
export type Availability = {
  disabled_reason?: string | null; online_store_ready?: boolean;
  enabled: boolean; gst_registered: boolean; shipping_paise: number | null; prepaid_enabled: boolean; cod_enabled: boolean; cod_limit: number | null;
  pickup_enabled: boolean; pickup_stores: PickupStore[]; whatsapp_number: string | null;
};
export type NearbyStore = { store_id: string; code: string; name: string; address: string | null; pincode: string | null; distance_km: number | null; availability: "available" | "few_left" | "unavailable"; whatsapp_number: string | null };
export type ShopOrder = {
  id: string;
  status: OrderStatus;
  channel: "web" | "whatsapp";
  payment_method: PaymentMethod;
  fulfilment_method: FulfilmentMethod;
  shipping_provider: "shiprocket" | "self";
  store_id: string | null;
  pickup_store_id: string | null;
  ship_from_store_id: string | null;
  invoice_id: string | null;
  advance_transaction_id: string | null;
  expires_at: string | null;
  approved_at: string | null;
  dispatched_at: string | null;
  delivered_at: string | null;
  ready_at: string | null;
  collected_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  review_reason: string | null;
  items: ShopItem[];
  address: DeliveryAddress;
  subtotal_paise: number;
  shipping_paise: number;
  total_paise: number;
  provider_key_id: string | null;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  shiprocket_order_id: number | null;
  shipment_id: number | null;
  awb: string | null;
  courier: string | null;
  shipping_error: string | null;
  created_at: string;
};
export function canVerifyPayment(order: Pick<ShopOrder, "status" | "payment_method" | "razorpay_order_id" | "razorpay_payment_id">): boolean {
  return (order.status === "awaiting_payment" || order.status === "expired" || order.status === "cancelled") &&
    order.payment_method === "prepaid" && Boolean(order.razorpay_order_id) && !order.razorpay_payment_id;
}
export type Quote = Pick<ShopOrder, "items" | "subtotal_paise" | "shipping_paise" | "total_paise"> & { pickup_store?: string | null };
export type PaymentResult = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string };
type RazorpayOptions = {
  key: string; amount: number; currency: "INR"; order_id: string; name: string;
  prefill: { email: string; name: string; contact: string };
  handler: (result: PaymentResult) => void; modal: { ondismiss: () => void };
};
type RazorpayInstance = { open: () => void; close: () => void; on: (event: "payment.failed", callback: () => void) => void };
declare global {
  interface Window { Razorpay?: new (options: RazorpayOptions) => RazorpayInstance }
}

function csrf(cookie: string) {
  const value = document.cookie.split("; ").find(entry => entry.startsWith(cookie + "="))?.slice(cookie.length + 1);
  return value ? decodeURIComponent(value) : "";
}

class ShopRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function accountRequest<T>(path: string, options?: RequestInit, realm: "shop" | "platform" | "checkout-admin" | "parties" = "shop"): Promise<T> {
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
    throw new ShopRequestError(message, response.status);
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

function paymentRequest(path: string, options: RequestInit, signal: AbortSignal): Promise<ShopOrder> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    const cleanup = () => { clearTimeout(timer); signal.removeEventListener("abort", cancel); };
    const cancel = () => { cleanup(); controller.abort(); reject(new Error("Payment verification cancelled.")); };
    const timer = setTimeout(() => {
      cleanup(); controller.abort();
      reject(new Error("Payment verification timed out. Check My Orders before paying again."));
    }, 30_000);
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) { cancel(); return; }
    accountRequest<ShopOrder>(path, { ...options, signal: controller.signal }).then(
      result => { cleanup(); resolve(result); },
      error => { cleanup(); reject(error); },
    );
  });
}

export function payOrder(order: ShopOrder, shopper: Shopper, storeName: string, signal?: AbortSignal): Promise<ShopOrder | null> {
  return new Promise((resolve, reject) => {
    if (!window.Razorpay) { reject(new Error("Razorpay checkout is unavailable.")); return; }
    if (!order.provider_key_id || !order.razorpay_order_id) { reject(new Error("This order has no Razorpay checkout. Check My Orders.")); return; }
    const lifetime = new AbortController();
    let checkout: RazorpayInstance | undefined;
    let finished = false, verifying = false;
    let pollTimer: ReturnType<typeof setTimeout>;
    const finish = (verified: ShopOrder | null, error?: Error) => {
      if (finished) return;
      finished = true;
      clearTimeout(deadline); clearTimeout(pollTimer);
      signal?.removeEventListener("abort", cancel);
      lifetime.abort();
      if (error) reject(error); else resolve(verified);
      checkout?.close();
    };
    const cancel = () => finish(null, new Error("Payment verification cancelled. Check My Orders before paying again."));
    const verified = (value: ShopOrder) => value.id === order.id && value.payment_method === "prepaid"
      && !!value.razorpay_payment_id && ["paid", "fulfilment_review", "confirmed", "shipping_pending",
        "shipment_booked", "dispatched", "delivered", "ready_for_pickup", "collected"].includes(value.status);
    const recover = async (dismissed: boolean) => {
      try {
        const value = await paymentRequest(`/orders/${order.id}/reconcile-payment`, { method: "POST" }, lifetime.signal);
        if (!verified(value)) throw new Error("Payment has not been verified. Check My Orders before paying again.");
        finish(value);
      } catch (failure) {
        if (dismissed && failure instanceof ShopRequestError && failure.status === 409) finish(null);
        else finish(null, new Error(`${failure instanceof Error ? failure.message : String(failure)} Check My Orders before paying again.`));
      }
    };
    const poll = async () => {
      try {
        const value = await paymentRequest(`/orders/${order.id}`, {}, lifetime.signal);
        if (verified(value)) { finish(value); return; }
      } catch (failure) {
        if (finished) return;
        console.warn("Unable to refresh payment status; checkout will attempt server-side reconciliation.", failure);
      }
      if (!finished) pollTimer = setTimeout(() => void poll(), 3000);
    };
    const deadline = setTimeout(() => {
      if (verifying || finished) return;
      verifying = true;
      void recover(false);
    }, 180_000);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) { cancel(); return; }
    try {
      checkout = new window.Razorpay({
        key: order.provider_key_id, amount: order.total_paise, currency: "INR", order_id: order.razorpay_order_id,
        name: storeName, prefill: { email: shopper.email, name: shopper.display_name, contact: order.address.phone },
        handler: result => {
          if (finished || verifying) return;
          verifying = true; clearTimeout(deadline);
          void paymentRequest(`/orders/${order.id}/confirm`, { method: "POST", body: JSON.stringify(result) }, lifetime.signal)
            .then(value => {
              if (!verified(value)) throw new Error("Payment has not been verified.");
              finish(value);
            }).catch(failure => {
              if (!finished) {
                console.warn("Payment callback confirmation did not complete; checking captured payment with the server.", failure);
                void recover(false);
              }
            });
        },
        modal: { ondismiss: () => {
          if (finished || verifying) return;
          verifying = true; clearTimeout(deadline);
          void recover(true);
        } },
      });
      checkout.on("payment.failed", () => finish(null, new Error("Payment failed. Check My Orders and your bank status before trying again.")));
      pollTimer = setTimeout(() => void poll(), 3000);
      checkout.open();
    } catch (failure) {
      finish(null, failure instanceof Error ? failure : new Error(String(failure)));
    }
  });
}

export const rupees = (paise: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(paise / 100);
export const orderStatus = (status: ShopOrder["status"]) => ({
  awaiting_payment: "Awaiting payment",
  paid: "Payment verified - awaiting dispatch",
  cod_requested: "Cash on delivery requested - awaiting store approval",
  confirmed: "Confirmed - being prepared",
  fulfilment_review: "Store review required; contact the store",
  shipping_pending: "Shipment submission pending reconciliation",
  shipment_booked: "Submitted to Shiprocket",
  dispatched: "Dispatched - invoice issued",
  delivered: "Delivered",
  ready_for_pickup: "Ready for pickup at the store",
  collected: "Collected",
  expired: "Expired - stock released",
  cancelled: "Cancelled",
  refunded: "Cancelled and refunded",
})[status] || status;
export const paymentLabel = (method: PaymentMethod) => ({ prepaid: "Paid online", cod: "Cash on delivery", pay_at_pickup: "Pay at pickup" })[method];
