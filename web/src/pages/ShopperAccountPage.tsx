import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../features/auth";
import { accountRequest, orderStatus, payOrder, loadRazorpay, rupees, shopperSession, type Shopper, type ShopOrder } from "../features/shop";
import { useCart } from "../features/cart";

export function ShopperAccountPage({ register = false }: { register?: boolean }) {
  const { storefront, loading } = useAuth();
  const cart = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [shopper, setShopper] = useState<Shopper | null>(null);
  const [checking, setChecking] = useState(true);
  const [orders, setOrders] = useState<ShopOrder[]>([]);
  const [offset, setOffset] = useState(0);
  const [form, setForm] = useState({ email: "", display_name: "", password: "", confirmation: "" });
  const [password, setPassword] = useState({ current_password: "", new_password: "" });
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
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (register && form.password !== form.confirmation) throw new Error("Passwords do not match.");
      const result = await accountRequest<Shopper>(register ? "/register" : "/login", {
        method: "POST", body: JSON.stringify(register ? { email: form.email, display_name: form.display_name, password: form.password } : { email: form.email, password: form.password }),
      });
      setShopper(result);
      setForm({ email: "", display_name: "", password: "", confirmation: "" });
      const next = new URLSearchParams(location.search).get("next");
      if (next === "/checkout" || next?.startsWith("/checkout?")) navigate(next, { replace: true });
      else navigate("/account", { replace: true });
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
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
      {!shopper ? <section className="access-panel">
        <form className="ops-form" onSubmit={submit}><fieldset disabled={busy} className="access-fields">
          {register ? <label>Your Name<input required maxLength={150} autoComplete="name" value={form.display_name} onChange={event => setForm({ ...form, display_name: event.target.value })} /></label> : null}
          <label>Email<input required type="email" autoComplete="username" maxLength={254} value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} /></label>
          <label>Password<input required type="password" autoComplete={register ? "new-password" : "current-password"} minLength={register ? 12 : 1} maxLength={128} value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} /></label>
          {register ? <label>Confirm Password<input required type="password" autoComplete="new-password" minLength={12} maxLength={128} value={form.confirmation} onChange={event => setForm({ ...form, confirmation: event.target.value })} /></label> : null}
          <button className="btn" disabled={busy}>{busy ? "Please wait..." : register ? "Create Shopper Account" : "Sign In to Store"}</button>
        </fieldset></form>
        <p><Link to={`${register ? "/account" : "/account/register"}${location.search}`}>{register ? "Already registered? Sign in" : "New shopper? Create an account"}</Link></p>
        <Link to="/login">Workspace staff sign in</Link>
      </section> : <>
        <section className="ops-card"><h2>{shopper.display_name}</h2><p>{shopper.email}</p>
          <button className="btn light" disabled={busy} onClick={() => {
            setBusy(true); setError("");
            void accountRequest("/logout", { method: "POST" }).then(() => { setShopper(null); setOrders([]); })
              .catch(failure => setError(String(failure))).finally(() => setBusy(false));
          }}>Sign Out of Store</button>
          <details><summary>Change Shopper Password</summary><form className="ops-form" onSubmit={event => {
            event.preventDefault(); setBusy(true); setError(""); setMessage("");
            void accountRequest("/password", { method: "POST", body: JSON.stringify(password) })
              .then(() => { setPassword({ current_password: "", new_password: "" }); setMessage("Password changed for this store only. Other shopper sessions were revoked."); })
              .catch(failure => setError(String(failure))).finally(() => setBusy(false));
          }}><label>Current Password<input required type="password" autoComplete="current-password" maxLength={128} value={password.current_password} onChange={event => setPassword({ ...password, current_password: event.target.value })} /></label><label>New Password<input required type="password" autoComplete="new-password" minLength={12} maxLength={128} value={password.new_password} onChange={event => setPassword({ ...password, new_password: event.target.value })} /></label><button className="btn" disabled={busy}>Change Password</button></form></details>
        </section>
        <section><h2>My Orders</h2><button className="ops-link-btn" disabled={busy} onClick={() => void refreshOrders().catch(failure => setError(String(failure)))}>Refresh Payment &amp; Shipping Status</button>
          {!orders.length ? <p>No orders on this page.</p> : null}
          {orders.map(order => <article className="ops-card shop-order" key={order.id}><h3>Order {order.id}</h3><p>{orderStatus(order.status)}</p><ul>{order.items.map(item => <li key={`${item.product_id}:${item.variant_id}`}>{item.name} × {item.quantity} · {rupees(item.unit_paise * item.quantity)}</li>)}</ul><p>Shipping {rupees(order.shipping_paise)} · Total <strong>{rupees(order.total_paise)}</strong></p>
            {order.status === "awaiting_payment" ? Date.now() - Date.parse(order.created_at) < 30 * 60 * 1000 ? <button className="btn" disabled={busy} onClick={() => void pay(order)}>Pay with Razorpay</button> : <p>Checkout expired. If already charged, wait for payment verification or contact the store before placing another order.</p> : null}
            {order.status === "awaiting_payment" ? <button className="btn light" disabled={busy} onClick={() => {
              setBusy(true); setError("");
              void accountRequest<ShopOrder>(`/orders/${order.id}/reconcile-payment`, { method: "POST" }).then(result => {
                if (result.status === "paid" || result.status === "payment_review") cart.removePurchased(order.items);
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
