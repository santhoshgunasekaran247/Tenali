import { FormEvent, useEffect, useState } from "react";
import { Paperclip } from "lucide-react";
import { AttachmentManager, AttachmentPicker } from "../components/Attachments";
import { api } from "../api";
import { postingKey } from "../features/postingKey";
import type { InventoryProduct } from "../types";
import { TaxLinesEditor, calculateLineTotals, newTaxLine } from "../components/TaxLinesEditor";
import type { Account, AttachmentInput, HsnMaster, InvoiceLineInput, Party, Purchase, PurchasePayment } from "../types";

type PurchaseForm = {
  vendor_party_id: string;
  purchase_date: string;
  bill_number: string;
  amount_paid: string;
  payment_mode: string;
  account_id: string;
  reference: string;
  due_date: string;
  notes: string;
  receipt_type: "PRODUCT" | "STOCK" | "SERVICE";
};

type PaymentForm = {
  amount: string;
  account_id: string;
  payment_mode: string;
  idempotency_key: string;
  payment_date: string;
  reference: string;
  notes: string;
};

function createIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type ReceiptForm = {
  receipt_type: "PRODUCT" | "STOCK" | "SERVICE";
  received_at: string;
  received_notes: string;
};

const EMPTY_FORM: PurchaseForm = {
  vendor_party_id: "",
  purchase_date: "",
  bill_number: "",
  amount_paid: "0",
  payment_mode: "",
  account_id: "",
  reference: "",
  due_date: "",
  notes: "",
  receipt_type: "PRODUCT",
};

const EMPTY_PAYMENT_FORM: PaymentForm = {
  amount: "",
  account_id: "",
  payment_mode: "",
  idempotency_key: "",
  payment_date: "",
  reference: "",
  notes: "",
};

const EMPTY_RECEIPT_FORM: ReceiptForm = {
  receipt_type: "PRODUCT",
  received_at: "",
  received_notes: "",
};

