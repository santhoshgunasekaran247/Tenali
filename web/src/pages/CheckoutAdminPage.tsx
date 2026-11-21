import { FloatingAlert } from "../components/Notifications";
import { FormEvent, useEffect, useState } from "react";
import { CheckCircle2, CreditCard, ExternalLink, MessageCircle, Package, ShoppingBag, Truck } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../features/auth";
import { accountRequest, canVerifyPayment, orderStatus, paymentLabel, rupees, type ShopOrder } from "../features/shop";
import { emptyPackage, OrderActions, ShiprocketPanel, useStoresAndAccounts, type PackageSize } from "../components/OrderActions";
import { DeleteTransactionDialog } from "../components/DeleteTransactionDialog";
import { OrderItems } from "../components/OrderItems";

type Policy = { shipping_provider: "shiprocket" | "self"; prepaid_enabled: boolean; shipping_sac: string; shipping_gst_rate: number | string; cod_enabled: boolean; cod_limit: number | string; cod_approval_hours: number;
  cod_overdue_days: number; cod_serviceable_pincodes: string[]; pickup_enabled: boolean; pickup_hold_hours: number; pickup_reminder_hours: number; prepaid_hold_minutes: number };
type Settings = { configured: boolean; enabled?: boolean; checkout_available?: boolean; checkout_blocker?: string | null; online_store_ready?: boolean; shipping_paise?: number; pickup_location?: string; payment_mode: "test" | "live" | null; credentials_saved?: boolean; razorpay_saved?: boolean; shiprocket_saved?: boolean } & Partial<Policy>;
const defaultPolicy: Policy = { prepaid_enabled: true, shipping_sac: "9968", shipping_gst_rate: 18, cod_enabled: false, cod_limit: 5000, cod_approval_hours: 24, cod_overdue_days: 15,
  cod_serviceable_pincodes: [], pickup_enabled: false, pickup_hold_hours: 72, pickup_reminder_hours: 48, prepaid_hold_minutes: 20, shipping_provider: "shiprocket" };
type CodRow = { order_id: string; status: string; dispatched_at: string | null; invoice_number: string; total: number; amount_received: number; outstanding: number; days_since_dispatch: number | null; overdue: boolean };
type Settlement = { id: string; courier: string; settlement_reference: string; settlement_date: string; expected_amount: number; received_amount: number; shortfall_reason: string | null };
type Enquiry = { id: string; reference: string; product_name: string; variant_name: string | null; quantity: number; shopper_name: string; shopper_phone: string; message: string | null; status: string; store_code: string | null; created_at: string; invoice_id: string | null };
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

