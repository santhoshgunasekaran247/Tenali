import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { FloatingAlert } from "../components/Notifications";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { refundDirectionLabel } from "../features/cancellation";
import type { Account, RefundSettlement, RefundSummary } from "../types";

const money = (value: number) => `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const today = () => new Date().toLocaleDateString("en-CA");
const MODES = ["cash", "bank", "upi", "card", "cheque", "other"];

type SettleForm = { account_id: string; settled_on: string; payment_mode: string; reference: string; notes: string };

/** Pending refunds from cancelled paid invoices (pay the customer) and bills (vendor pays back), confirmed once settled. */
export function RefundSettlementsPage() {
  const [status, setStatus] = useState<"PENDING" | "SETTLED">("PENDING");
  const [items, setItems] = useState<RefundSettlement[]>([]);
  const [summary, setSummary] = useState<RefundSummary | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [target, setTarget] = useState<RefundSettlement | null>(null);
  const [form, setForm] = useState<SettleForm>({ account_id: "", settled_on: today(), payment_mode: "", reference: "", notes: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const version = useRef(0);

  const load = async () => {
    const current = ++version.current;
    setLoading(true); setError(null);
    try {
      const [refunds, accountList] = await Promise.all([api.refunds(status), api.accounts({ active_only: true })]);
      if (current !== version.current) return;
      setItems(refunds.items); setSummary(refunds.summary); setAccounts(accountList.items);
    } catch (failure) {
      if (current === version.current) setError(failure instanceof Error ? failure.message : "Unable to load refunds.");
    } finally {
      if (current === version.current) setLoading(false);
    }
  };
  useEffect(() => { void load(); }, [status]);
  const formCard = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!target || !formCard.current) return;
    formCard.current.scrollIntoView({ behavior: "instant" as ScrollBehavior, block: "start" });
    formCard.current.querySelector("select")?.focus({ preventScroll: true });
  }, [target]);

  const open = (item: RefundSettlement) => {
    setTarget(item); setMessage(null); setError(null);
    setForm({ account_id: item.account_id || item.original_account_id || "", settled_on: today(),
      payment_mode: item.reversal_payment_mode || item.original_payment_mode || "", reference: "", notes: "" });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!target || !form.account_id) return;
    setBusy(true); setError(null);
    try {
      await api.settleRefund(target.id, { account_id: form.account_id, settled_on: form.settled_on || undefined,
        payment_mode: form.payment_mode || undefined, reference: form.reference || undefined, notes: form.notes || undefined });
      setMessage(`Refund of ${money(target.amount)} for ${target.document_number || "the cancelled document"} confirmed.`);
      setTarget(null);
      await load();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unable to confirm this refund.");
    } finally { setBusy(false); }
  };

  return <div className="ops-page">
    <section className="ops-hero">
      <PortalHomeLink />
      <p className="eyebrow">Operations</p>
      <h1>Refund Settlements</h1>
      <p>Cancelling a paid invoice or bill reverses its payments. Confirm each refund here once the money has actually moved, with the account and mode used.</p>
      <p><Link className="ops-inline-link" to="/portal/settlements">Borrowing &amp; Settlements</Link></p>
    </section>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    {summary ? <div className="portal-kpi-grid">
      <div className="portal-kpi-card"><p>To pay back to customers</p><strong>{money(summary.customer_amount)}</strong><span className="dashboard-caption">{summary.customer_count} pending</span></div>
      <div className="portal-kpi-card"><p>To receive back from vendors</p><strong>{money(summary.vendor_amount)}</strong><span className="dashboard-caption">{summary.vendor_count} pending</span></div>
    </div> : null}
    <section className="ops-grid ops-grid-single">
      <article className="ops-card ops-list-card">
        <div className="ops-card-head"><h2>{status === "PENDING" ? "Pending refunds" : "Settled refunds"}</h2>
          <div className="ops-list-tools"><select aria-label="Refund status" value={status} onChange={event => setStatus(event.target.value as "PENDING" | "SETTLED")}>
            <option value="PENDING">Pending</option><option value="SETTLED">Settled</option></select></div></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr>
          <th>Document</th><th>Party</th><th>Direction</th><th>Amount</th><th>Originally</th><th>{status === "PENDING" ? "Reversed on" : "Settled"}</th><th></th></tr></thead>
          <tbody>{loading ? <tr><td colSpan={7}>Loading refunds...</td></tr> : !items.length ? <tr><td colSpan={7}>{status === "PENDING" ? "No refunds are waiting for confirmation." : "No settled refunds yet."}</td></tr> :
            items.map(item => <tr key={item.id}>
              <td><Link className="ops-inline-link" to={item.document_type === "invoice" ? "/portal/billing" : "/portal/purchases"}>{item.document_type === "invoice" ? "Invoice" : "Bill"} {item.document_number || ""}</Link>{item.reason ? <><br /><small>{item.reason}</small></> : null}</td>
              <td>{item.party_name || "-"}</td>
              <td>{refundDirectionLabel(item.direction)}</td>
              <td>{money(item.amount)}</td>
              <td>{item.original_account_name || "-"} · {item.original_payment_mode || "-"}<br /><small>{item.paid_on}</small></td>
              <td>{status === "PENDING" ? item.reversal_date : <>{item.settled_on} · {item.account_name} · {item.payment_mode || "-"}{item.reference ? <><br /><small>Ref {item.reference}</small></> : null}</>}</td>
              <td>{item.status === "PENDING" ? <button type="button" className="ops-link-btn" onClick={() => open(item)}>Settle / change account</button> : null}</td>
            </tr>)}</tbody></table></div>
      </article>
      {target ? <article className="ops-card" ref={formCard}>
        <div className="ops-card-head"><h2>Confirm refund · {money(target.amount)}</h2>
          <button type="button" className="ops-link-btn" disabled={busy} onClick={() => setTarget(null)}>Close</button></div>
        <p className="ops-copy-note">{refundDirectionLabel(target.direction)} for {target.document_type === "invoice" ? "invoice" : "bill"} {target.document_number}. It was originally {target.direction === "PAY_CUSTOMER" ? "received into" : "paid from"} {target.original_account_name || "an account"} by {target.original_payment_mode || "an unrecorded mode"}. Correct the account and mode if the refund moved differently.</p>
        <form className="ops-form refund-settle-form" onSubmit={submit}>
          <label>{target.direction === "PAY_CUSTOMER" ? "Paid from account" : "Received into account"}
            <select required value={form.account_id} onChange={event => setForm({ ...form, account_id: event.target.value })}>
              <option value="">Select account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname}</option>)}</select></label>
          <label>Mode<select value={form.payment_mode} onChange={event => setForm({ ...form, payment_mode: event.target.value })}>
            <option value="">Same as original</option>{MODES.map(mode => <option key={mode} value={mode}>{mode.toUpperCase()}</option>)}</select></label>
          <label>Settled on<input required type="date" max={today()} value={form.settled_on} onChange={event => setForm({ ...form, settled_on: event.target.value })} /></label>
          <label>Reference<input maxLength={200} value={form.reference} onChange={event => setForm({ ...form, reference: event.target.value })} placeholder="UTR, cheque or receipt number" /></label>
          <label>Notes<textarea maxLength={1000} value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} /></label>
          <div className="shop-actions"><button className="btn" disabled={busy || !form.account_id}>{busy ? "Saving..." : "Confirm settled"}</button></div>
        </form>
      </article> : null}
    </section>
  </div>;
}
