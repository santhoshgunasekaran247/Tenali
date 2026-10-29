import { FormEvent, useEffect, useState } from "react";
import { CheckCircle2, CreditCard, ExternalLink, MessageCircle, Package, Settings2, ShoppingBag, Truck } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../features/auth";
import { accountRequest, orderStatus, rupees, type ShopOrder } from "../features/shop";

type Settings = { configured: boolean; enabled?: boolean; shipping_paise?: number; pickup_location?: string; payment_mode: "test" | "live" | null };
type Provider = "razorpay" | "shiprocket";
type ConnectionCheck = { provider: Provider; status: "passed" | "failed"; message: string; checked_at: string };
const emptySecrets = { razorpay_key_id: "", razorpay_key_secret: "", razorpay_webhook_secret: "", shiprocket_email: "", shiprocket_password: "" };
const providerLinks = {
  razorpay: "https://dashboard.razorpay.com/",
  shiprocket: "https://app.shiprocket.in/",
  razorpayKyc: "https://razorpay.com/docs/payments/kyc/",
  razorpayKeys: "https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/",
  shiprocketKyc: "https://support.shiprocket.in/support/solutions/articles/43000662578-what-documents-are-required-for-kyc-verification-",
  shiprocketApi: "https://support.shiprocket.in/support/solutions/articles/43000337456-shiprocket-api-document-helpsheet",
};

function ProviderLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <a className="checkout-provider-link" href={href} target="_blank" rel="noopener noreferrer">{children}<ExternalLink size={14} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a>;
}

