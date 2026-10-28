import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { PortalHomeLink } from "../components/PortalHomeLink";
import type {
  Account,
  AccountCreateInput,
  AccountTallyResponse,
  AuditJournalBucket,
  AuditJournalEntry,
  AccountTransaction,
  AccountTransactionCreateInput,
  AccountUpdateInput,
  PeriodLock,
} from "../types";

type FormState = {
  nickname: string;
  account_type: string;
  holder_name: string;
  phone: string;
  email: string;
  opening_balance: string;
};

type TransactionFormState = {
  from_account_id: string;
  to_account_id: string;
  amount: string;
  payment_mode: string;
  reference: string;
  category: string;
  description: string;
  transaction_date: string;
};

type JournalFilterState = {
  period: "daily" | "weekly" | "monthly" | "yearly";
  from_date: string;
  to_date: string;
  category: string;
  source_type: string;
};

type TransactionFilterState = {
  account_id: string;
  from_date: string;
  to_date: string;
  category: string;
  source_type: string;
};

type PeriodLockFormState = {
  period_start: string;
  period_end: string;
  reason: string;
};

const EMPTY_FORM: FormState = {
  nickname: "",
  account_type: "bank",
  holder_name: "",
  phone: "",
  email: "",
  opening_balance: "0",
};

const EMPTY_TX_FORM: TransactionFormState = {
  from_account_id: "",
  to_account_id: "",
  amount: "",
  payment_mode: "",
  reference: "",
  category: "",
  description: "",
  transaction_date: "",
};

const DEFAULT_JOURNAL_FILTERS: JournalFilterState = {
  period: "daily",
  from_date: "",
  to_date: "",
  category: "",
  source_type: "",
};

const DEFAULT_TX_FILTERS: TransactionFilterState = {
  account_id: "",
  from_date: "",
  to_date: "",
  category: "",
  source_type: "",
};

const DEFAULT_PERIOD_LOCK_FORM: PeriodLockFormState = {
  period_start: "",
  period_end: "",
  reason: "",
};

