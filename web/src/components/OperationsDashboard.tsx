import { useEffect, useState } from "react";
import { FloatingAlert } from "./Notifications";
import { Link } from "react-router-dom";
import { ClipboardList, Package, RefreshCw, ShoppingBag, Truck } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../features/auth";
import { toAssetUrl } from "../features/catalog/utils";
import type { OperationsDashboard as Dashboard, Store } from "../types";

const quantity = (value: number) => value.toLocaleString("en-IN", { maximumFractionDigits: 3 });
const money = (value: number) => value.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const localDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

export function OperationsDashboard() {
  const { user } = useAuth();
  const [period, setPeriod] = useState<"month" | "day" | "range">("month");
  const [month, setMonth] = useState(() => localDate().slice(0, 7));
  const [day, setDay] = useState(localDate);
  const [fromDate, setFromDate] = useState(() => `${localDate().slice(0, 7)}-01`);
  const [toDate, setToDate] = useState(localDate);
  const [storeId, setStoreId] = useState("");
  const [stores, setStores] = useState<Store[]>([]);
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    if ((period === "month" && !month) || (period === "day" && !day) ||
        (period === "range" && (!fromDate || !toDate || fromDate > toDate))) {
      setLoading(false); setData(null); setError("Choose a valid reporting date or date range.");
      return () => { active = false; };
    }
    setLoading(true); setError(""); setData(null);
    const dates = period === "month" ? { month: `${month}-01` } :
      period === "day" ? { from_date: day, to_date: day } : { from_date: fromDate, to_date: toDate };
    void Promise.all([api.dashboard(dates, storeId), api.stores()]).then(([summary, locations]) => {
      if (active) { setData(summary); setStores(locations.items); }
    }).catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "Unable to load dashboard."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [period, month, day, fromDate, toDate, storeId, revision, user?.company_id, user?.role, user?.modules, user?.store_ids]);
  const inventory = data?.inventory;
  const activePercent = inventory?.total_products ? Math.round(inventory.active_products * 100 / inventory.total_products) : 0;
  const activity = data?.orders ? [
    { label: "To confirm", value: data.orders.to_confirm, icon: ClipboardList, tone: "amber" },
    { label: "To ship", value: data.orders.to_ship, icon: Package, tone: "blue" },
    { label: "To deliver", value: data.orders.to_deliver, icon: Truck, tone: "green" },
    { label: "To invoice", value: data.orders.to_invoice, icon: ClipboardList, tone: "blue" },
    { label: "To collect", value: data.orders.to_collect, icon: ShoppingBag, tone: "green" },
    { label: "Needs review", value: data.orders.needs_review, icon: ClipboardList, tone: "red" },
  ] : [];
  return <section className="operations-dashboard" aria-labelledby="dashboard-title" aria-busy={loading}>
    <header className="ops-hero dashboard-hero">
      <Link className="portal-home-link" to="/portal">Back to Operations Portal</Link>
      <div className="dashboard-heading">
        <div className="dashboard-title-block"><h1 id="dashboard-title">Operations dashboard</h1><p>Live records from your accessible modules and stores.</p></div>
      <div className="dashboard-filters"><label>Store<select value={storeId} onChange={event => setStoreId(event.target.value)}><option value="">All accessible stores</option>{stores.map(store => <option key={store.id} value={store.id}>{store.name}{!store.is_active ? " (inactive)" : ""}</option>)}</select></label>
        <label>Reporting period<select value={period} onChange={event => setPeriod(event.target.value as "month" | "day" | "range")}><option value="month">Monthly</option><option value="day">Daily</option><option value="range">Date range</option></select></label>
        {period === "month" ? <label>Reporting month<input type="month" required value={month} onChange={event => setMonth(event.target.value)} /></label> : null}
        {period === "day" ? <label>Reporting date<input type="date" required value={day} onChange={event => setDay(event.target.value)} /></label> : null}
        {period === "range" ? <><label>From date<input type="date" required value={fromDate} onChange={event => setFromDate(event.target.value)} /></label><label>To date<input type="date" required value={toDate} onChange={event => setToDate(event.target.value)} /></label></> : null}
        <button type="button" className="btn light" aria-label="Refresh dashboard" disabled={loading} onClick={() => setRevision(value => value + 1)}><RefreshCw size={17} />Refresh</button></div>
      </div>
    </header>
    <div className="dashboard-content">
    {error ? <FloatingAlert>{error} <button type="button" className="ops-link-btn" onClick={() => setRevision(value => value + 1)}>Retry</button></FloatingAlert> : null}
    {loading ? <p className="dashboard-loading" role="status">Loading dashboard...</p> : data ? <>
      {data.sales || data.purchases || data.outflow ? <article className="dashboard-panel dashboard-financial-summary">
        <h3>{period === "day" ? "Daily" : period === "month" ? "Monthly" : "Date range"} financial overview</h3>
        <p className="dashboard-caption">Selected period: {data.from_date} to {data.to_date}, inclusive.</p>
        <div className="dashboard-totals">
          {data.sales ? <Link to="/portal/billing"><span>Sales invoiced</span><strong>{money(data.sales.total)}</strong><small>{data.sales.invoices} invoices</small></Link> : null}
          {data.purchases ? <Link to="/portal/purchases"><span>Purchase bills</span><strong>{money(data.purchases.total)}</strong><small>{data.purchases.bills} bills</small></Link> : null}
          {data.trading_result !== null ? <div className="dashboard-total"><span>Estimated profit / loss</span><strong>{money(data.trading_result)}</strong><small>Sales minus purchases</small></div> : null}
          {data.outflow ? <Link to="/portal/accounts"><span>Account outflow</span><strong>{money(data.outflow.total)}</strong><small>{data.outflow.entries} payments · workspace-wide</small></Link> : null}
        </div>
        {data.trading_result !== null ? <p className="dashboard-caption">Estimate only: invoice totals minus purchase bill totals, including tax. Not accounting profit: it excludes cost of goods sold, other expenses and inventory changes.</p> : null}
        {data.outflow ? <p className="dashboard-caption">Outflow is gross money paid from accounts, excluding transfers. Reversals are incoming transactions and do not reduce this figure. Outflow may include purchase payments and is not subtracted again above.</p> : storeId ? <p className="dashboard-caption">Account outflows are workspace-wide and unavailable for a single store.</p> : null}
      </article> : null}
      <div className="dashboard-activity-row">
        {data.orders ? <article className="dashboard-panel dashboard-activity"><h3>Sales activity</h3><p className="dashboard-caption">Pending online / WhatsApp orders, across all dates. Counts are orders, not item quantities.</p><div className="dashboard-activity-grid">{activity.map(item => <Link key={item.label} className={`dashboard-activity-card ${item.tone}`} to="/portal/checkout"><strong>{quantity(item.value)}</strong><span>orders</span><h4><item.icon size={15} />{item.label}</h4></Link>)}</div></article> : null}
        {inventory || data.purchases ? <article className="dashboard-panel dashboard-inventory-summary"><h3>Inventory summary</h3>{inventory ? <div className="dashboard-summary-line"><span>Quantity in hand</span><strong>{quantity(inventory.quantity_in_hand)}</strong></div> : null}
          {data.purchases ? <><div className="dashboard-summary-line"><span>Quantity to receive</span><strong>{quantity(data.purchases.quantity_to_receive)}</strong></div><Link className="dashboard-caption" to="/portal/purchases">{data.purchases.pending_receipts} pending purchase receipts</Link></> : null}
          <p className="dashboard-caption">Recorded quantities; mixed units are not a stock valuation. Pending receipts include all dates and exclude services.</p></article> : null}
      </div>
      <div className="dashboard-details-row">
        {inventory ? <article className="dashboard-panel"><h3>Product details</h3><div className="dashboard-product-details"><dl><div className="dashboard-low"><dt><Link to="/portal/inventory?view=alerts">Low stock items</Link></dt><dd>{quantity(inventory.low_stock_items)}</dd></div><div><dt>Active categories</dt><dd>{quantity(inventory.categories)}</dd></div><div><dt>All products</dt><dd>{quantity(inventory.total_products)}</dd></div><div><dt>Inactive products</dt><dd>{quantity(inventory.total_products - inventory.active_products)}</dd></div></dl>
          <div className="dashboard-donut-wrap"><div className="dashboard-donut" style={{ background: `conic-gradient(#059669 ${activePercent}%, #e8edf2 0)` }} role="img" aria-label={`${activePercent}% of products active`}><strong>{activePercent}%</strong></div><span>Active products</span></div></div><p className="dashboard-caption">Catalogue counts are workspace-wide. Low stock uses accessible-store balances and enabled reorder levels, including variants.</p></article> : null}
        {data.sales ? <article className="dashboard-panel"><div className="dashboard-panel-heading"><h3>Top selling items</h3><Link to="/portal/billing">View sales</Link></div>{data.sales.top_items.length ? <div className="dashboard-top-items">{data.sales.top_items.map(item => <Link key={item.product_id} to="/portal/billing" className="dashboard-top-item">{item.image_url ? <img src={toAssetUrl(item.image_url)} alt={item.name} loading="lazy" /> : <div className="dashboard-image-placeholder"><Package size={32} /></div>}<span title={item.name}>{item.name}</span><strong>{quantity(item.quantity)} <small>{item.uom}</small></strong></Link>)}</div> : <p className="dashboard-empty">No itemised posted sales in this period. Cancelled invoices are excluded.</p>}<p className="dashboard-caption">Ranked by billed quantity in the selected period, not revenue.</p></article> : null}
      </div>
      <div className="dashboard-details-row">
        {data.orders ? <article className="dashboard-panel"><h3>Sales orders by channel</h3><p className="dashboard-caption">Orders created in the reporting period, grouped by their current status. Expired holds are closed.</p>{data.orders.channels.length ? <div className="dashboard-table-wrap"><table className="ops-table"><thead><tr>{["Channel", "Awaiting payment", "Confirmed / paid", "To ship", "Dispatched", "Ready for pickup", "Review", "Completed", "Closed"].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{data.orders.channels.map(row => <tr key={row.channel}><th scope="row">{row.channel === "web" ? "Online store" : "WhatsApp"}</th>{[row.awaiting_payment, row.confirmed, row.to_ship, row.dispatched, row.ready_for_pickup, row.needs_review, row.completed, row.closed].map((value, index) => <td key={index}>{quantity(value)}</td>)}</tr>)}</tbody></table></div> : <p className="dashboard-empty">No online or WhatsApp orders in this period.</p>}</article> : null}
      </div>
      <div className="portal-kpi-grid">
        {data.receivables ? <><Link className="portal-kpi-card portal-kpi-link" to="/portal/receivables?status=OPEN"><p>Open receivables</p><strong>{data.receivables.open}</strong>{data.receivables.outstanding !== undefined ? <span className="dashboard-caption">{money(data.receivables.outstanding)} outstanding</span> : null}</Link><Link className="portal-kpi-card portal-kpi-link" to="/portal/receivables?focus=reminders"><p>Reminders due</p><strong>{data.receivables.reminders_due}</strong></Link><Link className="portal-kpi-card portal-kpi-link" to="/portal/receivables?status=BAD_DEBT"><p>Bad debt cases</p><strong>{data.receivables.bad_debt}</strong></Link></> : null}
        {data.borrowing_outstanding !== null ? <Link className="portal-kpi-card portal-kpi-link" to="/portal/settlements"><p>Net borrowing outstanding</p><strong>{money(data.borrowing_outstanding)}</strong><span className="dashboard-caption">Workspace-wide, all dates</span></Link> : null}
                {data.refunds_pending ? <><Link className="portal-kpi-card portal-kpi-link" to="/portal/settlements/refunds"><p>Refunds to pay customers</p><strong>{money(data.refunds_pending.customer_amount)}</strong><span className="dashboard-caption">{data.refunds_pending.customer_count} awaiting settlement</span></Link><Link className="portal-kpi-card portal-kpi-link" to="/portal/settlements/refunds"><p>Vendor refunds to receive</p><strong>{money(data.refunds_pending.vendor_amount)}</strong><span className="dashboard-caption">{data.refunds_pending.vendor_count} awaiting settlement</span></Link></> : null}
              </div>
              {!data.inventory && !data.orders && !data.purchases && !data.sales && !data.outflow && !data.receivables && data.borrowing_outstanding === null && !data.refunds_pending ? <p className="dashboard-empty">No dashboard modules are assigned to your account. Your available modules are listed below.</p> : null}
    </> : null}
    </div>
  </section>;
}