export function CheckoutAdminPage() {
  const { user } = useAuth();
  const allowed = user?.role === "owner" || user?.role === "admin";
  const [tab, setTab] = useState<"setup" | "orders">("setup");
  const [settings, setSettings] = useState<Settings>({ configured: false, payment_mode: null });
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [form, setForm] = useState({ enabled: false, shipping_rupees: "0", pickup_location: "", ...emptySecrets });
  const [checks, setChecks] = useState<Partial<Record<Provider, ConnectionCheck>>>({});
  const [checking, setChecking] = useState<Provider | null>(null);
  const [orders, setOrders] = useState<ShopOrder[]>([]);
  const [ordersLoaded, setOrdersLoaded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [packageSize, setPackageSize] = useState({ weight: "", length: "", width: "", height: "" });
  const [reconcileId, setReconcileId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = busy || checking !== null;
  const webhookUrl = `${window.location.origin}/api/shop/webhooks/razorpay/${user?.tenant_slug || ""}`;
  const localWebhook = ["localhost", "127.0.0.1"].includes(window.location.hostname) || window.location.protocol !== "https:";
  const refreshOrders = async () => {
    const result = await accountRequest<{ items: ShopOrder[] }>(`/orders?offset=${offset}`, undefined, "checkout-admin");
    setOrders(result.items); setOrdersLoaded(true);
  };
  useEffect(() => {
    if (!allowed) return;
    let active = true;
    void accountRequest<Settings>("/settings", undefined, "checkout-admin").then(result => {
      if (!active) return;
      setSettings(result);
      setForm({ enabled: result.enabled || false, shipping_rupees: ((result.shipping_paise || 0) / 100).toFixed(2), pickup_location: result.pickup_location || "", ...emptySecrets });
      setLoaded(true);
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [allowed, user?.company_id]);
  useEffect(() => {
    if (allowed && tab === "orders") {
      setOrdersLoaded(false);
      void refreshOrders().catch(failure => setError(String(failure)));
    }
  }, [allowed, tab, offset, user?.company_id]);
  const edit = (patch: Partial<typeof form>) => {
    setForm(previous => ({ ...previous, ...patch })); setDirty(true); setChecks({}); setMessage("");
  };
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      if (!/^\d+(?:\.\d{1,2})?$/.test(form.shipping_rupees)) throw new Error("Enter shipping in rupees with at most two decimal places.");
      const { shipping_rupees, ...fields } = form;
      const credentials = Object.fromEntries(Object.entries(emptySecrets).filter(([key]) => !!fields[key as keyof typeof emptySecrets]).map(([key]) => [key, fields[key as keyof typeof emptySecrets]]));
      const shipping_paise = Math.round(Number(shipping_rupees) * 100);
      await accountRequest("/settings", { method: "PUT", body: JSON.stringify({ enabled: form.enabled, pickup_location: form.pickup_location, shipping_paise, ...credentials }) }, "checkout-admin");
      const result = await accountRequest<Settings>("/settings", undefined, "checkout-admin");
      setSettings(result); setForm(previous => ({ ...previous, ...emptySecrets })); setDirty(false); setChecks({});
      setMessage("Setup saved for this workspace. Run the connection checks below; saving alone does not confirm KYC or provider activation.");
    } catch (failure) { setError(String(failure)); } finally { setBusy(false); }
  };
  const checkProvider = async (provider: Provider) => {
    setChecking(provider); setError("");
    setChecks(previous => ({ ...previous, [provider]: undefined }));
    try {
      const result = await accountRequest<ConnectionCheck>(`/settings/check/${provider}`, { method: "POST" }, "checkout-admin");
      setChecks(previous => ({ ...previous, [provider]: result }));
    } catch (failure) { setError(String(failure)); } finally { setChecking(null); }
  };
  const action = async (order: ShopOrder, reconcile: boolean) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await accountRequest(`/orders/${order.id}/${reconcile ? "reconcile-shipment" : "ship"}`, {
        method: "POST", body: JSON.stringify(reconcile ? { provider_order_id: Number(reconcileId) } : packageSize),
      }, "checkout-admin");
      setMessage(reconcile ? "Shipment reconciled." : "Order submitted to Shiprocket. Arrange AWB, pickup and delivery in Shiprocket, then check tracking here.");
      await refreshOrders();
    } catch (failure) { setError(String(failure)); await refreshOrders().catch(refreshFailure => setError(previous => `${previous} ${String(refreshFailure)}`)); }
    finally { setBusy(false); }
  };
  if (!allowed) return <main className="loading">Workspace administrator access is required.</main>;
  const statusLabel = !loaded ? "Loading setup" : !settings.configured ? "Not set up" : !settings.enabled ? "Online purchase hidden" : settings.payment_mode === "test" ? "Test checkout visible - no real payments" : "Live-key checkout visible - approval not verified";
  return <main className="shop-account-page checkout-admin-page">
    <header className="shop-account-heading"><Link to="/portal">Back to Workspace</Link><h1>Payments, Delivery &amp; Shopper Orders</h1><p>Set up your store once. Take online payments, or keep selling through WhatsApp enquiries.</p><span className="checkout-workspace-label">{user?.company_name} only · Each workspace uses its own provider accounts</span></header>
    <div className="shop-account-content">
      <nav className="checkout-page-nav" aria-label="Checkout administration">
        <button type="button" aria-pressed={tab === "setup"} onClick={() => setTab("setup")}><Settings2 size={18} aria-hidden="true" />Setup &amp; activation</button>
        <button type="button" aria-pressed={tab === "orders"} onClick={() => setTab("orders")}><Package size={18} aria-hidden="true" />Manage orders</button>
        <Link to="/">View storefront<ExternalLink size={14} aria-hidden="true" /></Link>
      </nav>
      {error ? <p className="checkout-notice ops-error" role="alert">{error}</p> : null}
      {message ? <p className="checkout-notice" role="status">{message}</p> : null}
      {tab === "setup" ? <>
        <section className="checkout-overview" aria-label="Store checkout status">
          <div><p className="checkout-kicker">Your store status</p><h2>{statusLabel}</h2><p>To accept real orders: finish your Razorpay and Shiprocket account setup, save their login details here, test a payment, then turn on Add to Cart below. Turning it on only shows the shopping button; it cannot activate your payment or shipping account.</p></div>
          <ol className="checkout-milestones"><li><CheckCircle2 size={18} aria-hidden="true" />Setup: {settings.configured ? "saved" : "required"}</li><li><CreditCard size={18} aria-hidden="true" />Razorpay: {settings.payment_mode ? `${settings.payment_mode} keys saved` : "not configured"}</li><li><Truck size={18} aria-hidden="true" />Next: open Razorpay and Shiprocket to finish any pending business-document or pickup-address checks</li></ol>
        </section>
        <section className="checkout-choice-guide" aria-labelledby="selling-options"><h2 id="selling-options">WhatsApp enquiry or online purchase?</h2>
          <div className="checkout-guide-grid">
            <article><MessageCircle size={24} aria-hidden="true" /><h3>WhatsApp: talk before buying</h3><p>For bulk discounts, customisation, quote-only products or availability questions. Opens a chat with the store; no payment, stock reservation or order is created in Tenali.</p><p>Add your business phone in <Link to="/portal/company#company-profile">Company Setup</Link>. Enquiries can stay available even when online checkout is off.</p></article>
            <article><ShoppingBag size={24} aria-hidden="true" /><h3>Add to Cart: shop and pay together</h3><p>Shoppers add priced, in-stock products, choose quantities and pay for the whole cart through Razorpay. Each product starts at the minimum quantity you set in Inventory. That minimum applies separately to each size / colour.</p><p>Shoppers sign in at checkout and review one delivery charge for the order. A WhatsApp conversation is not automatically converted to a cart or paid order.</p></article>
          </div>
        </section>
        <form className="ops-form checkout-setup-form" onSubmit={save}>
          <fieldset className="checkout-setup-fields" disabled={locked || !loaded}>
            <section className="checkout-step" aria-labelledby="payment-setup">
              <div className="checkout-step-heading"><span className="checkout-step-number">1</span><div><h2 id="payment-setup">Connect Razorpay payments</h2><p>Start in Test Mode. Switch to Live Mode only after Razorpay approves your business and website.</p></div></div>
              <div className="checkout-provider-links"><ProviderLink href={providerLinks.razorpay}>Open Razorpay dashboard</ProviderLink><ProviderLink href={providerLinks.razorpayKyc}>KYC documents by business type</ProviderLink><ProviderLink href={providerLinks.razorpayKeys}>Where to find API keys</ProviderLink></div>
              <ol className="checkout-instructions"><li>Create your own Razorpay account. Complete the business/PAN, authorised-person and bank details requested in its onboarding flow. Submit documents directly to Razorpay, not to Tenali.</li><li>Add your public storefront website for review, including contact, pricing, terms, privacy and refund policies. Provide a dedicated shopper test login if reviewers need it; never your staff/admin login. These policy pages are not created by this setup form.</li><li>In <strong>Account &amp; Settings → API Keys</strong>, choose <strong>Test Mode</strong> first and generate a matching key ID and secret. Test keys do not move real money.</li><li>In Razorpay&apos;s payment-capture settings, choose automatic capture. This tells Razorpay to collect a successful payment without you having to approve each one manually. Tenali only treats collected payments as paid orders.</li><li>In Razorpay&apos;s webhook settings, click <strong>Add webhook</strong>. A webhook is a message Razorpay sends to Tenali when a payment succeeds, even if the shopper closes their browser. Paste the URL shown below, select the event named <strong>payment.captured</strong>, and create a private password of at least 16 characters. Paste that same password into <strong>Webhook secret</strong> below. It is not your Razorpay login password or API secret. Set this up in Test Mode while testing, then repeat in Live Mode when you switch to real payments.</li></ol>
              <div className="company-fields">
                <label>Razorpay key ID<input required={!settings.configured} placeholder={settings.configured ? "Saved - enter only to replace key pair" : "rzp_test_... or rzp_live_..."} autoComplete="off" maxLength={100} value={form.razorpay_key_id} onChange={event => edit({ razorpay_key_id: event.target.value })} /><small>The prefix tells Tenali whether this is Test or Live Mode.</small></label>
                <label>Razorpay key secret<input required={!settings.configured} type="password" autoComplete="new-password" maxLength={256} placeholder={settings.configured ? "Saved securely - leave blank to keep" : "Paste the secret generated with this key ID"} value={form.razorpay_key_secret} onChange={event => edit({ razorpay_key_secret: event.target.value })} /><small>Replace key ID and secret together. Never share them in chat.</small></label>
                <label>Webhook secret<input required={!settings.configured} type="password" minLength={16} maxLength={256} autoComplete="new-password" placeholder={settings.configured ? "Saved securely - leave blank to keep" : "Use the same secret in Razorpay and here"} value={form.razorpay_webhook_secret} onChange={event => edit({ razorpay_webhook_secret: event.target.value })} /></label>
                <div className="checkout-webhook"><strong>Webhook URL to enter in Razorpay</strong><code>{webhookUrl}</code><small>Select payment.captured. A connection check does not test webhook delivery.</small></div>
              </div>
              {localWebhook ? <p className="checkout-notice">This is a local or non-HTTPS address. Razorpay cannot deliver a webhook to localhost. Use your deployed public HTTPS workspace domain (or a controlled HTTPS development tunnel) for webhook testing. Browser payment verification still runs, but it does not prove webhook delivery.</p> : null}
            </section>
            <section className="checkout-step" aria-labelledby="shipping-setup">
              <div className="checkout-step-heading"><span className="checkout-step-number">2</span><div><h2 id="shipping-setup">Connect Shiprocket delivery</h2><p>Use a dedicated API user and the exact pickup-location name from your Shiprocket account.</p></div></div>
              <div className="checkout-provider-links"><ProviderLink href={providerLinks.shiprocket}>Open Shiprocket dashboard</ProviderLink><ProviderLink href={providerLinks.shiprocketKyc}>Shiprocket KYC requirements</ProviderLink><ProviderLink href={providerLinks.shiprocketApi}>Create an API user</ProviderLink></div>
              <ol className="checkout-instructions"><li>Register with Shiprocket, complete the KYC for your business type and resolve any dashboard rejection or pending request.</li><li>Add and verify your pickup address/phone as required. Check wallet funds and courier serviceability for the deliveries you plan to accept.</li><li>Go to <strong>Settings → API → Create an API User</strong>. Use an email different from your main Shiprocket login, with permissions for pickup details, orders and shipments.</li><li>Paste that API user&apos;s credentials below, not your personal Shiprocket dashboard password. Copy the pickup-location name exactly, for example Primary.</li></ol>
              <div className="company-fields">
                <label>Shiprocket API-user email<input required={!settings.configured} type="email" autoComplete="off" maxLength={254} placeholder={settings.configured ? "Saved - enter only to replace login pair" : "Dedicated API user email"} value={form.shiprocket_email} onChange={event => edit({ shiprocket_email: event.target.value })} /></label>
                <label>Shiprocket API-user password<input required={!settings.configured} type="password" autoComplete="new-password" maxLength={256} placeholder={settings.configured ? "Saved securely - leave blank to keep" : "API user password, not dashboard password"} value={form.shiprocket_password} onChange={event => edit({ shiprocket_password: event.target.value })} /><small>Replace email and password together.</small></label>
                <label>Pickup-location name<input required maxLength={100} placeholder="Exact name from Shiprocket, e.g. Primary" value={form.pickup_location} onChange={event => edit({ pickup_location: event.target.value })} /></label>
                <label>Flat shipping charge (INR)<input type="number" required min={0} max={10000} step="0.01" value={form.shipping_rupees} onChange={event => edit({ shipping_rupees: event.target.value })} /><small>0 means free shipping. This is your customer-facing flat India rate, not a live courier quote. Confirm it covers your delivery areas and costs.</small></label>
              </div>
            </section>
            <section className="checkout-step" aria-labelledby="storefront-setup">
              <div className="checkout-step-heading"><span className="checkout-step-number">3</span><div><h2 id="storefront-setup">Save and choose what shoppers see</h2><p>Keep online checkout off while preparing your accounts. WhatsApp enquiries can continue.</p></div></div>
              <label className="checkout-switch"><input type="checkbox" checked={form.enabled} onChange={event => edit({ enabled: event.target.checked })} /><span><strong>Show Add to Cart on this workspace&apos;s storefront</strong><small>Test keys let you practise without real money. Live keys can charge shoppers. Before accepting real orders, complete the account checks in Razorpay and Shiprocket.</small></span></label>
              <p>Use numeric product prices (including applicable taxes), active variants and owned stock. Shoppers must log in to this store before paying. Quote-only or unavailable items cannot be purchased.</p>
              <div className="checkout-save-bar"><button className="btn" disabled={locked || !loaded}>{busy ? "Saving..." : "Save workspace setup"}</button><span>{dirty ? "Unsaved changes - save before checking connections." : settings.configured ? "Blank credential fields keep the saved values." : "First save requires both provider logins and the webhook secret."}</span></div>
              <p className="checkout-fine-print">Secrets are encrypted on the server and never returned to this page. Old orders keep their provider snapshot, so do not revoke old keys until those orders are reconciled. The platform operator must configure server credential encryption before your first save.</p>
            </section>
          </fieldset>
        </form>
        <section className="checkout-step" aria-labelledby="test-setup"><div className="checkout-step-heading"><span className="checkout-step-number">4</span><div><h2 id="test-setup">Check connections, then test a purchase</h2><p>Checks use saved settings only. They do not charge a card, create an order or book a shipment.</p></div></div>
          <div className="checkout-guide-grid">
            {(["razorpay", "shiprocket"] as const).map(provider => <article className="checkout-connection-card" key={provider}><h3>{provider === "razorpay" ? "Razorpay keys" : "Shiprocket login & pickup"}</h3><p>{provider === "razorpay" ? "Reads the orders API to check the saved keys. It does not confirm payment capture, KYC or settlement eligibility." : "Signs in as the API user and checks that the saved pickup location exists. It does not approve KYC or confirm a courier route."}</p><button className="btn light" type="button" disabled={locked || !loaded || !settings.configured || dirty} onClick={() => void checkProvider(provider)}>{checking === provider ? "Checking..." : `Check ${provider === "razorpay" ? "Razorpay" : "Shiprocket"} connection`}</button>
              {checks[provider] ? <div className={`checkout-check-result ${checks[provider]?.status}`} role="status"><strong>{checks[provider]?.status === "passed" ? "Connection check passed" : "Action needed"}</strong><p>{checks[provider]?.message}</p><small>Checked {new Date(checks[provider]!.checked_at).toLocaleString()} · Current session only</small></div> : <p className="checkout-fine-print">Not checked in this session.</p>}
            </article>)}
          </div>
          <ol className="checkout-instructions"><li>Save <strong>Test Mode</strong> Razorpay keys and enable Add to Cart only on a store you are testing. Add several products and quantities, then complete a test purchase with Razorpay&apos;s official test payment details. <ProviderLink href="https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/">Razorpay integration &amp; testing guide</ProviderLink></li><li>In <strong>Manage orders</strong>, confirm the order shows <strong>Payment verified</strong>. If verification is pending, use Verify Payment; do not pay twice. Check the same payment in the Razorpay Test dashboard.</li><li>On your public HTTPS site, open Razorpay&apos;s webhook delivery logs and check that the payment.captured message was delivered successfully. The connection-check button cannot test this message.</li><li><strong>Do not send test orders to Shiprocket.</strong> Razorpay test payments are simulated, but Shiprocket API calls can create real shipments. Tenali blocks shipment submission for test-key orders.</li><li>After provider approval, save matching <strong>Live Mode</strong> Razorpay keys and webhook settings, recheck connections, and perform an authorised small real purchase. Check capture in Razorpay and the verified order in Tenali. Live payments and shipping can incur charges; arrange any refund through Razorpay.</li></ol>
        </section>
        <section className="checkout-step" aria-labelledby="activation-help"><h2 id="activation-help">When can I accept real orders?</h2><div className="checkout-guide-grid"><article><h3>Razorpay: finish business verification</h3><p>KYC means checking your identity and business documents. Submit the documents requested in your Razorpay account and resolve any pending requests there. Razorpay also reviews your website; its guide allows up to 3 working days for that review, but total account approval can take longer.</p><p>Once Razorpay lets you take live payments, replace your test keys with live keys here and test a real payment. A successful connection check only means the saved keys work; it does not mean Razorpay has finished reviewing your business.</p></article><article><h3>Shiprocket: prepare for pickup</h3><p>Upload the business documents requested in Shiprocket and complete its pickup-address and phone checks. Its guide says manual document checks may take 2-3 business days. Before accepting orders, check that your wallet has enough funds and couriers deliver to the areas you serve.</p><p>The Shiprocket connection button checks your API login and pickup name. Open Shiprocket to see whether documents or address checks are still pending.</p></article></div><p className="checkout-notice"><strong>Before your first real sale:</strong> finish both provider accounts, save live keys, confirm a real payment and its automatic notification reach Tenali, check delivery costs and coverage, then turn on Add to Cart. Until then, shoppers can still contact you through WhatsApp.</p></section>
      </> : <section className="checkout-orders-section">
        <div className="checkout-orders-heading"><div><h2>Shopper orders</h2><p>Only this workspace&apos;s orders. Payment first, packing and shipping next.</p></div><button className="btn light" disabled={locked} onClick={() => void refreshOrders().catch(failure => setError(String(failure)))}>Refresh orders</button></div>
        {!ordersLoaded ? <p role="status">Loading orders...</p> : !orders.length ? <div className="checkout-empty"><ShoppingBag size={32} aria-hidden="true" /><h3>No orders on this page yet</h3><p>Orders appear here when shoppers proceed to payment for their carts. Adding to cart alone and WhatsApp chats do not create an order.</p><button className="btn light" onClick={() => setTab("setup")}>Review setup &amp; run checks</button></div> : <>
          <details className="checkout-step"><summary>Packing details &amp; shipment recovery</summary><p>For paid live orders, enter actual packed dimensions (cm) and weight (kg) before submitting. If a submission response was lost, find the order in Shiprocket using the Tenali order ID, then enter its Shiprocket order ID here. Do not blindly create another shipment.</p><div className="company-fields">
            {(Object.keys(packageSize) as (keyof typeof packageSize)[]).map(key => <label key={key}>Package {key} ({key === "weight" ? "kg" : "cm"})<input type="number" min={0.001} step="any" value={packageSize[key]} onChange={event => setPackageSize({ ...packageSize, [key]: event.target.value })} /></label>)}
            <label>Shiprocket order ID for recovery / tracking<input inputMode="numeric" value={reconcileId} onChange={event => setReconcileId(event.target.value)} /></label>
          </div></details>
          {orders.map(order => <article className="checkout-step shop-order" key={order.id}><div className="checkout-order-heading"><h3>{order.address.name}</h3><span className="checkout-order-total">{rupees(order.total_paise)}</span></div><p><strong>{orderStatus(order.status)}</strong>{order.provider_key_id.startsWith("rzp_test_") ? " · Test payment - no real shipment" : ""}</p><p className="checkout-fine-print">Order {order.id} · {new Date(order.created_at).toLocaleString()}</p><ul>{order.items.map(item => <li key={`${item.product_id}:${item.variant_id}`}>{item.name} × {item.quantity}</li>)}</ul><p>{order.address.phone}<br />{order.address.address}, {order.address.city}, {order.address.state} {order.address.pincode}</p>
            {order.status === "payment_review" ? <p role="alert" className="checkout-notice">Payment received, but stock could not be allocated. Contact the shopper and resolve/refund in Razorpay. Do not ship or invoice this as fulfilled.</p> : null}
            {order.shipping_error ? <p role="alert" className="ops-error">{order.shipping_error}</p> : null}
            {order.shiprocket_order_id ? <p>Shiprocket order {order.shiprocket_order_id} · Shipment {order.shipment_id} · {order.awb || "AWB not yet recorded"}</p> : null}
            <div className="shop-actions">{order.status === "paid" && !order.provider_key_id.startsWith("rzp_test_") ? <button className="btn" disabled={locked || Object.values(packageSize).some(value => !Number(value) || Number(value) <= 0)} onClick={() => void action(order, false)}>Submit packed order to Shiprocket</button> : null}
              {order.status === "awaiting_payment" ? <button className="btn light" disabled={locked} onClick={() => {
                setBusy(true); setError("");
                void accountRequest(`/orders/${order.id}/reconcile-payment`, { method: "POST" }, "checkout-admin").then(refreshOrders).catch(failure => setError(String(failure))).finally(() => setBusy(false));
              }}>Verify payment with Razorpay</button> : null}
              {order.status === "shipping_pending" || order.status === "shipment_booked" ? <button className="btn light" disabled={locked || !/^[1-9][0-9]*$/.test(reconcileId)} onClick={() => void action(order, true)}>Recover shipment / update tracking</button> : null}</div>
          </article>)}
        </>}
        <div className="shop-actions checkout-pagination"><button disabled={offset === 0 || locked} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><span>Page {offset / 50 + 1}</span><button disabled={orders.length < 50 || locked || !ordersLoaded} onClick={() => setOffset(offset + 50)}>Next</button></div>
        <p className="checkout-fine-print">Shiprocket submission is not pickup or delivery confirmation. Assign an AWB, schedule pickup and manage delivery in Shiprocket; use recovery / tracking to record those details here.</p>
      </section>}
    </div>
  </main>;
}
