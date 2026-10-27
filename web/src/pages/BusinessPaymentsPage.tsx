import { FormEvent, useEffect, useState } from "react";
import { Paperclip } from "lucide-react";
import { AttachmentManager, AttachmentPicker } from "../components/Attachments";
import { api } from "../api";
import type { Account, AccountTransaction, AttachmentInput, Party } from "../types";

type PaymentForm = {
  from_account_id: string;
  amount: string;
  purpose: "purchase" | "billing" | "expense";
  related_party_id: string;
  payment_mode: string;
  reference: string;
  notes: string;
  transaction_date: string;
  create_borrowing: boolean;
};

const EMPTY_FORM: PaymentForm = {
  from_account_id: "",
  amount: "",
  purpose: "purchase",
  related_party_id: "",
  payment_mode: "bank",
  reference: "",
  notes: "",
  transaction_date: "",
  create_borrowing: true,
};

export function BusinessPaymentsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [form, setForm] = useState<PaymentForm>(EMPTY_FORM);
  const [attachments, setAttachments] = useState<AttachmentInput[]>([]);
  const [attachmentReading, setAttachmentReading] = useState(false);
  const [payments, setPayments] = useState<AccountTransaction[]>([]);
  const [attachmentTarget, setAttachmentTarget] = useState<AccountTransaction | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [accountResponse, partyResponse, paymentResponse] = await Promise.all([
        api.accounts({ active_only: true }),
        api.parties({ active_only: true }),
        api.businessPayments(),
      ]);
      setAccounts(accountResponse.items);
      setParties(partyResponse.items);
      setPayments(paymentResponse.items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load accounts.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setSaving(true);

    try {
      const amount = Number(form.amount);
      if (!form.from_account_id) throw new Error("Select source account");
      if (!amount || amount <= 0) throw new Error("Amount must be greater than zero");
      if ((form.purpose === "purchase" || form.purpose === "billing") && !form.related_party_id) {
        throw new Error("Select related party for purchase or billing payments.");
      }

      const result = await api.createBusinessPayment({
        attachments,
        from_account_id: form.from_account_id,
        amount,
        purpose: form.purpose,
        related_party_id: form.related_party_id || undefined,
        payment_mode: form.payment_mode || undefined,
        reference: form.reference || undefined,
        notes: form.notes || undefined,
        transaction_date: form.transaction_date || undefined,
        create_borrowing: form.create_borrowing,
      });

      if (result.borrowing_id) {
        setMessage(
          `Payment posted and borrowing auto-captured. Borrowing ID: ${result.borrowing_id}`
        );
      } else {
        setMessage("Payment posted from company account (no borrowing created).");
      }
      setForm(EMPTY_FORM);
      setAttachments([]);
      setAttachmentTarget(result.account_transaction);
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to record business payment.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="ops-page business-payments-page">
      <section className="ops-hero">
        <p className="eyebrow">Operations</p>
        <h1>Business Payments</h1>
        <p>
          Record purchase, billing, and expense payments. If payment is from a non-company account,
          borrowing is auto-captured against that account&apos;s linked party.
        </p>
      </section>

      <section className="ops-grid ops-grid-single">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Create Business Payment</h2>
          </div>

          {loading ? <p>Loading accounts...</p> : null}
          {error ? <p className="ops-error">{error}</p> : null}
          {message ? <p>{message}</p> : null}

          <form className="ops-form" onSubmit={submit}>
            <label>
              Source Account
              <select
                value={form.from_account_id}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, from_account_id: event.target.value }))
                }
                required
              >
                <option value="">Select account</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.nickname} ({account.account_type})
                    {account.is_company_account ? " - Company" : ""}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Purpose
              <select
                value={form.purpose}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    purpose: event.target.value as "purchase" | "billing" | "expense",
                  }))
                }
              >
                <option value="purchase">Purchase Payment</option>
                <option value="billing">Vendor Bill Payment</option>
                <option value="expense">Expense</option>
              </select>
            </label>

            <label>
              Related Party
              <select
                value={form.related_party_id}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, related_party_id: event.target.value }))
                }
                required={form.purpose === "purchase" || form.purpose === "billing"}
              >
                <option value="">Select party</option>
                {parties.map((party) => (
                  <option key={party.id} value={party.id}>
                    {party.legal_name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Amount
              <input
                type="number"
                step="0.01"
                value={form.amount}
                onChange={(event) => setForm((prev) => ({ ...prev, amount: event.target.value }))}
                required
              />
            </label>

            <label>
              Mode
              <input
                value={form.payment_mode}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, payment_mode: event.target.value }))
                }
                placeholder="cash / bank / upi"
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
              Date
              <input
                type="date"
                value={form.transaction_date}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, transaction_date: event.target.value }))
                }
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
                checked={form.create_borrowing}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, create_borrowing: event.target.checked }))
                }
              />
              Auto-capture borrowing for non-company accounts
            </label>

            <AttachmentPicker value={attachments} onChange={setAttachments} disabled={saving} onBusyChange={setAttachmentReading} />
            <button className="btn" type="submit" disabled={saving || loading || attachmentReading}>
              {saving ? "Saving..." : "Save Payment"}
            </button>
          </form>
        </article>
        <article className="ops-card ops-list-card">
          <div className="ops-card-head"><h2>Recent Business Payments</h2>
            <button className="ops-link-btn" type="button" onClick={() => void load()} disabled={loading}>Refresh</button>
          </div>
          <div className="ops-table-wrap"><table className="ops-table">
            <thead><tr><th>Date</th><th>Account</th><th>Purpose</th><th>Reference</th><th>Amount</th><th>Status</th><th>Files</th></tr></thead>
            <tbody>{payments.length ? payments.map((payment) => <tr key={payment.id}>
              <td>{payment.transaction_date}</td><td>{payment.from_account_name || "-"}</td>
              <td>{payment.category?.replace("business_", "")}</td><td>{payment.reference || payment.description || "-"}</td>
              <td>{payment.amount.toFixed(2)}</td><td>{payment.is_reversed ? "Reversed" : "Posted"}</td>
              <td><button className="ops-link-btn" type="button" title="Receipts and bills" aria-label={`Attachments for payment ${payment.reference || payment.id}`}
                onClick={() => setAttachmentTarget(payment)}><Paperclip size={16} aria-hidden="true" /></button></td>
            </tr>) : <tr><td colSpan={7}>{loading ? "Loading..." : "No business payments found."}</td></tr>}</tbody>
          </table></div>
          {attachmentTarget ? <AttachmentManager key={attachmentTarget.id} entity="business_payment" recordId={attachmentTarget.id}
            title={attachmentTarget.reference || attachmentTarget.id} onClose={() => setAttachmentTarget(null)} /> : null}
        </article>
      </section>
    </div>
  );
}
