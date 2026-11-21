import { useEffect, useState } from "react";
import { accountRequest, paymentLabel, rupees, type ShopOrder } from "../features/shop";
import { api } from "../api";
import type { Account, Store } from "../types";
import { Link } from "react-router-dom";

type Props = { order: ShopOrder; stores: Store[]; accounts: Account[]; locked: boolean; onDone: (message: string) => Promise<void>; onError: (message: string) => void };

export type PackageSize = { weight: string; length: string; width: string; height: string };
export const emptyPackage: PackageSize = { weight: "", length: "", width: "", height: "" };

export const SHIPROCKET_UNCERTAIN = ["Provider response uncertain", "Shiprocket submission in progress"];

/** Which Shiprocket actions apply; orders dispatched before Shiprocket submission can still be submitted or recovered. */
export function shiprocketActions(order: ShopOrder) {
  const applies = order.shipping_provider === "shiprocket" && order.fulfilment_method === "delivery";
  const testPayment = (order.provider_key_id || "").startsWith("rzp_test_");
  const ready = (order.status === "paid" && order.payment_method === "prepaid") || (order.status === "confirmed" && order.payment_method === "cod");
  const late = ["dispatched", "delivered"].includes(order.status) && !order.shiprocket_order_id && ["prepaid", "cod"].includes(order.payment_method);
  const uncertain = SHIPROCKET_UNCERTAIN.some(marker => (order.shipping_error || "").startsWith(marker));
  return {
    applies,
    testPayment,
    canSubmit: applies && !testPayment && (ready || (late && !uncertain)),
    canRecover: applies && (["shipping_pending", "shipment_booked"].includes(order.status) || late || (order.status === "dispatched" && !order.awb)),
    // Staff may release an unconfirmed submission only after checking it does not exist in Shiprocket.
    canRelease: applies && !order.shiprocket_order_id && (order.status === "shipping_pending" || (late && uncertain)),
  };
}

type ShiprocketProps = { order: ShopOrder; pkg: PackageSize; reconcileId: string; locked: boolean;
  onPackage: (pkg: PackageSize) => void; onReconcileId: (value: string) => void; onSubmit: () => void; onRecover: () => void; onRelease?: () => void };

export function ShiprocketPanel({ order, pkg, reconcileId, locked, onPackage, onReconcileId, onSubmit, onRecover, onRelease }: ShiprocketProps) {
  const { applies, testPayment, canSubmit, canRecover, canRelease } = shiprocketActions(order);
  if (!applies) return null;
  const packageValid = Object.values(pkg).every(value => Number(value) > 0);
  return <section className="order-action-panel order-shiprocket-panel" aria-label="Shiprocket shipment"><h4>Shiprocket shipment</h4>
    {order.shiprocket_order_id ? <dl className="order-shiprocket-facts">
      <div><dt>Shiprocket order</dt><dd>{order.shiprocket_order_id}</dd></div>
      <div><dt>Shipment</dt><dd>{order.shipment_id || "-"}</dd></div>
      <div><dt>AWB</dt><dd>{order.awb || "Not yet assigned - syncs from Shiprocket automatically"}</dd></div>
      {order.courier ? <div><dt>Courier</dt><dd>{order.courier}</dd></div> : null}
    </dl> : <p className="order-action-help">{testPayment ? "Razorpay test payment - this order cannot create a real Shiprocket shipment."
      : order.status === "delivered" ? "This order was marked delivered but was never submitted to Shiprocket. Submit it now (it returns to dispatched until delivery), or recover it if it already exists in Shiprocket."
      : order.status === "dispatched" ? "This order was dispatched before it was submitted to Shiprocket. Submit it now, or recover it if it already exists in Shiprocket."
      : "Not yet submitted. Enter the packed size and submit; Dispatch & invoice unlocks once Shiprocket confirms the order."}</p>}
    {order.shipping_error ? <p role="alert" className="ops-error">{order.shipping_error}</p> : null}
    {canSubmit ? <div className="shop-actions order-package-fields">
      {(Object.keys(pkg) as (keyof PackageSize)[]).map(key => <label key={key}>{key[0].toUpperCase() + key.slice(1)} ({key === "weight" ? "kg" : "cm"})<input type="number" min={0.001} step="any" value={pkg[key]} onChange={event => onPackage({ ...pkg, [key]: event.target.value })} /></label>)}
      <button className="btn" disabled={locked || !packageValid} onClick={onSubmit}>Submit packed order to Shiprocket</button>
    </div> : null}
    {canRecover ? <details className="order-shiprocket-recovery"><summary>Recover shipment / update tracking</summary><p>If a submission response was lost, find the order in Shiprocket using the Tenali order ID and enter its Shiprocket order ID. Do not create another shipment.</p><div className="shop-actions">
      <label>Shiprocket order ID<input inputMode="numeric" value={reconcileId} onChange={event => onReconcileId(event.target.value)} /></label>
      <button className="btn light" disabled={locked || !/^[1-9][0-9]*$/.test(reconcileId)} onClick={onRecover}>Recover shipment / update tracking</button>
    </div>
      {canRelease && onRelease ? <div className="shop-actions"><p>Searched Shiprocket and this Tenali order ID is not there? Release it so it can be submitted again.</p>
        <button className="btn light" disabled={locked} onClick={() => { if (window.confirm("Only continue if this Tenali order ID does not exist in Shiprocket. Submitting again when it already exists creates a duplicate shipment.")) onRelease(); }}>Not in Shiprocket: allow resubmission</button></div> : null}
    </details> : null}
  </section>;
}

