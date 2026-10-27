import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  Account,
  BorrowingDirection,
  BorrowingEntry,
  BorrowingSummary,
  Party,
} from "../types";

type BorrowingForm = {
  party_id: string;
  direction: BorrowingDirection;
  amount: string;
  transaction_date: string;
  account_id: string;
  reference: string;
  notes: string;
  create_account_transaction: boolean;
};

const EMPTY_FORM: BorrowingForm = {
  party_id: "",
  direction: "borrow",
  amount: "",
  transaction_date: "",
  account_id: "",
  reference: "",
  notes: "",
  create_account_transaction: true,
};

function formatMoney(value: number): string {
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function SettlementsPage() {
  const [parties, setParties] = useState<Party[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [entries, setEntries] = useState<BorrowingEntry[]>([]);
  const [summary, setSummary] = useState<BorrowingSummary[]>([]);
  const [form, setForm] = useState<BorrowingForm>(EMPTY_FORM);
  const [selectedParty, setSelectedParty] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const partyOptions = useMemo(() => {
    return parties.map((party) => ({
      value: party.id,
      label: `${party.legal_name} (${party.party_type})`,
    }));
  }, [parties]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [partyResponse, accountResponse, summaryResponse, entriesResponse] = await Promise.all([
        api.parties({ active_only: true }),
        api.accounts({ active_only: true }),
        api.borrowingSummary(),
        api.borrowings({ party_id: selectedParty || undefined, limit: 200 }),
      ]);
      setParties(partyResponse.items);
      setAccounts(accountResponse.items);
      setSummary(summaryResponse.items);
      setEntries(entriesResponse.items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load settlements.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [selectedParty]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSaving(true);

    try {
      if (!form.party_id) throw new Error("Select a party.");
      const amount = Number(form.amount);
      if (!amount || amount <= 0) throw new Error("Amount must be greater than zero.");

      await api.createBorrowing({
        party_id: form.party_id,
        direction: form.direction,
        amount,
        transaction_date: form.transaction_date || undefined,
        account_id: form.account_id || undefined,
        reference: form.reference || undefined,
        notes: form.notes || undefined,
        create_account_transaction: form.create_account_transaction,
      });

      setForm(EMPTY_FORM);
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save settlement record.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="ops-page">
      <section className="ops-hero">
        <p className="eyebrow">Operations</p>
        <h1>Borrowing & Settlements</h1>
        <p>
          Track borrow and repay events per person with account-linked entries, so outstanding dues
          and settlement history are always auditable.
        </p>
      </section>

      <section className="ops-grid">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Record Borrow / Repay</h2>
          </div>
          <form className="ops-form" onSubmit={submit}>
            <label>
              Party
              <select
                value={form.party_id}
                onChange={(event) => setForm((prev) => ({ ...prev, party_id: event.target.value }))}
                required
              >
                <option value="">Select party</option>
                {partyOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Direction
              <select
                value={form.direction}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, direction: event.target.value as BorrowingDirection }))
                }
              >
                <option value="borrow">Borrowed</option>
                <option value="repay">Repaid</option>
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
              Account (optional)
              <select
                value={form.account_id}
                onChange={(event) => setForm((prev) => ({ ...prev, account_id: event.target.value }))}
              >
                <option value="">No linked account transaction</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.nickname} ({account.account_type})
                  </option>
                ))}
              </select>
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
                checked={form.create_account_transaction}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, create_account_transaction: event.target.checked }))
                }
              />
              Also post to account transactions when account is selected
            </label>

            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save Entry"}
            </button>
          </form>
        </article>

        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Outstanding by Party</h2>
            <span className="catalog-count">{summary.length} parties</span>
          </div>

          {error ? <p className="ops-error">{error}</p> : null}

          <div className="ops-list-tools">
            <select
              value={selectedParty}
              onChange={(event) => setSelectedParty(event.target.value)}
            >
              <option value="">All parties</option>
              {partyOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button className="btn" type="button" onClick={() => void load()}>
              Refresh
            </button>
          </div>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Party</th>
                  <th>Borrowed</th>
                  <th>Repaid</th>
                  <th>Net Outstanding</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={4}>Loading...</td>
                  </tr>
                ) : summary.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No borrowing records yet.</td>
                  </tr>
                ) : (
                  summary.map((row) => (
                    <tr key={row.party_id}>
                      <td>{row.party_name}</td>
                      <td>{formatMoney(row.borrowed_amount)}</td>
                      <td>{formatMoney(row.repaid_amount)}</td>
                      <td>{formatMoney(row.net_outstanding)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="ops-grid ops-grid-single">
        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Borrowing Timeline</h2>
            <span className="catalog-count">{entries.length} entries</span>
          </div>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Party</th>
                  <th>Direction</th>
                  <th>Amount</th>
                  <th>Reference</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 ? (
                  <tr>
                    <td colSpan={6}>No entries found.</td>
                  </tr>
                ) : (
                  entries.map((entry) => (
                    <tr key={entry.id}>
                      <td>{entry.transaction_date}</td>
                      <td>{entry.party_name}</td>
                      <td>{entry.direction === "borrow" ? "Borrowed" : "Repaid"}</td>
                      <td>{formatMoney(entry.amount)}</td>
                      <td>{entry.reference || "-"}</td>
                      <td>{entry.notes || "-"}</td>
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
