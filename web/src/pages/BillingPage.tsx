import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { TaxLinesEditor, calculateLineTotals, newTaxLine as newLine } from "../components/TaxLinesEditor";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { api } from "../api";
import { postingKey } from "../features/postingKey";
import type { InventoryProduct } from "../types";
import type { Account, HsnMaster, Invoice, InvoiceLineInput, InvoiceReconcileRun, Party } from "../types";

type InvoiceForm = {
  customer_party_id: string;
  invoice_date: string;
  billing_address: string;
  shipping_name: string;
  shipping_address: string;
  place_of_supply: string;
  payment_mode: string;
  account_id: string;
  reference: string;
  due_date: string;
  reminder_date: string;
  amount_received: string;
  notes: string;
  auto_create_receivable: boolean;
};

const EMPTY_FORM: InvoiceForm = {
  customer_party_id: "",
  invoice_date: "",
  billing_address: "",
  shipping_name: "",
  shipping_address: "",
  place_of_supply: "",
  payment_mode: "",
  account_id: "",
  reference: "",
  due_date: "",
  reminder_date: "",
  amount_received: "0",
  notes: "",
  auto_create_receivable: true,
};

const SUPPLY_STATES = [
  "01 - Jammu and Kashmir", "02 - Himachal Pradesh", "03 - Punjab", "04 - Chandigarh",
  "05 - Uttarakhand", "06 - Haryana", "07 - Delhi", "08 - Rajasthan", "09 - Uttar Pradesh",
  "10 - Bihar", "11 - Sikkim", "12 - Arunachal Pradesh", "13 - Nagaland", "14 - Manipur",
  "15 - Mizoram", "16 - Tripura", "17 - Meghalaya", "18 - Assam", "19 - West Bengal",
  "20 - Jharkhand", "21 - Odisha", "22 - Chhattisgarh", "23 - Madhya Pradesh", "24 - Gujarat",
  "26 - Dadra and Nagar Haveli and Daman and Diu", "27 - Maharashtra", "29 - Karnataka",
  "30 - Goa", "31 - Lakshadweep", "32 - Kerala", "33 - Tamil Nadu", "34 - Puducherry",
  "35 - Andaman and Nicobar Islands", "36 - Telangana", "37 - Andhra Pradesh", "38 - Ladakh",
];

