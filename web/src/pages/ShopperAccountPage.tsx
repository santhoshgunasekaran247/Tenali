import { FormEvent, useEffect, useState } from "react";
import { FederatedShopperLogin } from "../components/FederatedShopperLogin";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../features/auth";
import { accountRequest, orderStatus, paymentLabel, payOrder, loadRazorpay, rupees, shopperSession, type Shopper, type ShopOrder } from "../features/shop";
import { useCart } from "../features/cart";
import { clearSocialLogin } from "../features/shopperFederation";

export function ShopperAccountPage({ register = false }: { register?: boolean }) {
  const { storefront, loading } = useAuth();
  const cart = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [shopper, setShopper] = useState<Shopper | null>(null);
  const [checking, setChecking] = useState(true);
  const [orders, setOrders] = useState<ShopOrder[]>([]);
  const [offset, setOffset] = useState(0);
  const [profile, setProfile] = useState({ display_name: "", phone: "" });
  useEffect(() => {
    if (shopper) setProfile({ display_name: shopper.display_name, phone: shopper.phone || "" });
  }, [shopper]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (loading) return;
    if (!storefront) { setChecking(false); return; }
    let active = true;
    shopperSession().then(result => { if (active) setShopper(result); })
      .catch(failure => { if (active) setError(String(failure)); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [loading, storefront?.id]);
  const refreshOrders = async () => {
    const result = await accountRequest<{ items: ShopOrder[] }>(`/orders?offset=${offset}`);
    setOrders(result.items);
  };
  useEffect(() => {
    if (shopper) void refreshOrders().catch(failure => setError(String(failure)));
  }, [shopper?.id, offset]);
  const signedIn = (result: Shopper) => {
    setShopper(result);
    const next = new URLSearchParams(location.search).get("next");
    if (next === "/checkout" || next?.startsWith("/checkout?")) navigate(next, { replace: true });
    else navigate("/account", { replace: true });
  };
  const pay = async (order: ShopOrder) => {
    if (!shopper || !storefront) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await loadRazorpay();
      const result = await payOrder(order, shopper, storefront.company_name);
      if (result) {
        await accountRequest(`/orders/${order.id}/confirm`, { method: "POST", body: JSON.stringify(result) });
        cart.removePurchased(order.items);
        setMessage("Payment status updated.");
      } else setMessage("Checkout closed. An unfinished checkout does not confirm payment.");
      await refreshOrders();
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  if (loading || checking) return <main className="loading">Loading shopper account...</main>;
  if (!storefront) return <main className="access-page"><section className="access-panel"><h1>Shopper Account</h1><p>Open the store&apos;s workspace address or verified domain to sign in. Shopper accounts are separate for every store.</p><Link to="/login">Workspace staff sign in</Link></section></main>;
  return <main className="shop-account-page">
    <header className="shop-account-heading"><Link to="/">Back to Storefront</Link><h1>{shopper ? "My Shopper Account" : register ? "Create Shopper Account" : "Shopper Sign In"}</h1><p>{storefront.company_name} · Separate from staff and other stores.</p></header>
    <div className="shop-account-content">
      {error ? <p className="ops-error" role="alert">{error}</p> : null}
      {message ? <p role="status">{message}</p> : null}
      {!shopper ? <><FederatedShopperLogin key={storefront.id} onSignedIn={signedIn} /><Link to="/login">Workspace staff sign in</Link></> : <>
        <section className="ops-card"><h2>{shopper.display_name}</h2><p>{shopper.email}</p><p>Phone: {shopper.phone || "Not recorded"} (unverified)</p>
          <details><summary>Edit contact details</summary><form className="ops-form" onSubmit={(event: FormEvent) => {
            event.preventDefault(); setBusy(true); setError(""); setMessage("");
            void accountRequest<Shopper>("/profile", { method: "POST", body: JSON.stringify(profile) })
              .then(result => { setShopper(result); setMessage("Contact details updated. Your phone is unverified; no customer records were merged."); })
              .catch(failure => setError(String(failure))).finally(() => setBusy(false));
          }}><label>Your name<input required maxLength={150} value={profile.display_name} onChange={event => setProfile({ ...profile, display_name: event.target.value })} /></label>
            <label>Phone number<input required type="tel" maxLength={40} value={profile.phone} onChange={event => setProfile({ ...profile, phone: event.target.value })} /></label>
            <button className="btn light" disabled={busy}>Save contact details</button></form></details>
          <button className="btn light" disabled={busy} onClick={() => {
            setBusy(true); setError("");
            void accountRequest("/logout", { method: "POST" }).then(async () => {
              setShopper(null); setOrders([]);
              await clearSocialLogin();
            })
              .catch(failure => setError(String(failure))).finally(() => setBusy(false));
          }}>Sign Out of Store</button>
          <p>Manage sign-in security with your social login provider.</p>
        </section>
        <section><h2>My Orders</h2><button className="ops-link-btn" disabled={busy} onClick={() => void refreshOrders().catch(failure => setError(String(failure)))}>Refresh Payment &amp; Shipping Status</button>
          {!orders.length ? <p>No orders on this page.</p> : null}
          {orders.map(order => <article className="ops-card shop-order" key={order.id}><h3>Order {order.id}</h3><p>{orderStatus(order.status)} · {paymentLabel(order.payment_method)}{order.fulfilment_method === "pickup" ? " · Store pickup" : ""}</p>{order.review_reason && order.status === "fulfilment_review" ? <p className="checkout-notice">The store is reviewing this order.</p> : null}<ul>{order.items.map(item => <li key={`${item.product_id}:${item.variant_id}`}>{item.name} × {item.quantity} · {rupees(item.unit_paise * item.quantity)}</li>)}</ul><p>{order.shipping_paise ? `Shipping ${rupees(order.shipping_paise)} · ` : ""}Total <strong>{rupees(order.total_paise)}</strong></p>
            {order.status === "awaiting_payment" ? (!order.expires_at || Date.now() < Date.parse(order.expires_at)) ? <button className="btn" disabled={busy} onClick={() => void pay(order)}>Pay with Razorpay</button> : <p>Checkout expired. If already charged, wait for payment verification or contact the store before placing another order.</p> : null}
            {order.status === "cod_requested" && order.expires_at ? <p>Awaiting store approval until {new Date(order.expires_at).toLocaleString()}.</p> : null}
            {order.status === "confirmed" && order.payment_method === "pay_at_pickup" && order.expires_at ? <p>Held for pickup until {new Date(order.expires_at).toLocaleString()}.</p> : null}
            {order.status === "awaiting_payment" ? <button className="btn light" disabled={busy} onClick={() => {
              setBusy(true); setError("");
              void accountRequest<ShopOrder>(`/orders/${order.id}/reconcile-payment`, { method: "POST" }).then(result => {
                if (result.status === "paid" || result.status === "fulfilment_review") cart.removePurchased(order.items);
                return refreshOrders();
              })
                .catch(failure => setError(String(failure))).finally(() => setBusy(false));
            }}>Already Paid? Verify Payment</button> : null}
            {order.awb ? <p>Tracking: {order.courier} · {order.awb}</p> : null}
          </article>)}
          <div className="shop-actions"><button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button disabled={orders.length < 50 || busy} onClick={() => setOffset(offset + 50)}>Next</button></div>
        </section>
      </>}
    </div>
  </main>;
}