/** Staff lifecycle actions for one online order; each call maps to a checkout-admin endpoint. */
export function OrderActions({ order, stores, accounts, locked, onDone, onError }: Props) {
  const [shipFrom, setShipFrom] = useState(order.ship_from_store_id || "");
  const [collect, setCollect] = useState({ account_id: "", payment_mode: "cash" });
  const [cancel, setCancel] = useState({ reason: "", refund_account_id: "", refund_confirmed: false, refund_reference: "" });
  const [decline, setDecline] = useState("");
  const [tracking, setTracking] = useState({ courier: order.courier || "", awb: order.awb || "" });
  const [busy, setBusy] = useState(false);
  const stockStores = stores.filter(store => store.holds_stock && store.is_active);
  const online = stores.find(store => store.id === order.store_id);
  useEffect(() => { if (!shipFrom && online?.fulfilment_store_id) setShipFrom(online.fulfilment_store_id); }, [online?.fulfilment_store_id]);
  const run = async (path: string, body: unknown, message: string) => {
    setBusy(true); onError("");
    try { await accountRequest(`/orders/${order.id}/${path}`, { method: "POST", body: JSON.stringify(body ?? {}) }, "checkout-admin"); await onDone(message); }
    catch (failure) {
      onError(failure instanceof Error ? failure.message : String(failure));
      try { await onDone(""); }
      catch (refreshFailure) { onError(`${failure instanceof Error ? failure.message : String(failure)} Refresh failed: ${String(refreshFailure)}`); }
    }
    finally { setBusy(false); }
  };
  const disabled = locked || busy;
  const storeName = (id: string | null) => stores.find(store => store.id === id)?.code || "";
  const prepaidReady = order.payment_method !== "prepaid" || !!order.advance_transaction_id;
  const capturedPayment = order.payment_method === "prepaid" && !!order.razorpay_payment_id;
  const refundReady = !capturedPayment || (!!order.advance_transaction_id && !!cancel.refund_account_id &&
    cancel.refund_confirmed && /^rfnd_[A-Za-z0-9]+$/.test(cancel.refund_reference.trim()));
  const awaitingShiprocket = order.fulfilment_method === "delivery" && order.shipping_provider === "shiprocket" && !order.shiprocket_order_id;
  const dispatchReady = prepaidReady && !awaitingShiprocket;
  return <div className="order-actions">
    <p className="checkout-fine-print">{paymentLabel(order.payment_method)} · {order.fulfilment_method === "pickup" ? `Pickup at ${storeName(order.pickup_store_id)}` : order.shipping_provider === "self" ? "Self-shipping / own courier" : "Shiprocket delivery"}{order.ship_from_store_id ? ` · Shipped from ${storeName(order.ship_from_store_id)}` : ""}{order.invoice_id ? " · Invoiced" : ""}</p>
    {order.review_reason ? <p role="alert" className="checkout-notice">{order.review_reason}</p> : null}
    {order.status === "cod_requested" ? <section className="order-action-panel"><h4>Cash-on-delivery approval</h4><div className="shop-actions">
      <button className="btn" disabled={disabled} onClick={() => void run("approve-cod", {}, "Cash-on-delivery order approved; stock is now held at the warehouse.")}>Approve COD</button>
      <label>Decline reason<input placeholder="Reason for declining" value={decline} onChange={event => setDecline(event.target.value)} /></label>
      <button className="btn light" disabled={disabled} onClick={() => void run("decline-cod", { reason: decline || null }, "Cash-on-delivery request declined.")}>Decline</button>
    </div></section> : null}
    {order.payment_method === "prepaid" && order.razorpay_payment_id && !order.advance_transaction_id && !["cancelled", "refunded"].includes(order.status) ? <section className="order-action-panel"><h4>Record payment advance</h4><p>The payment is verified. Record it in the ledger before dispatching. This does not charge the shopper again.</p><div className="shop-actions"><Link className="ops-inline-link" to="/portal/stores">Set settlement account in Stores</Link><button className="btn light" disabled={disabled} onClick={() => void run("post-advance", {}, "Online payment advance posted.")}>Retry posting payment advance</button></div></section> : null}
    {["paid", "confirmed", "shipment_booked", "shipping_pending", "fulfilment_review"].includes(order.status) && order.payment_method !== "pay_at_pickup" && !order.invoice_id ? <section className="order-action-panel"><h4>Dispatch &amp; invoice</h4><div className="shop-actions">
      <label>Ship from<select disabled={disabled} value={shipFrom} onChange={event => setShipFrom(event.target.value)}><option value="">Choose a warehouse / shop</option>{stockStores.map(store => <option key={store.id} value={store.id}>{store.code} · {store.name}</option>)}</select></label>
      {order.status === "fulfilment_review" && awaitingShiprocket ? <button className="btn light" disabled={disabled || !shipFrom || !prepaidReady} onClick={() => void run("resolve-fulfilment", { ship_from_store_id: shipFrom }, "Stock review resolved. The order can now be submitted for shipping.")}>Resolve stock review</button> : null}
      {order.fulfilment_method === "delivery" && order.shipping_provider === "self" ? <>
        <label>Courier / delivery service (optional)<input maxLength={80} placeholder="Own delivery or courier name" value={tracking.courier} onChange={event => setTracking({ ...tracking, courier: event.target.value })} /></label>
        <label>Tracking / AWB number (optional)<input maxLength={120} value={tracking.awb} onChange={event => setTracking({ ...tracking, awb: event.target.value })} /></label>
      </> : null}
      <button className="btn" disabled={disabled || !shipFrom || !dispatchReady} onClick={() => void run("dispatch", {
        ship_from_store_id: shipFrom,
        ...(order.fulfilment_method === "delivery" && order.shipping_provider === "self" ? { courier: tracking.courier.trim() || null, awb: tracking.awb.trim() || null } : {}),
      }, "Dispatched: stock booked and invoice created.")}>Dispatch &amp; invoice</button>
    </div>{!prepaidReady ? <p className="order-action-help">Post the verified payment advance above to enable dispatch.</p> : awaitingShiprocket && order.status === "fulfilment_review" ? <p className="order-action-help">Choose the ship-from store and resolve the stock review before submitting to Shiprocket.</p> : awaitingShiprocket ? <p className="order-action-help">Submit the packed order to Shiprocket above first. Dispatch &amp; invoice unlocks once Shiprocket confirms the order.</p> : null}</section> : null}
    {order.fulfilment_method === "pickup" && ((order.payment_method === "prepaid" && order.status === "dispatched") || (order.payment_method === "pay_at_pickup" && order.status === "confirmed")) ? <button className="btn light" disabled={disabled} onClick={() => void run("ready", {}, "Marked ready for pickup.")}>Ready for pickup</button> : null}
    {order.fulfilment_method === "pickup" && ["confirmed", "ready_for_pickup", "dispatched"].includes(order.status) ? <section className="order-action-panel"><h4>Shopper collection</h4><div className="shop-actions">
      {order.payment_method === "pay_at_pickup" ? <>
        <label>Received into<select value={collect.account_id} onChange={event => setCollect({ ...collect, account_id: event.target.value })}><option value="">Account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label>
        <label>Mode<select value={collect.payment_mode} onChange={event => setCollect({ ...collect, payment_mode: event.target.value })}><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option><option value="bank">Bank</option></select></label>
      </> : null}
      <button className="btn" disabled={disabled || (order.payment_method === "pay_at_pickup" && !collect.account_id)} onClick={() => void run("collect", order.payment_method === "pay_at_pickup" ? collect : {}, order.payment_method === "pay_at_pickup" ? "Collected: invoice created in the shop's series." : "Handed over to the shopper.")}>Mark collected</button>
    </div></section> : null}
    {order.fulfilment_method === "delivery" && order.status === "dispatched" && !awaitingShiprocket ? <button className="btn light" disabled={disabled} onClick={() => {
      if (typeof window !== "undefined" && !window.confirm("Mark this order as delivered to the shopper?")) return;
      void run("delivered", {}, "Marked delivered.");
    }}>Mark delivered</button> : null}
    {!order.invoice_id && !order.shiprocket_order_id && !["cancelled", "refunded", "expired", "shipping_pending", "shipment_booked", "dispatched", "delivered"].includes(order.status) ? <details className="order-cancel-panel"><summary>Cancel order</summary><div className="shop-actions">
      {order.payment_method === "prepaid" && !order.razorpay_payment_id ? <p>Cancellation releases stock but cannot stop an in-flight payment. Verify any later payment before placing another order.</p> : null}
      <label className="order-cancel-reason">Cancellation reason<input maxLength={500} placeholder="Why is this order being cancelled?" value={cancel.reason} onChange={event => setCancel({ ...cancel, reason: event.target.value })} /></label>
      {capturedPayment && order.advance_transaction_id ? <>
        <p>This records a completed external refund; it does not initiate a refund. Complete and verify a full refund of {rupees(order.total_paise)} in Razorpay first. Partial refunds cannot be recorded here.</p>
        <label>Refund from<select value={cancel.refund_account_id} onChange={event => setCancel({ ...cancel, refund_account_id: event.target.value })}><option value="">Choose account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label>
        <label>Razorpay refund ID<input maxLength={120} placeholder="rfnd_..." value={cancel.refund_reference} onChange={event => setCancel({ ...cancel, refund_reference: event.target.value })} /></label>
        <label><input type="checkbox" checked={cancel.refund_confirmed} onChange={event => setCancel({ ...cancel, refund_confirmed: event.target.checked })} /> I completed and verified the full refund with Razorpay</label>
      </> : capturedPayment ? <p>Post the verified payment advance above before recording a refund and cancelling this order.</p> : null}
      <button className="btn light" disabled={disabled || !cancel.reason.trim() || !refundReady} onClick={() => void run("cancel", { reason: cancel.reason, refund_account_id: cancel.refund_account_id || null,
        refund_confirmed: capturedPayment && cancel.refund_confirmed, refund_reference: capturedPayment ? cancel.refund_reference.trim() : null }, capturedPayment ? "Completed refund recorded and order cancelled." : "Order cancelled.")}>Confirm cancellation</button>
    </div></details> : null}
    {!order.invoice_id && (order.shiprocket_order_id || ["shipping_pending", "shipment_booked", "dispatched", "delivered"].includes(order.status)) ? <p className="checkout-fine-print">This order has a shipment or dispatch in progress. Resolve it with the shipping provider and support before cancelling or recording a refund.</p> : null}
    {order.invoice_id ? <p className="checkout-fine-print">To reverse an invoiced order, reverse its receipt and cancel the invoice from Billing; stock returns to the store that shipped it.</p> : null}
    {order.shipping_provider === "self" && (order.courier || order.awb) ? <p className="checkout-fine-print">Delivery: {order.courier || "Own courier"}{order.awb ? ` · Tracking: ${order.awb}` : ""}</p> : null}
  </div>;
}

export function useStoresAndAccounts() {
  const [stores, setStores] = useState<Store[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [lookupError, setLookupError] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([api.stores(true), api.accounts({ active_only: true })])
      .then(([storeList, accountList]) => { if (active) { setStores(storeList.items); setAccounts(accountList.items); setLookupError(""); } })
      .catch(failure => { if (active) setLookupError(failure instanceof Error ? failure.message : String(failure)); });
    return () => { active = false; };
  }, []);
  return { stores, accounts, lookupError };
}