export function BillingPage() {
  const reconcilePageSize = 10;
  const [parties, setParties] = useState<Party[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [inventory,setInventory]=useState<InventoryProduct[]>([]);
  const [requestKey,setRequestKey]=useState(postingKey);
  const [hsnMasters, setHsnMasters] = useState<HsnMaster[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [collectionStatus, setCollectionStatus] = useState("");
  const [form, setForm] = useState<InvoiceForm>(EMPTY_FORM);
  const [lines, setLines] = useState<InvoiceLineInput[]>([newLine()]);
  const [sameShipping, setSameShipping] = useState(true);
  const [pdfBusy, setPdfBusy] = useState<string | null>(null);
  const [reconcileRuns, setReconcileRuns] = useState<InvoiceReconcileRun[]>([]);
  const [reconcileOffset, setReconcileOffset] = useState(0);
  const [reconcileTotal, setReconcileTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { subtotal, gstTotal, total } = calculateLineTotals(lines);

  const exportInvoice = async (invoice: Invoice) => {
    setPdfBusy(invoice.id);
    setError(null);
    try {
      const { downloadInvoicePdf } = await import("../features/invoicePdf");
      await downloadInvoicePdf(invoice);
    } catch (pdfError) {
      setError(pdfError instanceof Error ? pdfError.message : "Unable to generate invoice PDF.");
    } finally {
      setPdfBusy(null);
    }
  };

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [partyRes, accountRes, invoiceRes, hsnRes, inventoryRes] = await Promise.all([
        api.parties({ active_only: true }),
        api.accounts({ active_only: true }),
        api.invoices({ collection_status: collectionStatus || undefined }),
        api.hsnMasters(),
        api.inventoryProducts(),
      ]);
      const runsRes = await api.invoiceReconcileRuns(reconcilePageSize, reconcileOffset);
      setParties(partyRes.items.filter((party) => party.party_type !== "vendor"));
      setAccounts(accountRes.items);
      setInventory(inventoryRes.items);
      setHsnMasters(hsnRes.items);
      setInvoices(invoiceRes.items);
      setReconcileRuns(runsRes.items);
      setReconcileTotal(runsRes.total);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load billing data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [collectionStatus, reconcileOffset]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);

    try {
      const amountReceived = Number(form.amount_received || 0);

      if (!form.customer_party_id) throw new Error("Select customer party.");
      if (lines.some((line) => !hsnMasters.some((master) => master.code === line.hsn))) {
        throw new Error("Select an active HSN / SAC code for every item.");
      }
      if (!subtotal || subtotal < 0) throw new Error("Subtotal must be greater than or equal to zero.");
      if (total <= 0) throw new Error("Total must be greater than zero.");
      if (amountReceived < 0) throw new Error("Amount received cannot be negative.");
      if (amountReceived > 0 && !form.payment_mode) {
        throw new Error("Payment mode is required when amount received is entered.");
      }
      if (amountReceived > 0 && !form.account_id) {
        throw new Error("Select account where amount was received.");
      }

      await api.createInvoice({
        idempotency_key:requestKey,
        customer_party_id: form.customer_party_id,
        invoice_date: form.invoice_date || undefined,
        subtotal,
        gst_total: gstTotal,
        total,
        payment_mode: form.payment_mode || undefined,
        account_id: form.account_id || undefined,
        reference: form.reference || undefined,
        due_date: form.due_date || undefined,
        reminder_date: form.reminder_date || undefined,
        amount_received: amountReceived,
        notes: form.notes || undefined,
        auto_create_receivable: form.auto_create_receivable,
        lines,
        billing_address: form.billing_address,
        place_of_supply: form.place_of_supply,
        shipping_name: sameShipping ? undefined : form.shipping_name,
        shipping_address: sameShipping ? undefined : form.shipping_address,
      });

      setForm(EMPTY_FORM);
      setRequestKey(postingKey());
      setLines([newLine()]);
      setSameShipping(true);
      setMessage("Invoice posted. PDF is available in the invoice list.");
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to create invoice.");
    } finally {
      setSaving(false);
    }
  };

  const reconcileInvoices = async () => {
    setReconciling(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.reconcileInvoices("operations_user");
      setMessage(`Reconciliation complete. Healed ${result.healed_count} invoice records.`);
      await load();
    } catch (reconcileError) {
      setError(
        reconcileError instanceof Error ? reconcileError.message : "Unable to reconcile invoices."
      );
    } finally {
      setReconciling(false);
    }
  };

  const exportReconcileRunsCsv = () => {
    if (reconcileRuns.length === 0) {
      setMessage("No reconcile runs available for export on this page.");
      return;
    }
    const header = ["run_at", "healed_count", "triggered_by"];
    const rows = reconcileRuns.map((run) => [
      run.created_at,
      String(run.healed_count),
      run.triggered_by || "",
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(","))
      .join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `billing_reconcile_runs_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setMessage("Reconcile audit CSV exported.");
  };

  const exportSalesRegisterCsv = () => {
    void (async () => {
      setError(null);
      setMessage(null);
      try {
        const blob = await api.exportSalesRegisterCsv();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `sales_register_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setMessage("Sales register exported.");
      } catch (exportError) {
        setError(exportError instanceof Error ? exportError.message : "Unable to export sales register.");
      }
    })();
  };

  return (
    <div className="ops-page billing-page">
      <section className="ops-hero">
        <PortalHomeLink />
        <p className="eyebrow">Operations</p>
        <h1>Billing</h1>
        <p>
          Post sales invoices and automatically create receivables with collection status,
          reminders, and account-mode confirmation when amount is received.
        </p>
      </section>

      <section className="ops-grid">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Create Invoice</h2>
          </div>

          {error ? <p className="ops-error">{error}</p> : null}
          {message ? <p className="ops-success-banner">{message}</p> : null}

          <form className="ops-form" onSubmit={submit}>
            <label>
              Customer
              <select
                value={form.customer_party_id}
                onChange={(event) =>
                  setForm((prev) => {
                    const customer = parties.find((party) => party.id === event.target.value);
                    return {
                      ...prev,
                      customer_party_id: event.target.value,
                      billing_address: customer?.address || "",
                      place_of_supply: SUPPLY_STATES.find((state) => state.startsWith(`${customer?.gst_number?.slice(0, 2)} - `)) || "",
                    };
                  })
                }
                required
              >
                <option value="">Select customer</option>
                {parties.map((party) => (
                  <option key={party.id} value={party.id}>
                    {party.legal_name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Invoice Date
              <input
                type="date"
                value={form.invoice_date}
                onChange={(event) => setForm((prev) => ({ ...prev, invoice_date: event.target.value }))}
              />
            </label>

            <label>
              Bill To Address
              <textarea required rows={3} value={form.billing_address}
                onChange={(event) => setForm((prev) => ({ ...prev, billing_address: event.target.value }))} />
            </label>
            <label>
              Place of Supply
              <select required value={form.place_of_supply}
                onChange={(event) => setForm((prev) => ({ ...prev, place_of_supply: event.target.value }))}>
                <option value="">Select state</option>
                {SUPPLY_STATES.map((state) => <option key={state} value={state}>{state}</option>)}
              </select>
            </label>
            <label className="ops-toggle">
              <input type="checkbox" checked={sameShipping} onChange={(event) => setSameShipping(event.target.checked)} />
              Ship to billing address
            </label>
            {!sameShipping && <>
              <label>
                Ship To Name
                <input required value={form.shipping_name}
                  onChange={(event) => setForm((prev) => ({ ...prev, shipping_name: event.target.value }))} />
              </label>
              <label>
                Ship To Address
                <textarea required rows={3} value={form.shipping_address}
                  onChange={(event) => setForm((prev) => ({ ...prev, shipping_address: event.target.value }))} />
              </label>
            </>}
            <TaxLinesEditor lines={lines} masters={hsnMasters} products={inventory} onChange={setLines} disabled={saving} />

            <label>
              Amount Received Now
              <input
                type="number"
                step="0.01"
                value={form.amount_received}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, amount_received: event.target.value }))
                }
              />
            </label>

            <label>
              Payment Mode
              <input
                value={form.payment_mode}
                onChange={(event) => setForm((prev) => ({ ...prev, payment_mode: event.target.value }))}
                placeholder="cash / bank / upi"
              />
            </label>

            <label>
              Received In Account
              <select
                value={form.account_id}
                onChange={(event) => setForm((prev) => ({ ...prev, account_id: event.target.value }))}
              >
                <option value="">No account posting</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.nickname}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Due Date
              <input
                type="date"
                value={form.due_date}
                onChange={(event) => setForm((prev) => ({ ...prev, due_date: event.target.value }))}
              />
            </label>

            <label>
              Reminder Date
              <input
                type="date"
                value={form.reminder_date}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, reminder_date: event.target.value }))
                }
              />
            </label>

            <label>
              Reference
              <input
                value={form.reference}
                onChange={(event) => setForm((prev) => ({ ...prev, reference: event.target.value }))}
              />
            </label>

            <label>
              Notes
              <textarea
                rows={3}
                value={form.notes}
                onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))}
              />
            </label>

            <label className="ops-toggle">
              <input
                type="checkbox"
                checked={form.auto_create_receivable}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, auto_create_receivable: event.target.checked }))
                }
              />
              Auto-create receivable for unpaid balance
            </label>

            <button className="btn" type="submit" disabled={saving || loading || !hsnMasters.length}>
              {saving ? "Saving..." : "Post Invoice"}
            </button>
          </form>
        </article>

        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Invoices</h2>
            <span className="catalog-count">{invoices.length} records</span>
          </div>

          <div className="ops-list-tools">
            <select value={collectionStatus} onChange={(event) => setCollectionStatus(event.target.value)}>
              <option value="">All Collection Status</option>
              <option value="UNPAID">UNPAID</option>
              <option value="PARTIAL">PARTIAL</option>
              <option value="SETTLED">SETTLED</option>
              <option value="BAD_DEBT">BAD_DEBT</option>
            </select>
            <button className="btn" type="button" onClick={() => void reconcileInvoices()} disabled={reconciling}>
              {reconciling ? "Reconciling..." : "Reconcile Now"}
            </button>
            <button className="btn" type="button" onClick={() => void load()}>
              Refresh
            </button>
            <button className="btn" type="button" onClick={exportSalesRegisterCsv}>
              Export Sales Register
            </button>
          </div>

          {loading ? <p>Loading...</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Invoice #</th>
                  <th>Date</th>
                  <th>Customer</th>
                  <th>Total</th>
                  <th>Received</th>
                  <th>Status</th>
                  <th>Due</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {invoices.length === 0 ? (
                  <tr>
                    <td colSpan={8}>No invoices found.</td>
                  </tr>
                ) : (
                  invoices.map((item) => (
                    <tr key={item.id}>
                      <td>{item.invoice_number}</td>
                      <td>{item.invoice_date}</td>
                      <td>{item.customer_name}</td>
                      <td>{item.total.toFixed(2)}</td>
                      <td>{item.amount_received.toFixed(2)}</td>
                      <td>{item.status==='CANCELLED'?'CANCELLED':item.collection_status}</td>
                      <td>{item.due_date || "-"}</td>
                      <td>
                        <button className="ops-link-btn" type="button"
                          title={item.document_data ? "Download tax invoice PDF" : "Legacy invoice has no saved product details"}
                          aria-label={`Download PDF for ${item.invoice_number}`}
                          disabled={!item.document_data || pdfBusy !== null}
                          onClick={() => void exportInvoice(item)}>
                          <Download size={16} aria-hidden="true" /> {pdfBusy === item.id ? "Generating..." : "PDF"}
                        </button>
                        {item.status!=='CANCELLED'&&item.amount_received===0?<button type="button" className="ops-link-btn" onClick={()=>{const reason=window.prompt('Reason for cancellation (stock is returned; no refund is issued):');if(reason?.trim())void api.cancelInvoice(item.id,reason).then(()=>load()).catch(failure=>setError(String(failure)));}}>Cancel Invoice</button>:null}
                        {item.status!=='CANCELLED'&&(item.collection_status === "UNPAID" ||
                          item.collection_status === "PARTIAL") && (
                          <Link
                            className="ops-link-btn"
                            to={`/portal/receivables?invoice_id=${encodeURIComponent(item.id)}`}
                          >
                            Collect
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Reconcile Audit</h2>
            <span className="catalog-count">{reconcileTotal} runs</span>
          </div>

          <div className="ops-list-tools">
            <button
              className="btn"
              type="button"
              onClick={() => setReconcileOffset((prev) => Math.max(prev - reconcilePageSize, 0))}
              disabled={reconcileOffset === 0}
            >
              Prev
            </button>
            <button
              className="btn"
              type="button"
              onClick={() => setReconcileOffset((prev) => prev + reconcilePageSize)}
              disabled={reconcileOffset + reconcileRuns.length >= reconcileTotal}
            >
              Next
            </button>
            <button className="btn" type="button" onClick={() => exportReconcileRunsCsv()}>
              Export CSV
            </button>
            <span className="catalog-count">
              Showing {reconcileRuns.length === 0 ? 0 : reconcileOffset + 1}-
              {reconcileOffset + reconcileRuns.length}
            </span>
          </div>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Run At</th>
                  <th>Healed</th>
                  <th>Triggered By</th>
                </tr>
              </thead>
              <tbody>
                {reconcileRuns.length === 0 ? (
                  <tr>
                    <td colSpan={3}>No reconcile runs yet.</td>
                  </tr>
                ) : (
                  reconcileRuns.map((run) => (
                    <tr key={run.id}>
                      <td>{run.created_at}</td>
                      <td>{run.healed_count}</td>
                      <td>{run.triggered_by || "-"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </div>
  );
}