export function CheckoutAdminPage({ setupOnly = false }: { setupOnly?: boolean }) {
  const { user } = useAuth();
  const allowed = user?.role === "owner" || user?.role === "admin";
  const [tab, setTab] = useState<"orders" | "cod" | "enquiries">("orders");
  const { stores, accounts, lookupError } = useStoresAndAccounts();
  const [policy, setPolicy] = useState<Policy>(defaultPolicy);
  const [pincodeText, setPincodeText] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [cod, setCod] = useState<{ items: CodRow[]; settlements: Settlement[]; total_outstanding: number } | null>(null);
  const [settlement, setSettlement] = useState({ courier: "", settlement_reference: "", settlement_date: new Date().toISOString().slice(0, 10), account_id: "", shortfall_reason: "", notes: "" });
  const [settlementItems, setSettlementItems] = useState<Record<string, string>>({});
  const [enquiries, setEnquiries] = useState<Enquiry[]>([]);
  const [enquiryInvoice, setEnquiryInvoice] = useState<Record<string, string>>({});
  const [settings, setSettings] = useState<Settings>({ configured: false, payment_mode: null });
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [form, setForm] = useState({ enabled: false, shipping_rupees: "0", pickup_location: "", ...emptySecrets });
  const [checks, setChecks] = useState<Partial<Record<Provider, ConnectionCheck>>>({});
  const [checking, setChecking] = useState<Provider | null>(null);
  const [orders, setOrders] = useState<ShopOrder[]>([]);
  const [ordersLoaded, setOrdersLoaded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [packages, setPackages] = useState<Record<string, PackageSize>>({});
  const [reconcileIds, setReconcileIds] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [settlementDelete, setSettlementDelete] = useState<Settlement | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = busy || checking !== null;
  const webhookUrl = `${window.location.origin}/api/shop/webhooks/razorpay/${user?.tenant_slug || ""}`;
  const localWebhook = ["localhost", "127.0.0.1"].includes(window.location.hostname) || window.location.protocol !== "https:";
  const refreshOrders = async () => {
    const result = await accountRequest<{ items: ShopOrder[] }>(`/orders?offset=${offset}${statusFilter ? `&status=${statusFilter}` : ""}`, undefined, "checkout-admin");
    setOrders(result.items); setOrdersLoaded(true);
  };
  const refreshCod = async () => setCod(await accountRequest("/cod", undefined, "checkout-admin"));
  const refreshEnquiries = async () => setEnquiries((await accountRequest<{ items: Enquiry[] }>("/enquiries", undefined, "checkout-admin")).items);
  useEffect(() => {
    if (!allowed || setupOnly) return;
    if (tab === "cod") void refreshCod().catch(failure => setError(String(failure)));
    if (tab === "enquiries") void refreshEnquiries().catch(failure => setError(String(failure)));
  }, [allowed, setupOnly, tab, user?.company_id]);
  useEffect(() => {
    if (!allowed || !setupOnly) return;
    let active = true;
    void accountRequest<Settings>("/settings", undefined, "checkout-admin").then(result => {
      if (!active) return;
      setSettings(result);
      setForm({ enabled: result.enabled || false, shipping_rupees: ((result.shipping_paise || 0) / 100).toFixed(2), pickup_location: result.pickup_location || "", ...emptySecrets });
      const loadedPolicy = { ...defaultPolicy, ...Object.fromEntries(Object.entries(result).filter(([key, value]) => key in defaultPolicy && value !== null && value !== undefined)) } as Policy;
      setPolicy(loadedPolicy); setPincodeText(loadedPolicy.cod_serviceable_pincodes.join(", "));
      setLoaded(true);
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [allowed, setupOnly, user?.company_id]);
  useEffect(() => {
    if (allowed && !setupOnly && tab === "orders") {
      setOrdersLoaded(false);
      void refreshOrders().catch(failure => setError(String(failure)));
    }
  }, [allowed, setupOnly, tab, offset, statusFilter, user?.company_id]);
  // Pull AWB/courier from Shiprocket in the background; the server throttles and skips orders that already have tracking.
  useEffect(() => {
    if (!allowed || setupOnly || tab !== "orders") return;
    let active = true;
    const sync = () => void accountRequest<{ updated: number }>("/tracking/sync", { method: "POST" }, "checkout-admin")
      .then(result => { if (active && result?.updated) return refreshOrders(); })
      .catch(() => {});
    sync();
    const timer = window.setInterval(sync, 180_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [allowed, setupOnly, tab, user?.company_id]);
  const edit = (patch: Partial<typeof form>) => {
    setForm(previous => ({ ...previous, ...patch })); setDirty(true); setChecks({}); setMessage("");
  };
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      if (!/^\d+(?:\.\d{1,2})?$/.test(form.shipping_rupees)) throw new Error("Enter shipping in rupees with at most two decimal places.");
      const { shipping_rupees, ...fields } = form;
      const credentials = Object.fromEntries(Object.entries(emptySecrets).filter(([key]) =>
        (policy.shipping_provider === "shiprocket" || !key.startsWith("shiprocket_")) && !!fields[key as keyof typeof emptySecrets])
        .map(([key]) => [key, fields[key as keyof typeof emptySecrets]]));
      const shipping_paise = Math.round(Number(shipping_rupees) * 100);
      const pincodes = pincodeText.split(/[\s,]+/).map(value => value.trim()).filter(Boolean);
      await accountRequest("/settings", { method: "PUT", body: JSON.stringify({ enabled: form.enabled, pickup_location: form.pickup_location, shipping_paise, ...credentials, ...policy,
        shipping_gst_rate: Number(policy.shipping_gst_rate), cod_limit: Number(policy.cod_limit), cod_serviceable_pincodes: pincodes }) }, "checkout-admin");
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
        method: "POST", body: JSON.stringify(reconcile ? { provider_order_id: Number(reconcileIds[order.id]) } : packages[order.id] || emptyPackage),
      }, "checkout-admin");
      setMessage(reconcile ? "Shipment reconciled." : ["dispatched", "delivered"].includes(order.status) ? "Order submitted to Shiprocket. Arrange AWB and pickup in Shiprocket." : "Order submitted to Shiprocket. You can now dispatch & invoice it; arrange AWB and pickup in Shiprocket.");
      await refreshOrders();
    } catch (failure) { setError(String(failure)); await refreshOrders().catch(refreshFailure => setError(previous => `${previous} ${String(refreshFailure)}`)); }
    finally { setBusy(false); }
  };
  const release = async (order: ShopOrder) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await accountRequest(`/orders/${order.id}/release-shipment`, { method: "POST" }, "checkout-admin");
      setMessage("Shiprocket submission released. Enter the packed size and submit again.");
      await refreshOrders();
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  };
  if (!allowed) return <main className="loading">Workspace administrator access is required.</main>;
  const statusLabel = !loaded ? "Loading setup" : !settings.configured ? "Not set up" : !settings.enabled ? "Online purchase hidden"
    : !settings.checkout_available ? "Checkout blocked - store setup required"
    : !settings.prepaid_enabled ? "Checkout visible - online payment off"
    : settings.payment_mode === "test" ? "Test checkout visible - no real payments"
    : settings.payment_mode === "live" ? "Live-key checkout visible - approval not verified" : "Razorpay setup required";
  return <main className="shop-account-page checkout-admin-page">
    <header className="shop-account-heading"><Link to="/portal">Back to Workspace</Link><h1>{setupOnly ? "Payments & Delivery Setup" : "Online Orders"}</h1>
      <p>{setupOnly ? "Connect payment and delivery providers, configure checkout and activate online purchases." : "Manage shopper orders, courier COD settlements and customer enquiries."}</p>
      <span className="checkout-workspace-label">{user?.company_name} only · {setupOnly ? "Each workspace uses its own provider accounts" : "Orders and enquiries for this workspace"}</span></header>
    <div className="shop-account-content">
      <nav className="checkout-page-nav" aria-label={setupOnly ? "Payment and delivery setup" : "Online order operations"}>
        {setupOnly ? <Link to="/portal/checkout"><Package size={18} aria-hidden="true" />Open online orders</Link> : <>
        <button type="button" aria-pressed={tab === "orders"} onClick={() => setTab("orders")}><Package size={18} aria-hidden="true" />Manage orders</button>
        <button type="button" aria-pressed={tab === "cod"} onClick={() => setTab("cod")}><CreditCard size={18} aria-hidden="true" />COD settlements</button>
        <button type="button" aria-pressed={tab === "enquiries"} onClick={() => setTab("enquiries")}><MessageCircle size={18} aria-hidden="true" />Enquiries</button>
        </>}
        <Link to="/">View storefront<ExternalLink size={14} aria-hidden="true" /></Link>
      </nav>
      {error ? <FloatingAlert>{error}</FloatingAlert> : null}
      {lookupError ? <FloatingAlert>Unable to load stores and settlement accounts: {lookupError}. Refresh before changing an order.</FloatingAlert> : null}
      {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
      {setupOnly ? <>
        <section className="checkout-overview" aria-label="Store checkout status">
          <div><p className="checkout-kicker">Your store status</p><h2>{statusLabel}</h2><p>Choose your payment and shipping methods, save the required credentials and test before turning on Add to Cart. Self-shipping uses your own delivery team or courier; Shiprocket is optional. Turning on checkout does not activate a provider account.</p></div>
          <ol className="checkout-milestones"><li><CheckCircle2 size={18} aria-hidden="true" />Setup: {settings.configured ? "saved" : "required"}</li><li><CreditCard size={18} aria-hidden="true" />Razorpay: {settings.payment_mode ? `${settings.payment_mode} keys saved` : "not configured"}</li><li><Truck size={18} aria-hidden="true" />Delivery: {policy.shipping_provider === "self" ? "Self-shipping / own courier" : "Shiprocket"}</li></ol>
        </section>
        {settings.configured && settings.checkout_blocker ? <p className="checkout-notice" role="status">{settings.checkout_blocker} <Link to="/portal/stores">Open Stores</Link></p> : null}
        {settings.payment_mode === "test" ? <p className="checkout-notice">Test keys are saved in Tenali. Activating Live Mode in Razorpay does not replace them here. To accept real payments, save the matching live key ID and secret, configure the Live Mode webhook secret, then run the connection check.</p> : null}
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
              <p><Link to="/portal/policies">Draft, review and publish this store&apos;s policies</Link> before website review. Use the store&apos;s public contact, privacy, terms, shipping, payment and cancellation/refund/returns pages, not unpublished drafts or Tenali platform policies.</p>
              <ol className="checkout-instructions"><li>Create your own Razorpay account. Complete the business/PAN, authorised-person and bank details requested in its onboarding flow. Submit documents directly to Razorpay, not to Tenali.</li><li>Add your public storefront website for review, including contact, pricing, terms, privacy and refund policies. Provide a dedicated shopper test login if reviewers need it; never your staff/admin login. These policy pages are not created by this setup form.</li><li>In <strong>Account &amp; Settings → API Keys</strong>, choose <strong>Test Mode</strong> first and generate a matching key ID and secret. Test keys do not move real money.</li><li>In Razorpay&apos;s payment-capture settings, choose automatic capture. This tells Razorpay to collect a successful payment without you having to approve each one manually. Tenali only treats collected payments as paid orders.</li><li>In Razorpay&apos;s webhook settings, click <strong>Add webhook</strong>. A webhook is a message Razorpay sends to Tenali when a payment succeeds, even if the shopper closes their browser. Paste the URL shown below, select the event named <strong>payment.captured</strong>, and create a private password of at least 16 characters. Paste that same password into <strong>Webhook secret</strong> below. It is not your Razorpay login password or API secret. Set this up in Test Mode while testing, then repeat in Live Mode when you switch to real payments.</li></ol>
              <div className="company-fields">
                <label>Razorpay key ID<input required={policy.prepaid_enabled && !settings.razorpay_saved} placeholder={settings.razorpay_saved ? "Saved - enter only to replace key pair" : "rzp_test_... or rzp_live_..."} autoComplete="off" maxLength={100} value={form.razorpay_key_id} onChange={event => edit({ razorpay_key_id: event.target.value })} /><small>The prefix tells Tenali whether this is Test or Live Mode.</small></label>
                <label>Razorpay key secret<input required={policy.prepaid_enabled && !settings.razorpay_saved} type="password" autoComplete="new-password" maxLength={256} placeholder={settings.razorpay_saved ? "Saved securely - leave blank to keep" : "Paste the secret generated with this key ID"} value={form.razorpay_key_secret} onChange={event => edit({ razorpay_key_secret: event.target.value })} /><small>Replace key ID and secret together. Never share them in chat.</small></label>
                <label>Webhook secret<input required={policy.prepaid_enabled && !settings.razorpay_saved} type="password" minLength={16} maxLength={256} autoComplete="new-password" placeholder={settings.razorpay_saved ? "Saved securely - leave blank to keep" : "Use the same secret in Razorpay and here"} value={form.razorpay_webhook_secret} onChange={event => edit({ razorpay_webhook_secret: event.target.value })} /></label>
                <div className="checkout-webhook"><strong>Webhook URL to enter in Razorpay</strong><code>{webhookUrl}</code><small>Select payment.captured. A connection check does not test webhook delivery.</small></div>
              </div>
              {localWebhook ? <p className="checkout-notice">This is a local or non-HTTPS address. Razorpay cannot deliver a webhook to localhost. Use your deployed public HTTPS workspace domain (or a controlled HTTPS development tunnel) for webhook testing. Browser payment verification still runs, but it does not prove webhook delivery.</p> : null}
            </section>
            <section className="checkout-step" aria-labelledby="shipping-setup">
              <div className="checkout-step-heading"><span className="checkout-step-number">2</span><div><h2 id="shipping-setup">Choose how you ship</h2><p>Use your own delivery team or courier, or connect Shiprocket.</p></div></div>
              <label>Shipping method<select value={policy.shipping_provider} onChange={event => {
                setPolicy({ ...policy, shipping_provider: event.target.value as Policy["shipping_provider"] }); setDirty(true); setChecks({});
              }}><option value="self">Self-shipping / own courier</option><option value="shiprocket">Shiprocket</option></select></label>
              <p className="checkout-fine-print">Applies to new orders only. Existing orders keep their original shipping method.</p>
              {policy.shipping_provider === "self" ? <p className="checkout-notice">No Shiprocket account is required. Arrange delivery yourself, enter optional courier and tracking details when dispatching, then mark the order delivered. COD receipts are recorded under COD settlements.</p> : <>
              <div className="checkout-provider-links"><ProviderLink href={providerLinks.shiprocket}>Open Shiprocket dashboard</ProviderLink><ProviderLink href={providerLinks.shiprocketKyc}>Shiprocket KYC requirements</ProviderLink><ProviderLink href={providerLinks.shiprocketApi}>Create an API user</ProviderLink></div>
              <ol className="checkout-instructions"><li>Register with Shiprocket, complete the KYC for your business type and resolve any dashboard rejection or pending request.</li><li>Add and verify your pickup address/phone as required. Check wallet funds and courier serviceability for the deliveries you plan to accept.</li><li>Go to <strong>Settings → API → Create an API User</strong>. Use an email different from your main Shiprocket login, with permissions for pickup details, orders and shipments.</li><li>Paste that API user&apos;s credentials below, not your personal Shiprocket dashboard password. Copy the pickup-location name exactly, for example Primary.</li></ol>
              <div className="company-fields">
                <label>Shiprocket API-user email<input required={!settings.shiprocket_saved && policy.prepaid_enabled} type="email" autoComplete="off" maxLength={254} placeholder={settings.shiprocket_saved ? "Saved - enter only to replace login pair" : "Dedicated API user email"} value={form.shiprocket_email} onChange={event => edit({ shiprocket_email: event.target.value })} /></label>
                <label>Shiprocket API-user password<input required={!settings.shiprocket_saved && policy.prepaid_enabled} type="password" autoComplete="new-password" maxLength={256} placeholder={settings.shiprocket_saved ? "Saved securely - leave blank to keep" : "API user password, not dashboard password"} value={form.shiprocket_password} onChange={event => edit({ shiprocket_password: event.target.value })} /><small>Replace email and password together.</small></label>
                <label>Pickup-location name<input required maxLength={100} placeholder="Exact name from Shiprocket, e.g. Primary" value={form.pickup_location} onChange={event => edit({ pickup_location: event.target.value })} /></label>
              </div>
              </>}
              <label>Flat shipping charge (INR)<input type="number" required min={0} max={10000} step="0.01" value={form.shipping_rupees} onChange={event => edit({ shipping_rupees: event.target.value })} /><small>0 means free shipping. This is your customer-facing flat India rate, not a live courier quote. Confirm it covers your delivery areas and costs.</small></label>
            </section>
            <section className="checkout-step" aria-labelledby="storefront-setup">
              <div className="checkout-step-heading"><span className="checkout-step-number">3</span><div><h2 id="storefront-setup">Save and choose what shoppers see</h2><p>Keep online checkout off while preparing your accounts. WhatsApp enquiries can continue. Checkout also requires an active Online store linked to an active fulfilment warehouse or shop in <Link to="/portal/stores">Stores</Link>.</p></div></div>
              <label className="checkout-switch"><input type="checkbox" checked={form.enabled} onChange={event => edit({ enabled: event.target.checked })} /><span><strong>Show Add to Cart on this workspace&apos;s storefront</strong><small>Test keys let you practise without real money. Live keys can charge shoppers. Complete checks for the providers you use and arrange delivery coverage before accepting real orders.</small></span></label>
              <div className="company-fields">
                <label className="ops-toggle"><input type="checkbox" checked={policy.prepaid_enabled} onChange={event => { setPolicy({ ...policy, prepaid_enabled: event.target.checked }); setDirty(true); }} />Online payment (Razorpay)</label>
                <label className="ops-toggle"><input type="checkbox" checked={policy.cod_enabled} onChange={event => { setPolicy({ ...policy, cod_enabled: event.target.checked }); setDirty(true); }} />Cash on delivery (requested, then approved by you)</label>
                <label className="ops-toggle"><input type="checkbox" checked={policy.pickup_enabled} onChange={event => { setPolicy({ ...policy, pickup_enabled: event.target.checked }); setDirty(true); }} />Store pickup at shops marked &quot;allows pickup&quot;</label>
                <label>COD limit per order (INR)<input type="number" min={0} step="0.01" value={policy.cod_limit} onChange={event => { setPolicy({ ...policy, cod_limit: event.target.value }); setDirty(true); }} /></label>
                <label>COD approval window (hours)<input type="number" min={1} max={720} value={policy.cod_approval_hours} onChange={event => { setPolicy({ ...policy, cod_approval_hours: Number(event.target.value) }); setDirty(true); }} /></label>
                <label>COD overdue after (days)<input type="number" min={1} max={365} value={policy.cod_overdue_days} onChange={event => { setPolicy({ ...policy, cod_overdue_days: Number(event.target.value) }); setDirty(true); }} /></label>
                <label>COD serviceable PIN codes (blank = all)<textarea rows={2} value={pincodeText} onChange={event => { setPincodeText(event.target.value); setDirty(true); }} placeholder="600001, 600002" /></label>
                <label>Pickup hold (hours)<input type="number" min={1} max={720} value={policy.pickup_hold_hours} onChange={event => { setPolicy({ ...policy, pickup_hold_hours: Number(event.target.value) }); setDirty(true); }} /></label>
                <label>Pickup reminder (hours)<input type="number" min={1} max={720} value={policy.pickup_reminder_hours} onChange={event => { setPolicy({ ...policy, pickup_reminder_hours: Number(event.target.value) }); setDirty(true); }} /></label>
                <label>Online payment hold (minutes)<input type="number" min={5} max={180} value={policy.prepaid_hold_minutes} onChange={event => { setPolicy({ ...policy, prepaid_hold_minutes: Number(event.target.value) }); setDirty(true); }} /></label>
                <label>Shipping SAC<input maxLength={8} pattern="[0-9]{4,8}" value={policy.shipping_sac} onChange={event => { setPolicy({ ...policy, shipping_sac: event.target.value }); setDirty(true); }} /></label>
                <label>Shipping GST %<input type="number" min={0} max={100} step="0.01" value={policy.shipping_gst_rate} onChange={event => { setPolicy({ ...policy, shipping_gst_rate: event.target.value }); setDirty(true); }} /></label>
              </div>
              <p className="checkout-fine-print">Stock leaves a store only when an order is dispatched or collected; before that it is held. Invoices for online orders use the online store&apos;s series; pay-at-pickup invoices use the shop&apos;s own series. Set up stores and the Razorpay clearing account under Stores &amp; Warehouses.</p>
              <p>Use numeric product prices (including applicable taxes), active variants and owned stock. Shoppers must log in to this store before paying. Quote-only or unavailable items cannot be purchased.</p>
              <div className="checkout-save-bar"><button className="btn" disabled={locked || !loaded}>{busy ? "Saving..." : "Save workspace setup"}</button><span>{dirty ? "Unsaved changes - save before checking connections." : settings.configured ? "Blank credential fields keep the saved values." : "Enter credentials only for the payment and shipping providers you enable."}</span></div>
              <p className="checkout-fine-print">Secrets are encrypted on the server and never returned to this page. Old orders keep their provider snapshot, so do not revoke old keys until those orders are reconciled. The platform operator must configure server credential encryption before your first save.</p>
            </section>
          </fieldset>
        </form>
        <section className="checkout-step" aria-labelledby="test-setup"><div className="checkout-step-heading"><span className="checkout-step-number">4</span><div><h2 id="test-setup">Check connections, then test a purchase</h2><p>Checks use saved settings only. They do not charge a card, create an order or book a shipment.</p></div></div>
          <div className="checkout-guide-grid">
            {(["razorpay", "shiprocket"] as const).filter(provider => provider !== "shiprocket" || policy.shipping_provider === "shiprocket").map(provider => <article className="checkout-connection-card" key={provider}><h3>{provider === "razorpay" ? "Razorpay keys" : "Shiprocket login & pickup"}</h3><p>{provider === "razorpay" ? "Reads the orders API to check the saved keys. It does not confirm payment capture, KYC or settlement eligibility." : "Signs in as the API user and checks that the saved pickup location exists. It does not approve KYC or confirm a courier route."}</p><button className="btn light" type="button" disabled={locked || !loaded || !settings.configured || dirty} onClick={() => void checkProvider(provider)}>{checking === provider ? "Checking..." : `Check ${provider === "razorpay" ? "Razorpay" : "Shiprocket"} connection`}</button>
              {checks[provider] ? <div className={`checkout-check-result ${checks[provider]?.status}`} role="status"><strong>{checks[provider]?.status === "passed" ? "Connection check passed" : "Action needed"}</strong><p>{checks[provider]?.message}</p><small>Checked {new Date(checks[provider]!.checked_at).toLocaleString()} · Current session only</small></div> : <p className="checkout-fine-print">Not checked in this session.</p>}
            </article>)}
          </div>
          <ol className="checkout-instructions"><li>Save <strong>Test Mode</strong> Razorpay keys and enable Add to Cart only on a store you are testing. Add several products and quantities, then complete a test purchase with Razorpay&apos;s official test payment details. <ProviderLink href="https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/">Razorpay integration &amp; testing guide</ProviderLink></li><li>In <strong>Manage orders</strong>, confirm the order shows <strong>Payment verified</strong>. If verification is pending, use Verify Payment; do not pay twice. Check the same payment in the Razorpay Test dashboard.</li><li>On your public HTTPS site, open Razorpay&apos;s webhook delivery logs and check that the payment.captured message was delivered successfully. The connection-check button cannot test this message.</li><li><strong>Do not send test orders to Shiprocket.</strong> Razorpay test payments are simulated, but Shiprocket API calls can create real shipments. Tenali blocks shipment submission for test-key orders.</li><li>After provider approval, save matching <strong>Live Mode</strong> Razorpay keys and webhook settings, recheck connections, and perform an authorised small real purchase. Check capture in Razorpay and the verified order in Tenali. Live payments and shipping can incur charges; arrange any refund through Razorpay.</li></ol>
        </section>
        <section className="checkout-step" aria-labelledby="activation-help"><h2 id="activation-help">When can I accept real orders?</h2><div className="checkout-guide-grid">
          <article><h3>Razorpay: finish business verification</h3><p>If you enable online payment, complete Razorpay business and website approval. Save live keys, test a real payment and verify webhook delivery. A connection check alone does not establish approval.</p></article>
          {policy.shipping_provider === "shiprocket" ? <article><h3>Shiprocket: prepare for pickup</h3><p>Complete Shiprocket KYC, verify the pickup address and phone, and check wallet funds and courier coverage. A successful API connection does not establish provider approval.</p></article> :
            <article><h3>Self-shipping: arrange your own delivery</h3><p>No Shiprocket credentials or checks are needed. Confirm your courier coverage and costs, then dispatch from Online Orders. Add optional courier and tracking details, mark delivery when completed and record COD receipts separately.</p></article>}
        </div><p className="checkout-notice"><strong>Before your first real sale:</strong> verify the payment methods you enabled, delivery costs and coverage. Turn on Add to Cart only when ready. Shoppers can still contact you through WhatsApp while you prepare.</p></section>
      </> : tab === "orders" ? <section className="checkout-orders-section">
        <div className="checkout-orders-heading"><div><h2>Shopper orders</h2><p>Only this workspace&apos;s orders. Approve, dispatch and collect from here; each dispatch or collection creates the invoice and books stock.</p></div><div className="shop-actions"><label>Status<select value={statusFilter} onChange={event => { setStatusFilter(event.target.value); setOffset(0); }}><option value="">All</option>{["awaiting_payment", "expired", "cod_requested", "paid", "confirmed", "fulfilment_review", "shipping_pending", "shipment_booked", "dispatched", "ready_for_pickup", "delivered", "collected", "cancelled"].map(value => <option key={value} value={value}>{orderStatus(value as ShopOrder["status"])}</option>)}</select></label><button className="btn light" disabled={locked} onClick={() => void refreshOrders().catch(failure => setError(String(failure)))}>Refresh orders</button></div></div>
        {!ordersLoaded ? <p role="status">Loading orders...</p> : !orders.length ? <div className="checkout-empty"><ShoppingBag size={32} aria-hidden="true" /><h3>No orders on this page yet</h3><p>Orders appear here when shoppers proceed to payment for their carts. Adding to cart alone and WhatsApp chats do not create an order.</p><Link className="btn light" to="/portal/checkout-setup">Review payments &amp; delivery setup</Link></div> : <>
          {orders.map(order => <article className="checkout-step shop-order online-order-card" key={order.id}><header className="checkout-order-heading"><div><p className="checkout-kicker">Order #{order.id.slice(0, 8)}</p><h3>{order.address.name}</h3><time dateTime={order.created_at}>{new Date(order.created_at).toLocaleString()}</time></div><div className="order-heading-total"><span className="checkout-order-total">{rupees(order.total_paise)}</span><span>{paymentLabel(order.payment_method)}</span></div></header>
            <div className="order-status-row"><span className={`order-status-badge order-status-${order.status}`}>{orderStatus(order.status)}</span>{(order.provider_key_id || "").startsWith("rzp_test_") ? <span className="order-test-badge">Test payment - no real shipment</span> : null}</div>
            <div className="order-details-grid"><section aria-label="Ordered items"><h4>Items</h4><OrderItems items={order.items} /><p className="order-delivery-charge">Delivery <strong>{order.shipping_paise ? rupees(order.shipping_paise) : "Free"}</strong></p></section>
              <section className="order-delivery-address" aria-label="Delivery contact"><h4>{order.fulfilment_method === "pickup" ? "Shopper contact" : "Deliver to"}</h4><strong>{order.address.name}</strong><a href={`tel:${order.address.phone}`}>{order.address.phone}</a><address>{order.address.address}<br />{order.address.city}, {order.address.state} {order.address.pincode}</address></section></div>
            <details className="order-reference"><summary>Order reference</summary><p>{order.id}</p>{order.razorpay_payment_id ? <p>Razorpay: {order.razorpay_payment_id}</p> : null}{order.shiprocket_order_id ? <p>Shiprocket: {order.shiprocket_order_id}{order.shipment_id ? ` · Shipment ${order.shipment_id}` : ""}</p> : null}</details>
            <ShiprocketPanel order={order} pkg={packages[order.id] || emptyPackage} reconcileId={reconcileIds[order.id] || ""} locked={locked}
              onPackage={pkg => setPackages(previous => ({ ...previous, [order.id]: pkg }))} onReconcileId={value => setReconcileIds(previous => ({ ...previous, [order.id]: value }))}
              onSubmit={() => void action(order, false)} onRecover={() => void action(order, true)} onRelease={() => void release(order)} />
            <OrderActions order={order} stores={stores} accounts={accounts} locked={locked} onDone={async note => { if (note) setMessage(note); await refreshOrders(); }} onError={failure => setError(failure)} />
            {order.shipping_error && order.shipping_provider !== "shiprocket" ? <p role="alert" className="ops-error">{order.shipping_error}</p> : null}
            <div className="shop-actions order-provider-actions">
              {canVerifyPayment(order) ? <button className="btn light" disabled={locked} onClick={() => {
                setBusy(true); setError("");
                void accountRequest(`/orders/${order.id}/reconcile-payment`, { method: "POST" }, "checkout-admin").then(refreshOrders).catch(failure => setError(String(failure))).finally(() => setBusy(false));
              }}>Verify payment with Razorpay</button> : null}</div>
          </article>)}
        </>}
        <div className="shop-actions checkout-pagination"><button disabled={offset === 0 || locked} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><span>Page {offset / 50 + 1}</span><button disabled={orders.length < 50 || locked || !ordersLoaded} onClick={() => setOffset(offset + 50)}>Next</button></div>
        <p className="checkout-fine-print">Self-shipping: arrange your own courier, dispatch &amp; invoice, then mark delivered. For Shiprocket orders, submission alone is not delivery confirmation; manage AWB and pickup in Shiprocket.</p>
      </section> : null}
      {!setupOnly && tab === "cod" ? <section className="checkout-orders-section">
        <div className="checkout-orders-heading"><div><h2>Cash on delivery</h2><p>Dispatched COD invoices stay open until the courier remits. Record each remittance against its orders; shortfalls need a reason.</p></div><button className="btn light" disabled={locked} onClick={() => void refreshCod().catch(failure => setError(String(failure)))}>Refresh</button></div>
        {!cod ? <p role="status">Loading...</p> : <>
          <p>Outstanding: <strong>{rupees(Math.round(Number(cod.total_outstanding) * 100))}</strong></p>
          <form className="ops-form" onSubmit={event => { event.preventDefault(); setBusy(true); setError(""); setMessage("");
            const items = Object.entries(settlementItems).filter(([, amount]) => Number(amount) > 0).map(([order_id, amount]) => ({ order_id, amount: Number(amount) }));
            void accountRequest("/cod/settlements", { method: "POST", body: JSON.stringify({ ...settlement, shortfall_reason: settlement.shortfall_reason || null, notes: settlement.notes || null, items }) }, "checkout-admin")
              .then(() => { setMessage("Settlement recorded and collections posted."); setSettlementItems({}); setSettlement({ ...settlement, settlement_reference: "", shortfall_reason: "", notes: "" }); return refreshCod(); })
              .catch(failure => setError(String(failure))).finally(() => setBusy(false)); }}>
            <div className="company-fields">
              <label>Courier<input required maxLength={80} value={settlement.courier} onChange={event => setSettlement({ ...settlement, courier: event.target.value })} /></label>
              <label>Remittance reference / UTR<input required maxLength={120} value={settlement.settlement_reference} onChange={event => setSettlement({ ...settlement, settlement_reference: event.target.value })} /></label>
              <label>Date<input type="date" required value={settlement.settlement_date} onChange={event => setSettlement({ ...settlement, settlement_date: event.target.value })} /></label>
              <label>Received into<select required value={settlement.account_id} onChange={event => setSettlement({ ...settlement, account_id: event.target.value })}><option value="">Account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label>
              <label>Shortfall reason (if less than expected)<input maxLength={500} value={settlement.shortfall_reason} onChange={event => setSettlement({ ...settlement, shortfall_reason: event.target.value })} /></label>
            </div>
            <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Invoice</th><th>Dispatched</th><th>Days</th><th>Total</th><th>Outstanding</th><th>Received now</th></tr></thead>
              <tbody>{cod.items.length ? cod.items.map(row => <tr key={row.order_id} className={row.overdue ? "ops-error" : undefined}><td>{row.invoice_number}</td><td>{row.dispatched_at ? new Date(row.dispatched_at).toLocaleDateString() : ""}</td><td>{row.days_since_dispatch ?? ""}{row.overdue ? " · overdue" : ""}</td><td>{Number(row.total).toFixed(2)}</td><td>{Number(row.outstanding).toFixed(2)}</td>
                <td><input aria-label={`Received for ${row.invoice_number}`} type="number" min={0} step="0.01" value={settlementItems[row.order_id] || ""} onChange={event => setSettlementItems({ ...settlementItems, [row.order_id]: event.target.value })} /></td></tr>) : <tr><td colSpan={6}>No open COD invoices.</td></tr>}</tbody></table></div>
            <button className="btn" disabled={locked || !Object.values(settlementItems).some(value => Number(value) > 0)}>Record settlement</button>
          </form>
          <h3>Recent settlements</h3>
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Date</th><th>Courier</th><th>Reference</th><th>Expected</th><th>Received</th>          <th>Shortfall reason</th><th>Actions</th></tr></thead>
                      <tbody>{cod.settlements.length ? cod.settlements.map(row => <tr key={row.id}><td>{row.settlement_date}</td><td>{row.courier}</td><td>{row.settlement_reference}</td><td>{Number(row.expected_amount).toFixed(2)}</td><td>{Number(row.received_amount).toFixed(2)}</td><td>{row.shortfall_reason || ""}</td>
                        <td>{allowed ? <button type="button" className="ops-link-btn" onClick={() => setSettlementDelete(row)}>Delete</button> : null}</td></tr>) : <tr><td colSpan={7}>No settlements yet.</td></tr>}</tbody></table></div>
                    {settlementDelete ? <DeleteTransactionDialog kind="cod_settlement" id={settlementDelete.id} title={`COD settlement ${settlementDelete.settlement_reference}`}
                      onClose={() => setSettlementDelete(null)} onDone={async result => { setSettlementDelete(null); setMessage(`Deleted ${result.label}.`); await refreshCod(); }} /> : null}
        </>}
      </section> : null}
      {!setupOnly && tab === "enquiries" ? <section className="checkout-orders-section">
        <div className="checkout-orders-heading"><div><h2>WhatsApp enquiries</h2><p>Recorded when shoppers tap &quot;Ask this store&quot;. Convert to an invoice from Billing, then link it here.</p></div><button className="btn light" disabled={locked} onClick={() => void refreshEnquiries().catch(failure => setError(String(failure)))}>Refresh</button></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Ref</th><th>When</th><th>Product</th><th>Qty</th><th>Shopper</th><th>Store</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{enquiries.length ? enquiries.map(row => <tr key={row.id}><td>{row.reference}</td><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.product_name}{row.variant_name ? ` - ${row.variant_name}` : ""}{row.message ? <small> · {row.message}</small> : null}</td><td>{Number(row.quantity)}</td><td>{row.shopper_name}<br /><a href={`https://wa.me/${row.shopper_phone.replace("+", "")}`} target="_blank" rel="noopener noreferrer">{row.shopper_phone}</a></td><td>{row.store_code || ""}</td><td>{row.status}</td>
            <td>{row.status !== "converted" ? <span className="shop-actions">
              {["quoted", "closed"].filter(value => value !== row.status).map(value => <button key={value} type="button" className="ops-link-btn" disabled={locked} onClick={() => void accountRequest(`/enquiries/${row.id}`, { method: "PUT", body: JSON.stringify({ status: value }) }, "checkout-admin").then(refreshEnquiries).catch(failure => setError(String(failure)))}>{value}</button>)}
              <input aria-label={`Invoice id for ${row.reference}`} placeholder="Invoice ID" value={enquiryInvoice[row.id] || ""} onChange={event => setEnquiryInvoice({ ...enquiryInvoice, [row.id]: event.target.value })} />
              <button type="button" className="ops-link-btn" disabled={locked || !enquiryInvoice[row.id]} onClick={() => void accountRequest(`/enquiries/${row.id}`, { method: "PUT", body: JSON.stringify({ status: "converted", invoice_id: enquiryInvoice[row.id] }) }, "checkout-admin").then(refreshEnquiries).catch(failure => setError(String(failure)))}>Mark converted</button>
            </span> : <span>Invoice {row.invoice_id}</span>}</td></tr>) : <tr><td colSpan={8}>No enquiries.</td></tr>}</tbody></table></div>
      </section> : null}
    </div>
  </main>;
}