export function PurchasesPage() {
  const [vendors, setVendors] = useState<Party[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [inventory,setInventory]=useState<InventoryProduct[]>([]);
  const [requestKey,setRequestKey]=useState(postingKey);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [paymentStatus, setPaymentStatus] = useState("");
  const [form, setForm] = useState<PurchaseForm>(EMPTY_FORM);
  const [attachments, setAttachments] = useState<AttachmentInput[]>([]);
  const [attachmentReading, setAttachmentReading] = useState(false);
  const [attachmentTarget, setAttachmentTarget] = useState<Purchase | null>(null);
  const [lines, setLines] = useState<InvoiceLineInput[]>([newTaxLine()]);
  const [hsnMasters, setHsnMasters] = useState<HsnMaster[]>([]);
  const { subtotal, gstTotal, total } = calculateLineTotals(lines);
  const [paymentTarget, setPaymentTarget] = useState<Purchase | null>(null);
  const [paymentForm, setPaymentForm] = useState<PaymentForm>(EMPTY_PAYMENT_FORM);
  const [paymentHistory, setPaymentHistory] = useState<PurchasePayment[]>([]);
  const [paymentHistoryLoading, setPaymentHistoryLoading] = useState(false);
  const [receiptTarget, setReceiptTarget] = useState<Purchase | null>(null);
  const [receiptForm, setReceiptForm] = useState<ReceiptForm>(EMPTY_RECEIPT_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [paying, setPaying] = useState(false);
  const [confirmingReceipt, setConfirmingReceipt] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [partyRes, accountRes, purchaseRes, hsnRes,inventoryRes] = await Promise.all([
        api.parties({ active_only: true }),
        api.accounts({ active_only: true }),
        api.purchases({ payment_status: paymentStatus || undefined }),
        api.hsnMasters(),
        api.inventoryProducts(),
      ]);

      setVendors(
        partyRes.items.filter(
          (party) => party.party_type === "vendor" || party.party_type === "customer_vendor"
        )
      );
      setAccounts(accountRes.items);
      setInventory(inventoryRes.items);
      setHsnMasters(hsnRes.items);
      setPurchases(purchaseRes.items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load purchases data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [paymentStatus]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setSaving(true);

    try {
      const amountPaid = Number(form.amount_paid || 0);

      if (!form.vendor_party_id) throw new Error("Select vendor party.");
      if (lines.some((line) => !hsnMasters.some((master) => master.code === line.hsn))) {
        throw new Error("Select an active HSN / SAC code for every item.");
      }
      if (!subtotal || subtotal < 0) throw new Error("Subtotal must be greater than or equal to zero.");
      if (total <= 0) throw new Error("Total must be greater than zero.");
      if (amountPaid < 0) throw new Error("Amount paid cannot be negative.");
      if (amountPaid > total) throw new Error("Amount paid cannot exceed total.");
      if (amountPaid > 0 && !form.payment_mode) {
        throw new Error("Payment mode is required when amount paid is entered.");
      }
      if (amountPaid > 0 && !form.account_id) {
        throw new Error("Select account from which the purchase payment was made.");
      }

      const created = await api.createPurchase({
        idempotency_key:requestKey,
        attachments,
        lines,
        vendor_party_id: form.vendor_party_id,
        purchase_date: form.purchase_date || undefined,
        bill_number: form.bill_number || undefined,
        subtotal,
        gst_total: gstTotal,
        total,
        amount_paid: amountPaid,
        payment_mode: form.payment_mode || undefined,
        account_id: form.account_id || undefined,
        reference: form.reference || undefined,
        due_date: form.due_date || undefined,
        notes: form.notes || undefined,
        receipt_type: form.receipt_type,
      });

      setForm(EMPTY_FORM);
      setRequestKey(postingKey());
      setAttachments([]);
      setAttachmentTarget(created);
      setLines([newTaxLine()]);
      setMessage("Purchase bill posted.");
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to create purchase.");
    } finally {
      setSaving(false);
    }
  };

  const startReceiptConfirm = (purchase: Purchase) => {
    setReceiptTarget(purchase);
    setReceiptForm({
      receipt_type: purchase.receipt_type,
      received_at: "",
      received_notes: "",
    });
    setError(null);
    setMessage(null);
  };

  const submitReceiptConfirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!receiptTarget) return;

    setConfirmingReceipt(true);
    setError(null);
    setMessage(null);

    try {
      await api.confirmPurchaseReceipt(receiptTarget.id, {
        receipt_type: receiptForm.receipt_type,
        received_at: receiptForm.received_at || undefined,
        received_notes: receiptForm.received_notes || undefined,
      });
      setReceiptTarget(null);
      setReceiptForm(EMPTY_RECEIPT_FORM);
      setMessage("Purchase receipt confirmed.");
      await load();
    } catch (confirmError) {
      setError(
        confirmError instanceof Error
          ? confirmError.message
          : "Unable to confirm purchase receipt."
      );
    } finally {
      setConfirmingReceipt(false);
    }
  };

  const startPayment = async (purchase: Purchase) => {
    setPaymentTarget(purchase);
    setPaymentForm({
      amount: purchase.balance_amount > 0 ? purchase.balance_amount.toFixed(2) : "",
      account_id: "",
      payment_mode: "",
      idempotency_key: createIdempotencyKey("purchase-payment"),
      payment_date: "",
      reference: purchase.reference || "",
      notes: "",
    });
    setPaymentHistoryLoading(true);
    try {
      const response = await api.purchasePayments(purchase.id);
      setPaymentHistory(response.items);
    } catch {
      setPaymentHistory([]);
    } finally {
      setPaymentHistoryLoading(false);
    }
    setError(null);
    setMessage(null);
  };

  const submitPayment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!paymentTarget) return;

    setPaying(true);
    setError(null);
    setMessage(null);
    try {
      const amount = Number(paymentForm.amount);
      if (!amount || amount <= 0) throw new Error("Payment amount must be greater than zero.");
      if (amount - paymentTarget.balance_amount > 0.0001) {
        throw new Error("Payment amount cannot exceed purchase balance.");
      }
      if (!paymentForm.account_id) throw new Error("Select account for payment.");
      if (!paymentForm.payment_mode) throw new Error("Payment mode is required.");

      await api.addPurchasePayment(paymentTarget.id, {
        amount,
        account_id: paymentForm.account_id,
        payment_mode: paymentForm.payment_mode,
        idempotency_key: paymentForm.idempotency_key,
        payment_date: paymentForm.payment_date || undefined,
        reference: paymentForm.reference || undefined,
        notes: paymentForm.notes || undefined,
      });

      setPaymentTarget(null);
      setPaymentForm(EMPTY_PAYMENT_FORM);
      setPaymentHistory([]);
      setMessage("Purchase payment recorded.");
      await load();
    } catch (payError) {
      setError(payError instanceof Error ? payError.message : "Unable to record purchase payment.");
    } finally {
      setPaying(false);
    }
  };

  const exportPurchaseRegisterCsv = () => {
    void (async () => {
      setError(null);
      setMessage(null);
      try {
        const blob = await api.exportPurchaseRegisterCsv();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `purchase_register_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setMessage("Purchase register exported.");
      } catch (exportError) {
        setError(exportError instanceof Error ? exportError.message : "Unable to export purchase register.");
      }
    })();
  };

  const exportApAgingCsv = () => {
    void (async () => {
      setError(null);
      setMessage(null);
      try {
        const blob = await api.exportApAgingCsv();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `ap_aging_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setMessage("AP aging exported.");
      } catch (exportError) {
        setError(exportError instanceof Error ? exportError.message : "Unable to export AP aging.");
      }
    })();
  };

  return (
    <div className="ops-page purchases-page">
      <section className="ops-hero">
        <p className="eyebrow">Operations</p>
        <h1>Purchases</h1>
        <p>
          Record vendor bills and track unpaid balances. Partial or full payment can be posted while
          creating the purchase.
        </p>
      </section>

      <section className="ops-grid">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Create Purchase Bill</h2>
          </div>

          {error ? <p className="ops-error">{error}</p> : null}
          {message ? <p className="ops-success-banner">{message}</p> : null}

          <form className="ops-form" onSubmit={submit}>
            <label>
              Vendor
              <select
                value={form.vendor_party_id}
                onChange={(event) =>
                  {setForm((prev) => ({ ...prev, vendor_party_id: event.target.value }));setLines([newTaxLine()]);}
                }
                required
              >
                <option value="">Select vendor</option>
                {vendors.map((party) => (
                  <option key={party.id} value={party.id}>
                    {party.legal_name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Purchase Date
              <input
                type="date"
                value={form.purchase_date}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, purchase_date: event.target.value }))
                }
              />
            </label>

            <label>
              Bill Number
              <input
                value={form.bill_number}
                onChange={(event) => setForm((prev) => ({ ...prev, bill_number: event.target.value }))}
              />
            </label>

            <TaxLinesEditor lines={lines} masters={hsnMasters} products={inventory} vendorId={form.vendor_party_id} onChange={setLines} disabled={saving} />

            <label>
              Amount Paid Now
              <input
                type="number"
                step="0.01"
                value={form.amount_paid}
                onChange={(event) => setForm((prev) => ({ ...prev, amount_paid: event.target.value }))}
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
              Paid From Account
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

            <label>
              Receipt Type
              <select
                value={form.receipt_type}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    receipt_type: event.target.value as "PRODUCT" | "STOCK" | "SERVICE",
                  }))
                }
              >
                <option value="PRODUCT">Product</option>
                <option value="STOCK">Stock</option>
                <option value="SERVICE">Service</option>
              </select>
            </label>

            <AttachmentPicker value={attachments} onChange={setAttachments} disabled={saving} onBusyChange={setAttachmentReading} />
            <button className="btn" type="submit" disabled={saving || loading || attachmentReading || !hsnMasters.length}>
              {saving ? "Saving..." : "Post Purchase"}
            </button>
          </form>
        </article>

        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Purchase Bills</h2>
            <span className="catalog-count">{purchases.length} records</span>
          </div>

          <div className="ops-list-tools">
            <select value={paymentStatus} onChange={(event) => setPaymentStatus(event.target.value)}>
              <option value="">All Payment Status</option>
              <option value="UNPAID">UNPAID</option>
              <option value="PARTIAL">PARTIAL</option>
              <option value="PAID">PAID</option>
            </select>
            <button className="btn" type="button" onClick={() => void load()}>
              Refresh
            </button>
            <button className="btn" type="button" onClick={exportPurchaseRegisterCsv}>
              Export Purchase Register
            </button>
            <button className="btn" type="button" onClick={exportApAgingCsv}>
              Export AP Aging
            </button>
          </div>

          {loading ? <p>Loading...</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Vendor</th>
                  <th>Bill #</th>
                  <th>Total</th>
                  <th>Paid</th>
                  <th>Balance</th>
                  <th>Status</th>
                  <th>Receipt</th>
                  <th>Due</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {purchases.length === 0 ? (
                  <tr>
                    <td colSpan={10}>No purchases found.</td>
                  </tr>
                ) : (
                  purchases.map((item) => (
                    <tr key={item.id}>
                      <td>{item.purchase_date}</td>
                      <td>{item.vendor_name}</td>
                      <td>{item.bill_number || "-"}</td>
                      <td>{item.total.toFixed(2)}</td>
                      <td>{item.amount_paid.toFixed(2)}</td>
                      <td>{item.balance_amount.toFixed(2)}</td>
                      <td>{item.status==='CANCELLED'?'CANCELLED':item.payment_status}</td>
                      <td>{item.receipt_status === "RECEIVED" ? `${item.receipt_type} RECEIVED` : "PENDING"}</td>
                      <td>{item.due_date || "-"}</td>
                      <td>
                        <div className="ops-list-tools">
                          <button className="ops-link-btn" type="button" title="Receipts and bills" aria-label={`Attachments for purchase ${item.bill_number || item.id}`}
                            onClick={() => setAttachmentTarget(item)}><Paperclip size={16} aria-hidden="true" /> Files</button>
                          {item.status!=='CANCELLED'&&item.amount_paid===0?<button className="ops-link-btn" type="button" onClick={()=>{const reason=window.prompt('Reason for cancellation (received stock is removed; no refund is issued):');if(reason?.trim())void api.cancelPurchase(item.id,reason).then(()=>load()).catch(failure=>setError(String(failure)));}}>Cancel Bill</button>:null}
                          {item.status!=='CANCELLED'&&item.balance_amount > 0 ? (
                            <button
                              className="ops-link-btn"
                              type="button"
                              onClick={() => void startPayment(item)}
                            >
                              Pay
                            </button>
                          ) : null}
                          {item.status!=='CANCELLED'&&item.receipt_status !== "RECEIVED" ? (
                            <button
                              className="ops-link-btn"
                              type="button"
                              onClick={() => startReceiptConfirm(item)}
                            >
                              Confirm Receipt
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {attachmentTarget ? <AttachmentManager key={attachmentTarget.id} entity="purchase" recordId={attachmentTarget.id}
            title={attachmentTarget.bill_number || attachmentTarget.vendor_name} onClose={() => setAttachmentTarget(null)} /> : null}

          {paymentTarget ? (
            <div className="ops-inline-block">
              <h3>
                Record Payment: {paymentTarget.vendor_name} ({paymentTarget.bill_number || "No bill #"})
              </h3>
              <p>Outstanding Balance: {paymentTarget.balance_amount.toFixed(2)}</p>
              <form className="ops-form" onSubmit={submitPayment}>
                <label>
                  Amount
                  <input
                    type="number"
                    step="0.01"
                    value={paymentForm.amount}
                    onChange={(event) =>
                      setPaymentForm((prev) => ({ ...prev, amount: event.target.value }))
                    }
                    required
                  />
                </label>

                <label>
                  Account
                  <select
                    value={paymentForm.account_id}
                    onChange={(event) =>
                      setPaymentForm((prev) => ({ ...prev, account_id: event.target.value }))
                    }
                    required
                  >
                    <option value="">Select account</option>
                    {accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.nickname}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Payment Mode
                  <input
                    value={paymentForm.payment_mode}
                    onChange={(event) =>
                      setPaymentForm((prev) => ({ ...prev, payment_mode: event.target.value }))
                    }
                    placeholder="cash / bank / upi"
                    required
                  />
                </label>

                <label>
                  Payment Date
                  <input
                    type="date"
                    value={paymentForm.payment_date}
                    onChange={(event) =>
                      setPaymentForm((prev) => ({ ...prev, payment_date: event.target.value }))
                    }
                  />
                </label>

                <label>
                  Reference
                  <input
                    value={paymentForm.reference}
                    onChange={(event) =>
                      setPaymentForm((prev) => ({ ...prev, reference: event.target.value }))
                    }
                  />
                </label>

                <label>
                  Notes
                  <textarea
                    rows={2}
                    value={paymentForm.notes}
                    onChange={(event) =>
                      setPaymentForm((prev) => ({ ...prev, notes: event.target.value }))
                    }
                  />
                </label>

                <div className="ops-list-tools">
                  <button className="btn" type="submit" disabled={paying}>
                    {paying ? "Saving..." : "Save Payment"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => {
                      setPaymentTarget(null);
                      setPaymentForm(EMPTY_PAYMENT_FORM);
                      setPaymentHistory([]);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>

              <div className="ops-table-wrap">
                <table className="ops-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Amount</th>
                      <th>Mode</th>
                      <th>Reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paymentHistoryLoading ? (
                      <tr>
                        <td colSpan={4}>Loading payment history...</td>
                      </tr>
                    ) : paymentHistory.length === 0 ? (
                      <tr>
                        <td colSpan={4}>No payments recorded yet.</td>
                      </tr>
                    ) : (
                      paymentHistory.map((entry) => (
                        <tr key={entry.id}>
                          <td>{entry.payment_date}</td>
                          <td>{entry.amount.toFixed(2)}</td>
                          <td>{entry.payment_mode}</td>
                          <td>{entry.reference || "-"}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {receiptTarget ? (
            <div className="ops-inline-block">
              <h3>
                Confirm Receipt: {receiptTarget.vendor_name} ({receiptTarget.bill_number || "No bill #"})
              </h3>
              <form className="ops-form" onSubmit={submitReceiptConfirm}>
                <label>
                  Receipt Type
                  <select
                    value={receiptForm.receipt_type}
                    onChange={(event) =>
                      setReceiptForm((prev) => ({
                        ...prev,
                        receipt_type: event.target.value as "PRODUCT" | "STOCK" | "SERVICE",
                      }))
                    }
                  >
                    <option value="PRODUCT">Product</option>
                    <option value="STOCK">Stock</option>
                    <option value="SERVICE">Service</option>
                  </select>
                </label>

                <label>
                  Received At
                  <input
                    type="datetime-local"
                    value={receiptForm.received_at}
                    onChange={(event) =>
                      setReceiptForm((prev) => ({ ...prev, received_at: event.target.value }))
                    }
                  />
                </label>

                <label>
                  Receipt Notes
                  <textarea
                    rows={2}
                    value={receiptForm.received_notes}
                    onChange={(event) =>
                      setReceiptForm((prev) => ({ ...prev, received_notes: event.target.value }))
                    }
                  />
                </label>

                <div className="ops-list-tools">
                  <button className="btn" type="submit" disabled={confirmingReceipt}>
                    {confirmingReceipt ? "Saving..." : "Confirm"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => {
                      setReceiptTarget(null);
                      setReceiptForm(EMPTY_RECEIPT_FORM);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          ) : null}
        </article>
      </section>
    </div>
  );
}
