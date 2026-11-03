import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../features/auth";
import { accountRequest, loadRazorpay, payOrder, rupees, shopperSession, type Availability, type DeliveryAddress, type FulfilmentMethod, type PaymentMethod, type Quote, type Shopper, type ShopOrder } from "../features/shop";
import { cartItemKey, useCart } from "../features/cart";
import { policyPath } from "../features/policies";

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
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [fulfilment, setFulfilment] = useState<FulfilmentMethod>(() => (search.get("pickup") ? "pickup" : "delivery"));
  const [payment, setPayment] = useState<PaymentMethod>("prepaid");
  const [pickupStore, setPickupStore] = useState(() => search.get("pickup") || "");
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cartFingerprint = JSON.stringify(cart.items);
  useEffect(() => {
    setQuote(null);
    if (!order) setRequestKey(crypto.randomUUID());
  }, [cartFingerprint, fulfilment, payment, pickupStore]);
  useEffect(() => {
    if (loading || !storefront) return;
    accountRequest<Availability>("/availability").then(result => {
      setAvailability(result);
      if (!result.prepaid_enabled) setPayment(result.cod_enabled ? "cod" : "pay_at_pickup");
      if (!result.pickup_enabled) setFulfilment("delivery");
    }).catch(failure => setError(String(failure)));
  }, [loading, storefront?.id]);
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
      setShopper(result); setAddress(previous => ({ ...previous, name: result.display_name, phone: result.phone?.replace(/^\+91/, "") || "" }));
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [loading, storefront?.id, location.search]);
  const effectivePayment: PaymentMethod = fulfilment === "pickup" ? (payment === "cod" ? "pay_at_pickup" : payment) : (payment === "pay_at_pickup" ? "prepaid" : payment);
  const payload = { request_key: requestKey, items: cart.items, address, payment_method: effectivePayment, fulfilment_method: fulfilment,
    pickup_store_id: fulfilment === "pickup" ? pickupStore || null : null };
  const getQuote = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { setQuote(await accountRequest<Quote>("/quote", { method: "POST", body: JSON.stringify(payload) })); }
    catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const pay = async () => {
    if (!quote || !shopper || !storefront) return;
    setBusy(true); setError("");
    try {
      if (effectivePayment === "prepaid") await loadRazorpay();
      const created = order || await accountRequest<ShopOrder>("/orders", { method: "POST", body: JSON.stringify({ ...payload, expected_total_paise: quote.total_paise }) });
      setOrder(created);
      if (effectivePayment !== "prepaid") { cart.removePurchased(created.items); navigate("/account", { replace: true }); return; }
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
  return <main className="shop-account-page"><header className="shop-account-heading"><Link to="/cart">Back to Cart</Link><h1>Secure Checkout</h1><p>{storefront.company_name} · {fulfilment === "pickup" ? "Store pickup" : "India delivery"}</p><Link to="/account">My Orders</Link></header><div className="shop-account-content">
    <p className="policy-notice">Review this seller&apos;s <Link to={policyPath("tenant", "terms")}>terms</Link>, <Link to={policyPath("tenant", "privacy")}>privacy</Link>, <Link to={policyPath("tenant", "shipping")}>shipping and delivery</Link>, <Link to={policyPath("tenant", "payment")}>payment</Link> and <Link to={policyPath("tenant", "returns")}>cancellation, refund, return and exchange policies</Link>. <Link to={policyPath("tenant", "contact")}>Contact the seller</Link> for missing or unclear terms.</p>
    {error ? <p className="ops-error" role="alert">{error}</p> : null}
    {!shopper ? <p>Loading shopper session...</p> : <form className="ops-form ops-card" onSubmit={getQuote}>
      <fieldset className="access-fields" disabled={busy || !!order}><legend>Delivery Details</legend><div className="company-fields">
        {(["name", "phone", "address", "city", "state", "pincode"] as const).map(key => <label key={key}>{({ name: "Full Name", phone: "Mobile Number", address: "Street Address", city: "City", state: "State", pincode: "PIN Code" })[key]}<input required value={address[key]} maxLength={key === "address" ? 250 : key === "phone" ? 10 : key === "pincode" ? 6 : 80} pattern={key === "phone" ? "[6-9][0-9]{9}" : key === "pincode" ? "[1-9][0-9]{5}" : undefined} onChange={event => { setAddress({ ...address, [key]: event.target.value }); setQuote(null); setRequestKey(crypto.randomUUID()); }} /></label>)}
      </div>
      {availability ? <div className="company-fields">
        {availability.pickup_enabled && availability.pickup_stores.length ? <label>Receive by<select value={fulfilment} onChange={event => setFulfilment(event.target.value as FulfilmentMethod)}><option value="delivery">Delivery to my address</option><option value="pickup">Pick up at a store</option></select></label> : null}
        {fulfilment === "pickup" ? <label>Pickup store<select required value={pickupStore} onChange={event => setPickupStore(event.target.value)}><option value="">Choose a store</option>{availability.pickup_stores.map(store => <option key={store.id} value={store.id}>{store.name}{store.address ? ` · ${store.address}` : ""}</option>)}</select></label> : null}
        <label>Pay by<select value={effectivePayment} onChange={event => setPayment(event.target.value as PaymentMethod)}>
          {availability.prepaid_enabled ? <option value="prepaid">Pay online now (Razorpay)</option> : null}
          {fulfilment === "delivery" && availability.cod_enabled ? <option value="cod">Cash on delivery (store approval required)</option> : null}
          {fulfilment === "pickup" ? <option value="pay_at_pickup">Pay at the store when collecting</option> : null}
        </select></label>
      </div> : null}
      <p>{cart.items.length} products / variants in your cart. <Link to="/cart">Edit products and quantities</Link></p><button className="btn" disabled={busy || (fulfilment === "pickup" && !pickupStore)}>Review Order</button></fieldset>
    </form>}
    {order ? <p className="checkout-notice">Order created. Finish this payment or check <Link to="/account">My Orders</Link> before starting another checkout. <Link to="/account">View payment status</Link></p> : null}
    {quote ? <section className="ops-card"><h2>Order Summary</h2><ul>{quote.items.map(item => <li key={cartItemKey(item)}>{item.name} × {item.quantity} · {rupees(item.unit_paise * item.quantity)}</li>)}</ul><p>Items: {rupees(quote.subtotal_paise)}</p>{fulfilment === "pickup" ? <p>Pickup at {quote.pickup_store || "the chosen store"} · no shipping charge</p> : <p>Flat-rate India shipping: {rupees(quote.shipping_paise)}</p>}<p>Listed item prices include applicable taxes. Final total: <strong>{rupees(quote.total_paise)}</strong></p>{fulfilment === "delivery" ? <p>Your delivery details will be shared with this store&apos;s shipping provider for fulfillment.</p> : null}
      {effectivePayment === "cod" ? <p>The store reviews cash-on-delivery requests before confirming. You pay the courier {rupees(quote.total_paise)} on delivery.</p> : null}
      {effectivePayment === "pay_at_pickup" ? <p>Your items are held at the store for a limited time. Pay {rupees(quote.total_paise)} at the counter when you collect.</p> : null}
      <button className="btn" type="button" disabled={busy || !shopper} onClick={() => void pay()}>{busy ? "Please wait..." : effectivePayment === "prepaid" ? `Pay ${rupees(quote.total_paise)} with Razorpay` : effectivePayment === "cod" ? "Request cash on delivery" : "Reserve for pickup"}</button></section> : null}
  </div></main>;
}
