import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../features/auth";
import { accountRequest, loadRazorpay, payOrder, rupees, shopperSession, type DeliveryAddress, type Quote, type Shopper, type ShopOrder } from "../features/shop";
import { cartItemKey, useCart } from "../features/cart";

export function CheckoutPage() {
  const { storefront, loading } = useAuth();
  const cart = useCart();
  const location = useLocation();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [shopper, setShopper] = useState<Shopper | null>(null);
  const [address, setAddress] = useState<DeliveryAddress>({ name: "", phone: "", address: "", city: "", state: "", pincode: "", country: "India" });
  const [quote, setQuote] = useState<Quote | null>(null);
  const [order, setOrder] = useState<ShopOrder | null>(null);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cartFingerprint = JSON.stringify(cart.items);
  useEffect(() => {
    setQuote(null);
    if (!order) setRequestKey(crypto.randomUUID());
  }, [cartFingerprint]);
  useEffect(() => {
    const product = search.get("product");
    if (product) navigate(`/products/${encodeURIComponent(product)}${search.get("variant") ? `?variant=${encodeURIComponent(search.get("variant")!)}` : ""}`, { replace: true });
  }, [search, navigate]);
  useEffect(() => {
    if (loading || !storefront) return;
    let active = true;
    shopperSession().then(result => {
      if (!active) return;
      if (!result) { navigate(`/account?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true }); return; }
      setShopper(result); setAddress(previous => ({ ...previous, name: result.display_name }));
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [loading, storefront?.id, location.search]);
  const payload = { request_key: requestKey, items: cart.items, address };
  const getQuote = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { setQuote(await accountRequest<Quote>("/quote", { method: "POST", body: JSON.stringify(payload) })); }
    catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const pay = async () => {
    if (!quote || !shopper || !storefront) return;
    setBusy(true); setError("");
    try {
      await loadRazorpay();
      const created = order || await accountRequest<ShopOrder>("/orders", { method: "POST", body: JSON.stringify({ ...payload, expected_total_paise: quote.total_paise }) });
      setOrder(created);
      const result = await payOrder(created, shopper, storefront.company_name);
      if (!result) { navigate("/account"); return; }
      await accountRequest(`/orders/${created.id}/confirm`, { method: "POST", body: JSON.stringify(result) });
      cart.removePurchased(created.items);
      navigate("/account", { replace: true });
    } catch (failure) { setError(`${String(failure)} Check My Orders before creating another checkout.`); }
    finally { setBusy(false); }
  };
  if (loading) return <main className="loading">Loading store...</main>;
  if (!storefront || !cart.items.length) return <main className="loading">Your cart is empty. <Link to="/">Browse products</Link></main>;
  return <main className="shop-account-page"><header className="shop-account-heading"><Link to="/cart">Back to Cart</Link><h1>Secure Checkout</h1><p>{storefront.company_name} · India delivery · Prepaid Razorpay</p><Link to="/account">My Orders</Link></header><div className="shop-account-content">
    {error ? <p className="ops-error" role="alert">{error}</p> : null}
    {!shopper ? <p>Loading shopper session...</p> : <form className="ops-form ops-card" onSubmit={getQuote}>
      <fieldset className="access-fields" disabled={busy || !!order}><legend>Delivery Details</legend><div className="company-fields">
        {(["name", "phone", "address", "city", "state", "pincode"] as const).map(key => <label key={key}>{({ name: "Full Name", phone: "Mobile Number", address: "Street Address", city: "City", state: "State", pincode: "PIN Code" })[key]}<input required value={address[key]} maxLength={key === "address" ? 250 : key === "phone" ? 10 : key === "pincode" ? 6 : 80} pattern={key === "phone" ? "[6-9][0-9]{9}" : key === "pincode" ? "[1-9][0-9]{5}" : undefined} onChange={event => { setAddress({ ...address, [key]: event.target.value }); setQuote(null); setRequestKey(crypto.randomUUID()); }} /></label>)}
      </div><p>{cart.items.length} products / variants in your cart. <Link to="/cart">Edit products and quantities</Link></p><button className="btn" disabled={busy}>Review Order</button></fieldset>
    </form>}
    {order ? <p className="checkout-notice">Order created. Finish this payment or check <Link to="/account">My Orders</Link> before starting another checkout. <Link to="/account">View payment status</Link></p> : null}
    {quote ? <section className="ops-card"><h2>Order Summary</h2><ul>{quote.items.map(item => <li key={cartItemKey(item)}>{item.name} × {item.quantity} · {rupees(item.unit_paise * item.quantity)}</li>)}</ul><p>Items: {rupees(quote.subtotal_paise)}</p><p>Flat-rate India shipping: {rupees(quote.shipping_paise)}</p><p>Listed item prices include applicable taxes. Final total: <strong>{rupees(quote.total_paise)}</strong></p><p>Your delivery details will be shared with this store&apos;s shipping provider for fulfillment.</p><button className="btn" type="button" disabled={busy || !shopper} onClick={() => void pay()}>{busy ? "Please wait..." : `Pay ${rupees(quote.total_paise)} with Razorpay`}</button></section> : null}
  </div></main>;
}