function formatMoney(value: number): string {
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function getTransactionStatus(
  tx: Pick<AccountTransaction, "reversal_of_transaction_id" | "is_reversed">
): { label: string; className: string } {
  if (tx.reversal_of_transaction_id) {
    return { label: "Reversal", className: "ops-status-badge reversal" };
  }
  if (tx.is_reversed) {
    return { label: "Reversed", className: "ops-status-badge reversed" };
  }
  return { label: "Posted", className: "ops-status-badge posted" };
}

export function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [transactions, setTransactions] = useState<AccountTransaction[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [txForm, setTxForm] = useState<TransactionFormState>(EMPTY_TX_FORM);
  const [txFilters, setTxFilters] = useState<TransactionFilterState>(DEFAULT_TX_FILTERS);
  const [periodLockForm, setPeriodLockForm] = useState<PeriodLockFormState>(
    DEFAULT_PERIOD_LOCK_FORM
  );
  const [periodLocks, setPeriodLocks] = useState<PeriodLock[]>([]);
  const [journalFilters, setJournalFilters] = useState<JournalFilterState>(
    DEFAULT_JOURNAL_FILTERS
  );
  const [tally, setTally] = useState<AccountTallyResponse | null>(null);
  const [tallyLoading, setTallyLoading] = useState(false);
  const [journalEntries, setJournalEntries] = useState<AuditJournalEntry[]>([]);
  const [journalBuckets, setJournalBuckets] = useState<AuditJournalBucket[]>([]);
  const [journalLoading, setJournalLoading] = useState(false);
  const [activeOnly, setActiveOnly] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [txSaving, setTxSaving] = useState(false);
  const [lockSaving, setLockSaving] = useState(false);

  const loadJournal = async () => {
    setJournalLoading(true);
    setError(null);
    try {
      const response = await api.accountAuditJournal({
        period: journalFilters.period,
        from_date: journalFilters.from_date || undefined,
        to_date: journalFilters.to_date || undefined,
        category: journalFilters.category || undefined,
        source_type: journalFilters.source_type || undefined,
        limit: 3000,
      });
      setJournalEntries(response.items);
      setJournalBuckets(response.buckets);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load audit journal.");
    } finally {
      setJournalLoading(false);
    }
  };

  const accountOptions = useMemo(
    () => accounts.map((account) => ({ value: account.id, label: account.nickname })),
    [accounts]
  );

  const load = async () => {
    setLoading(true);
    setTallyLoading(true);
    setError(null);
    try {
      const [accountsResponse, txResponse, tallyResponse, locksResponse] = await Promise.all([
        api.accounts({ active_only: activeOnly }),
        api.accountTransactions({
          limit: 200,
          account_id: txFilters.account_id || undefined,
          from_date: txFilters.from_date || undefined,
          to_date: txFilters.to_date || undefined,
          category: txFilters.category || undefined,
          source_type: txFilters.source_type || undefined,
        }),
        api.accountTally({ as_of: txFilters.to_date || undefined }),
        api.periodLocks(false),
      ]);
      setAccounts(accountsResponse.items);
      setTransactions(txResponse.items);
      setTally(tallyResponse);
      setPeriodLocks(locksResponse.items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load accounts.");
    } finally {
      setLoading(false);
      setTallyLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [activeOnly]);

  useEffect(() => {
    void loadJournal();
  }, [journalFilters.period]);

  const resetForm = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
  };

  const submitAccount = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const payload: AccountCreateInput = {
        nickname: form.nickname.trim(),
        account_type: form.account_type.trim(),
        holder_name: form.holder_name || undefined,
        phone: form.phone || undefined,
        email: form.email || undefined,
        opening_balance: Number(form.opening_balance || 0),
      };

      if (!payload.nickname || !payload.account_type) {
        throw new Error("Nickname and account type are required.");
      }

      if (editingId) {
        const patch: AccountUpdateInput = payload;
        await api.updateAccount(editingId, patch);
      } else {
        await api.createAccount(payload);
      }

      resetForm();
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save account.");
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (account: Account) => {
    setEditingId(account.id);
    setForm({
      nickname: account.nickname,
      account_type: account.account_type,
      holder_name: account.holder_name || "",
      phone: account.phone || "",
      email: account.email || "",
      opening_balance: String(account.opening_balance ?? 0),
    });
  };

  const deactivateAccount = async (accountId: string) => {
    setError(null);
    try {
      await api.updateAccount(accountId, { is_active: false });
      await load();
    } catch (deactivateError) {
      setError(
        deactivateError instanceof Error
          ? deactivateError.message
          : "Unable to deactivate account."
      );
    }
  };

  const submitTransaction = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setTxSaving(true);
    setError(null);

    try {
      const payload: AccountTransactionCreateInput = {
        from_account_id: txForm.from_account_id || undefined,
        to_account_id: txForm.to_account_id || undefined,
        amount: Number(txForm.amount),
        payment_mode: txForm.payment_mode || undefined,
        reference: txForm.reference || undefined,
        category: txForm.category || undefined,
        description: txForm.description || undefined,
        transaction_date: txForm.transaction_date || undefined,
      };

      if (!payload.amount || payload.amount <= 0) {
        throw new Error("Amount must be greater than zero.");
      }

      if (!payload.from_account_id && !payload.to_account_id) {
        throw new Error("Select at least one source or destination account.");
      }

      await api.createAccountTransaction(payload);
      setTxForm(EMPTY_TX_FORM);
      await load();
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "Unable to record transaction."
      );
    } finally {
      setTxSaving(false);
    }
  };

  const exportJournalCsv = () => {
    void (async () => {
      try {
        const blob = await api.exportAccountJournalCsv({
          period: journalFilters.period,
          from_date: journalFilters.from_date || undefined,
          to_date: journalFilters.to_date || undefined,
          category: journalFilters.category || undefined,
          source_type: journalFilters.source_type || undefined,
          limit: 5000,
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `audit_journal_${journalFilters.period}_${new Date()
          .toISOString()
          .slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } catch (exportError) {
        setError(exportError instanceof Error ? exportError.message : "Unable to export journal CSV.");
      }
    })();
  };

  const exportTransactionsCsv = () => {
    void (async () => {
      try {
        const blob = await api.exportAccountTransactionsCsv({
          limit: 2000,
          account_id: txFilters.account_id || undefined,
          from_date: txFilters.from_date || undefined,
          to_date: txFilters.to_date || undefined,
          category: txFilters.category || undefined,
          source_type: txFilters.source_type || undefined,
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `account_transactions_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } catch (exportError) {
        setError(
          exportError instanceof Error ? exportError.message : "Unable to export transactions CSV."
        );
      }
    })();
  };

  const reverseTransaction = async (transactionId: string) => {
    const shouldProceed = window.confirm(
      "This will post a reversal transaction and cannot be edited. Continue?"
    );
    if (!shouldProceed) {
      return;
    }

    setError(null);
    try {
      await api.reverseAccountTransaction(transactionId, {
        notes: "Reversal from accounts page",
      });
      await load();
      await loadJournal();
    } catch (reverseError) {
      setError(reverseError instanceof Error ? reverseError.message : "Unable to reverse transaction.");
    }
  };

  const submitPeriodLock = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLockSaving(true);
    setError(null);
    try {
      if (!periodLockForm.period_start || !periodLockForm.period_end) {
        throw new Error("Select period start and end dates.");
      }
      await api.closePeriodLock({
        period_start: periodLockForm.period_start,
        period_end: periodLockForm.period_end,
        reason: periodLockForm.reason || undefined,
        closed_by: "operations_user",
      });
      setPeriodLockForm(DEFAULT_PERIOD_LOCK_FORM);
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to close period.");
    } finally {
      setLockSaving(false);
    }
  };

  const reopenPeriodLock = async (lockId: string) => {
    setError(null);
    try {
      await api.reopenPeriodLock(lockId, {
        reopened_by: "operations_user",
        reopen_reason: "Reopened from accounts page",
      });
      await load();
    } catch (reopenError) {
      setError(reopenError instanceof Error ? reopenError.message : "Unable to reopen period lock.");
    }
  };

  return (
    <div className="ops-page">
      <section className="ops-hero">
        <PortalHomeLink />
        <p className="eyebrow">Operations</p>
        <h1>Accounts</h1>
        <p>
          Manage business accounts and capture account-to-account or cash movement
          transactions in one place.
        </p>
      </section>

      <section className="ops-grid">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>{editingId ? "Edit Account" : "Create Account"}</h2>
            {editingId ? (
              <button className="ops-link-btn" onClick={resetForm} type="button">
                Cancel
              </button>
            ) : null}
          </div>

          <form className="ops-form" onSubmit={submitAccount}>
            <label>
              Nickname
              <input
                value={form.nickname}
                onChange={(event) => setForm((prev) => ({ ...prev, nickname: event.target.value }))}
                required
              />
            </label>

            <label>
              Account Type
              <select
                value={form.account_type}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, account_type: event.target.value }))
                }
              >
                <option value="bank">Bank</option>
                <option value="cash">Cash</option>
                <option value="upi">UPI</option>
                <option value="card">Card</option>
                <option value="other">Other</option>
              </select>
            </label>

            <label>
              Holder Name
              <input
                value={form.holder_name}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, holder_name: event.target.value }))
                }
              />
            </label>

            <label>
              Phone
              <input
                value={form.phone}
                onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
              />
            </label>

            <label>
              Email
              <input
                value={form.email}
                onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
              />
            </label>

            <label>
              Opening Balance
              <input
                type="number"
                value={form.opening_balance}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, opening_balance: event.target.value }))
                }
              />
            </label>

            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Saving..." : editingId ? "Update Account" : "Create Account"}
            </button>
          </form>
        </article>

        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Accounts</h2>
            <span className="catalog-count">{accounts.length} records</span>
          </div>

          <div className="ops-list-tools">
            <label className="ops-toggle">
              <input
                type="checkbox"
                checked={activeOnly}
                onChange={(event) => setActiveOnly(event.target.checked)}
              />
              Active only
            </label>
          </div>

          {error ? <p className="ops-error">{error}</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Nickname</th>
                  <th>Type</th>
                  <th>Holder</th>
                  <th>Opening</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={6}>Loading...</td>
                  </tr>
                ) : accounts.length === 0 ? (
                  <tr>
                    <td colSpan={6}>No accounts found.</td>
                  </tr>
                ) : (
                  accounts.map((account) => (
                    <tr key={account.id}>
                      <td>{account.nickname}</td>
                      <td>{account.account_type}</td>
                      <td>{account.holder_name || "-"}</td>
                      <td>{account.opening_balance.toFixed(2)}</td>
                      <td>{account.is_active ? "Active" : "Inactive"}</td>
                      <td>
                        <button
                          className="ops-link-btn"
                          type="button"
                          onClick={() => startEdit(account)}
                        >
                          Edit
                        </button>
                        {account.is_active ? (
                          <button
                            className="ops-link-btn"
                            type="button"
                            onClick={() => void deactivateAccount(account.id)}
                          >
                            Deactivate
                          </button>
                        ) : null}
                      </td>
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
            <h2>Account Tally</h2>
            <span className="catalog-count">
              {tallyLoading || !tally ? "..." : `${tally.items.length} accounts`}
            </span>
          </div>

          <div className="ops-list-tools">
            <span>Opening: {tally ? formatMoney(tally.total_opening_balance) : "0.00"}</span>
            <span>Inflow: {tally ? formatMoney(tally.total_inflow) : "0.00"}</span>
            <span>Outflow: {tally ? formatMoney(tally.total_outflow) : "0.00"}</span>
            <span>Current: {tally ? formatMoney(tally.total_current_balance) : "0.00"}</span>
          </div>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Type</th>
                  <th>Opening</th>
                  <th>Inflow</th>
                  <th>Outflow</th>
                  <th>Current</th>
                  <th>Entries</th>
                  <th>Last Date</th>
                </tr>
              </thead>
              <tbody>
                {tallyLoading ? (
                  <tr>
                    <td colSpan={8}>Loading tally...</td>
                  </tr>
                ) : !tally || tally.items.length === 0 ? (
                  <tr>
                    <td colSpan={8}>No tally data found.</td>
                  </tr>
                ) : (
                  tally.items.map((row) => (
                    <tr key={row.account_id}>
                      <td>{row.account_name}{row.is_company_account ? " (Company)" : ""}</td>
                      <td>{row.account_type}</td>
                      <td>{formatMoney(row.opening_balance)}</td>
                      <td>{formatMoney(row.total_inflow)}</td>
                      <td>{formatMoney(row.total_outflow)}</td>
                      <td>{formatMoney(row.current_balance)}</td>
                      <td>{row.transaction_count}</td>
                      <td>{row.last_transaction_date || "-"}</td>
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
            <h2>Period Close / Lock</h2>
            <span className="catalog-count">{periodLocks.length} active locks</span>
          </div>

          <form className="ops-form" onSubmit={submitPeriodLock}>
            <label>
              Period Start
              <input
                type="date"
                value={periodLockForm.period_start}
                onChange={(event) =>
                  setPeriodLockForm((prev) => ({ ...prev, period_start: event.target.value }))
                }
                required
              />
            </label>
            <label>
              Period End
              <input
                type="date"
                value={periodLockForm.period_end}
                onChange={(event) =>
                  setPeriodLockForm((prev) => ({ ...prev, period_end: event.target.value }))
                }
                required
              />
            </label>
            <label>
              Reason
              <input
                value={periodLockForm.reason}
                onChange={(event) =>
                  setPeriodLockForm((prev) => ({ ...prev, reason: event.target.value }))
                }
                placeholder="Month closed after audit"
              />
            </label>
            <button className="btn" type="submit" disabled={lockSaving}>
              {lockSaving ? "Saving..." : "Close Period"}
            </button>
          </form>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Start</th>
                  <th>End</th>
                  <th>Reason</th>
                  <th>Closed By</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {periodLocks.length === 0 ? (
                  <tr>
                    <td colSpan={5}>No active period locks.</td>
                  </tr>
                ) : (
                  periodLocks.map((lock) => (
                    <tr key={lock.id}>
                      <td>{lock.period_start}</td>
                      <td>{lock.period_end}</td>
                      <td>{lock.reason || "-"}</td>
                      <td>{lock.closed_by || "-"}</td>
                      <td>
                        <button
                          className="ops-link-btn"
                          type="button"
                          onClick={() => void reopenPeriodLock(lock.id)}
                        >
                          Reopen
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="ops-grid ops-grid-single">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Record Transaction</h2>
          </div>

          <form className="ops-form" onSubmit={submitTransaction}>
            <label>
              From Account
              <select
                value={txForm.from_account_id}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, from_account_id: event.target.value }))
                }
              >
                <option value="">-</option>
                {accountOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              To Account
              <select
                value={txForm.to_account_id}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, to_account_id: event.target.value }))
                }
              >
                <option value="">-</option>
                {accountOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Amount
              <input
                type="number"
                step="0.01"
                value={txForm.amount}
                onChange={(event) => setTxForm((prev) => ({ ...prev, amount: event.target.value }))}
                required
              />
            </label>

            <label>
              Payment Mode
              <input
                value={txForm.payment_mode}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, payment_mode: event.target.value }))
                }
                placeholder="cash / bank / upi"
              />
            </label>

            <label>
              Reference
              <input
                value={txForm.reference}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, reference: event.target.value }))
                }
              />
            </label>

            <label>
              Category
              <input
                value={txForm.category}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, category: event.target.value }))
                }
                placeholder="sales_collection / purchase_payment / borrow_settlement"
              />
            </label>

            <label>
              Transaction Date
              <input
                type="date"
                value={txForm.transaction_date}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, transaction_date: event.target.value }))
                }
              />
            </label>

            <label>
              Description
              <textarea
                rows={3}
                value={txForm.description}
                onChange={(event) =>
                  setTxForm((prev) => ({ ...prev, description: event.target.value }))
                }
              />
            </label>

            <button className="btn" type="submit" disabled={txSaving}>
              {txSaving ? "Saving..." : "Save Transaction"}
            </button>
          </form>
        </article>

        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Recent Transactions</h2>
            <span className="catalog-count">{transactions.length} records</span>
          </div>

          <div className="ops-list-tools">
            <select
              value={txFilters.account_id}
              onChange={(event) =>
                setTxFilters((prev) => ({ ...prev, account_id: event.target.value }))
              }
            >
              <option value="">All accounts</option>
              {accountOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={txFilters.from_date}
              onChange={(event) =>
                setTxFilters((prev) => ({ ...prev, from_date: event.target.value }))
              }
            />
            <input
              type="date"
              value={txFilters.to_date}
              onChange={(event) =>
                setTxFilters((prev) => ({ ...prev, to_date: event.target.value }))
              }
            />
            <input
              value={txFilters.category}
              onChange={(event) =>
                setTxFilters((prev) => ({ ...prev, category: event.target.value }))
              }
              placeholder="Category"
            />
            <input
              value={txFilters.source_type}
              onChange={(event) =>
                setTxFilters((prev) => ({ ...prev, source_type: event.target.value }))
              }
              placeholder="Source"
            />
            <button className="btn" type="button" onClick={() => void load()}>
              Apply
            </button>
            <button
              className="btn"
              type="button"
              onClick={async () => {
                const resetFilters = DEFAULT_TX_FILTERS;
                setTxFilters(resetFilters);
                setLoading(true);
                setTallyLoading(true);
                setError(null);
                try {
                  const [accountsResponse, txResponse, tallyResponse] = await Promise.all([
                    api.accounts({ active_only: activeOnly }),
                    api.accountTransactions({ limit: 200 }),
                    api.accountTally(),
                  ]);
                  setAccounts(accountsResponse.items);
                  setTransactions(txResponse.items);
                  setTally(tallyResponse);
                } catch (loadError) {
                  setError(loadError instanceof Error ? loadError.message : "Unable to load accounts.");
                } finally {
                  setLoading(false);
                  setTallyLoading(false);
                }
              }}
            >
              Reset
            </button>
            <button className="btn" type="button" onClick={exportTransactionsCsv}>
              Export CSV
            </button>
          </div>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Direction</th>
                  <th>Status</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Amount</th>
                  <th>Category</th>
                  <th>Source</th>
                  <th>Mode</th>
                  <th>Ref</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {transactions.length === 0 ? (
                  <tr>
                    <td colSpan={11}>No transactions yet.</td>
                  </tr>
                ) : (
                  transactions.map((item) => {
                    const status = getTransactionStatus(item);
                    return (
                      <tr key={item.id}>
                        <td>{item.transaction_date}</td>
                        <td>{item.direction || "-"}</td>
                        <td>
                          <span className={status.className}>{status.label}</span>
                        </td>
                        <td>{item.from_account_name || item.from_account_id || "-"}</td>
                        <td>{item.to_account_name || item.to_account_id || "-"}</td>
                        <td>{item.amount.toFixed(2)}</td>
                        <td>{item.category || "-"}</td>
                        <td>{item.source_type || "-"}</td>
                        <td>{item.payment_mode || "-"}</td>
                        <td>{item.reference || "-"}</td>
                        <td>
                          {item.reversal_of_transaction_id ? (
                            <span>Reversal row</span>
                          ) : item.is_reversed ? (
                            <span>Already reversed</span>
                          ) : (
                            <button
                              className="ops-link-btn"
                              type="button"
                              onClick={() => void reverseTransaction(item.id)}
                            >
                              Reverse
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="ops-grid ops-grid-single">
        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Audit Journal</h2>
            <span className="catalog-count">{journalEntries.length} rows</span>
          </div>

          <div className="ops-list-tools">
            <select
              value={journalFilters.period}
              onChange={(event) =>
                setJournalFilters((prev) => ({
                  ...prev,
                  period: event.target.value as "daily" | "weekly" | "monthly" | "yearly",
                }))
              }
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
            </select>

            <input
              type="date"
              value={journalFilters.from_date}
              onChange={(event) =>
                setJournalFilters((prev) => ({ ...prev, from_date: event.target.value }))
              }
              placeholder="From"
            />

            <input
              type="date"
              value={journalFilters.to_date}
              onChange={(event) =>
                setJournalFilters((prev) => ({ ...prev, to_date: event.target.value }))
              }
              placeholder="To"
            />

            <input
              value={journalFilters.category}
              onChange={(event) =>
                setJournalFilters((prev) => ({ ...prev, category: event.target.value }))
              }
              placeholder="Category"
            />

            <input
              value={journalFilters.source_type}
              onChange={(event) =>
                setJournalFilters((prev) => ({ ...prev, source_type: event.target.value }))
              }
              placeholder="Source type"
            />

            <button className="btn" type="button" onClick={() => void loadJournal()}>
              Apply
            </button>
            <button
              className="btn"
              type="button"
              onClick={async () => {
                const resetFilters = DEFAULT_JOURNAL_FILTERS;
                setJournalFilters(resetFilters);
                setJournalLoading(true);
                setError(null);
                try {
                  const response = await api.accountAuditJournal({
                    period: resetFilters.period,
                    limit: 3000,
                  });
                  setJournalEntries(response.items);
                  setJournalBuckets(response.buckets);
                } catch (loadError) {
                  setError(
                    loadError instanceof Error ? loadError.message : "Unable to load audit journal."
                  );
                } finally {
                  setJournalLoading(false);
                }
              }}
            >
              Reset
            </button>
            <button className="btn" type="button" onClick={exportJournalCsv}>
              Export CSV
            </button>
          </div>

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Entries</th>
                  <th>Inflow</th>
                  <th>Outflow</th>
                  <th>Transfer</th>
                  <th>Net</th>
                </tr>
              </thead>
              <tbody>
                {journalBuckets.length === 0 ? (
                  <tr>
                    <td colSpan={6}>No summary rows.</td>
                  </tr>
                ) : (
                  journalBuckets.map((bucket) => (
                    <tr key={bucket.period_key}>
                      <td>{bucket.period_key}</td>
                      <td>{bucket.entry_count}</td>
                      <td>{bucket.total_inflow.toFixed(2)}</td>
                      <td>{bucket.total_outflow.toFixed(2)}</td>
                      <td>{bucket.total_transfer.toFixed(2)}</td>
                      <td>{bucket.net_flow.toFixed(2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {journalLoading ? <p>Loading journal...</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Period</th>
                  <th>Direction</th>
                  <th>Amount</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Category</th>
                  <th>Source</th>
                  <th>Reference</th>
                </tr>
              </thead>
              <tbody>
                {journalEntries.length === 0 ? (
                  <tr>
                    <td colSpan={9}>No journal entries found.</td>
                  </tr>
                ) : (
                  journalEntries.map((row) => (
                    <tr key={row.transaction_id}>
                      <td>{row.transaction_date}</td>
                      <td>{row.period_key}</td>
                      <td>{row.direction}</td>
                      <td>{row.amount.toFixed(2)}</td>
                      <td>{row.from_account_name || row.from_account_id || "-"}</td>
                      <td>{row.to_account_name || row.to_account_id || "-"}</td>
                      <td>{row.category || "-"}</td>
                      <td>{row.source_type || "-"}</td>
                      <td>{row.reference || "-"}</td>
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
