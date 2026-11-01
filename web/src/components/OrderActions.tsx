import { useEffect, useState } from "react";
import { accountRequest, paymentLabel, type ShopOrder } from "../features/shop";
import { api } from "../api";
import type { Account, Store } from "../types";

type Props = { order: ShopOrder; stores: Store[]; accounts: Account[]; locked: boolean; onDone: (message: string) => Promise<void>; onError: (message: string) => void };

/** Staff lifecycle actions for one online order; each call maps to a checkout-admin endpoint. */
export function OrderActions({ order, stores, accounts, locked, onDone, onError }: Props) {
  const [shipFrom, setShipFrom] = useState(order.ship_from_store_id || "");
  const [collect, setCollect] = useState({ account_id: "", payment_mode: "cash" });
  const [cancel, setCancel] = useState({ reason: "", refund_account_id: "" });
  const [decline, setDecline] = useState("");
  const [busy, setBusy] = useState(false);
  const stockStores = stores.filter(store => store.holds_stock && store.is_active);
  const online = stores.find(store => store.id === order.store_id);
  useEffect(() => { if (!shipFrom && online?.fulfilment_store_id) setShipFrom(online.fulfilment_store_id); }, [online?.fulfilment_store_id]);
  const run = async (path: string, body: unknown, message: string) => {
    setBusy(true);
    try { await accountRequest(`/orders/${order.id}/${path}`, { method: "POST", body: JSON.stringify(body ?? {}) }, "checkout-admin"); await onDone(message); }
    catch (failure) { onError(String(failure)); await onDone(""); }
    finally { setBusy(false); }
  };
  const disabled = locked || busy;
  const storeName = (id: string | null) => stores.find(store => store.id === id)?.code || "";
  const prepaidReady = order.payment_method !== "prepaid" || !!order.advance_transaction_id;
  return <div className="order-actions">
    <p className="checkout-fine-print">{paymentLabel(order.payment_method)} · {order.fulfilment_method === "pickup" ? `Pickup at ${storeName(order.pickup_store_id)}` : "Delivery"}{order.ship_from_store_id ? ` · Shipped from ${storeName(order.ship_from_store_id)}` : ""}{order.invoice_id ? " · Invoiced" : ""}</p>
    {order.review_reason ? <p role="alert" className="checkout-notice">{order.review_reason}</p> : null}
    {order.status === "cod_requested" ? <div className="shop-actions">
      <button className="btn" disabled={disabled} onClick={() => void run("approve-cod", {}, "Cash-on-delivery order approved; stock is now held at the warehouse.")}>Approve COD</button>
      <input aria-label="Decline reason" placeholder="Reason for declining" value={decline} onChange={event => setDecline(event.target.value)} />
      <button className="btn light" disabled={disabled} onClick={() => void run("decline-cod", { reason: decline || null }, "Cash-on-delivery request declined.")}>Decline</button>
    </div> : null}
    {order.payment_method === "prepaid" && order.razorpay_payment_id && order.review_reason?.startsWith("Advance not posted") ? <button className="btn light" disabled={disabled} onClick={() => void run("post-advance", {}, "Online payment advance posted.")}>Retry posting payment advance</button> : null}
    {["paid", "confirmed", "shipment_booked", "shipping_pending", "fulfilment_review"].includes(order.status) && order.payment_method !== "pay_at_pickup" && !order.invoice_id ? <div className="shop-actions">
      <label>Ship from<select value={shipFrom} onChange={event => setShipFrom(event.target.value)}>{stockStores.map(store => <option key={store.id} value={store.id}>{store.code} · {store.name}</option>)}</select></label>
      <button className="btn" disabled={disabled || !shipFrom || !prepaidReady} onClick={() => void run("dispatch", { ship_from_store_id: shipFrom }, "Dispatched: stock booked and invoice created.")}>Dispatch &amp; invoice</button>
    </div> : null}
    {order.fulfilment_method === "pickup" && ((order.payment_method === "prepaid" && order.status === "dispatched") || (order.payment_method === "pay_at_pickup" && order.status === "confirmed")) ? <button className="btn light" disabled={disabled} onClick={() => void run("ready", {}, "Marked ready for pickup.")}>Ready for pickup</button> : null}
    {order.fulfilment_method === "pickup" && ["confirmed", "ready_for_pickup", "dispatched"].includes(order.status) ? <div className="shop-actions">
      {order.payment_method === "pay_at_pickup" ? <>
        <label>Received into<select value={collect.account_id} onChange={event => setCollect({ ...collect, account_id: event.target.value })}><option value="">Account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label>
        <label>Mode<select value={collect.payment_mode} onChange={event => setCollect({ ...collect, payment_mode: event.target.value })}><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option><option value="bank">Bank</option></select></label>
      </> : null}
      <button className="btn" disabled={disabled || (order.payment_method === "pay_at_pickup" && !collect.account_id)} onClick={() => void run("collect", order.payment_method === "pay_at_pickup" ? collect : {}, order.payment_method === "pay_at_pickup" ? "Collected: invoice created in the shop's series." : "Handed over to the shopper.")}>Mark collected</button>
    </div> : null}
    {order.fulfilment_method === "delivery" && order.status === "dispatched" ? <button className="btn light" disabled={disabled} onClick={() => void run("delivered", {}, "Marked delivered.")}>Mark delivered</button> : null}
    {!order.invoice_id && !["cancelled", "refunded", "expired"].includes(order.status) ? <details><summary>Cancel order</summary><div className="shop-actions">
      <input aria-label="Cancellation reason" placeholder="Reason" value={cancel.reason} onChange={event => setCancel({ ...cancel, reason: event.target.value })} />
      {order.payment_method === "prepaid" && order.razorpay_payment_id ? <label>Refund from<select value={cancel.refund_account_id} onChange={event => setCancel({ ...cancel, refund_account_id: event.target.value })}><option value="">Clearing account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label> : null}
      <button className="btn light" disabled={disabled || !cancel.reason.trim()} onClick={() => void run("cancel", { reason: cancel.reason, refund_account_id: cancel.refund_account_id || null }, "Order cancelled.")}>Confirm cancellation</button>
    </div></details> : null}
    {order.invoice_id ? <p className="checkout-fine-print">To reverse an invoiced order, reverse its receipt and cancel the invoice from Billing; stock returns to the store that shipped it.</p> : null}
  </div>;
}

export function useStoresAndAccounts() {
  const [stores, setStores] = useState<Store[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  useEffect(() => {
    void api.stores(true).then(result => setStores(result.items)).catch(() => setStores([]));
    void api.accounts({ active_only: true }).then(result => setAccounts(result.items)).catch(() => setAccounts([]));
  }, []);
  return { stores, accounts };
}

