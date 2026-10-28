import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { PortalHomeLink } from "../components/PortalHomeLink";
import type { Account, Party, Receivable, ReceivableReminderLog } from "../types";

type ReceivableForm = {
  party_id: string;
  reference: string;
  amount_due: string;
  due_date: string;
  reminder_date: string;
  notes: string;
};

type CollectionForm = {
  receivable_id: string;
  amount: string;
  account_id: string;
  payment_mode: string;
  idempotency_key: string;
  reference: string;
  payment_date: string;
  notes: string;
};

function createIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type ReminderHistoryFilters = {
  from_date: string;
  to_date: string;
  reminded_by: string;
};

const EMPTY_RECEIVABLE_FORM: ReceivableForm = {
  party_id: "",
  reference: "",
  amount_due: "",
  due_date: "",
  reminder_date: "",
  notes: "",
};

function createEmptyCollectionForm(): CollectionForm {
  return {
    receivable_id: "",
    amount: "",
    account_id: "",
    payment_mode: "cash",
    idempotency_key: createIdempotencyKey("receivable-collection"),
    reference: "",
    payment_date: "",
    notes: "",
  };
}

const EMPTY_HISTORY_FILTERS: ReminderHistoryFilters = {
  from_date: "",
  to_date: "",
  reminded_by: "",
};

function addDaysIso(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function ReceivablesPage() {
  const [searchParams] = useSearchParams();
  const invoiceIdQuery = searchParams.get("invoice_id") || "";
  const statusQuery = (searchParams.get("status") || "").toUpperCase();
  const focusQuery = (searchParams.get("focus") || "").toLowerCase();
  const [parties, setParties] = useState<Party[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [receivables, setReceivables] = useState<Receivable[]>([]);
  const [reminders, setReminders] = useState<Receivable[]>([]);
  const [statusFilter, setStatusFilter] = useState(
    statusQuery && statusQuery !== "OPEN" ? statusQuery : ""
  );
  const [showOpenOnly, setShowOpenOnly] = useState(statusQuery === "OPEN");
  const [receivableForm, setReceivableForm] = useState<ReceivableForm>(EMPTY_RECEIVABLE_FORM);
  const [collectionForm, setCollectionForm] = useState<CollectionForm>(createEmptyCollectionForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [remindingId, setRemindingId] = useState<string | null>(null);
  const [nextReminderById, setNextReminderById] = useState<Record<string, string>>({});
  const [historyForReceivableId, setHistoryForReceivableId] = useState<string | null>(null);
  const [historyForReceivableLabel, setHistoryForReceivableLabel] = useState<string>("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [reminderHistory, setReminderHistory] = useState<ReceivableReminderLog[]>([]);
  const [historyFilters, setHistoryFilters] = useState<ReminderHistoryFilters>(
    EMPTY_HISTORY_FILTERS
  );
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const remindersRef = useRef<HTMLElement | null>(null);

  const ledgerRows = useMemo(() => {
    if (!showOpenOnly) return receivables;
    return receivables.filter((item) => item.status === "UNPAID" || item.status === "PARTIAL");
  }, [receivables, showOpenOnly]);

  useEffect(() => {
    if (!statusQuery) {
      setShowOpenOnly(false);
      return;
    }
    if (statusQuery === "OPEN") {
      setStatusFilter("");
      setShowOpenOnly(true);
      return;
    }
    if (["UNPAID", "PARTIAL", "SETTLED", "BAD_DEBT"].includes(statusQuery)) {
      setStatusFilter(statusQuery);
      setShowOpenOnly(false);
    }
  }, [statusQuery]);

  useEffect(() => {
    if (invoiceIdQuery && statusFilter) {
      setStatusFilter("");
      setShowOpenOnly(false);
    }
  }, [invoiceIdQuery, statusFilter]);

  useEffect(() => {
    if (!success) return;
    const timeout = window.setTimeout(() => setSuccess(null), 2500);
    return () => window.clearTimeout(timeout);
  }, [success]);

  useEffect(() => {
    if (!loading && focusQuery === "reminders") {
      remindersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focusQuery, loading]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [partyRes, accountRes, receivableRes, reminderRes] = await Promise.all([
        api.parties({ active_only: true }),
        api.accounts({ active_only: true }),
        api.receivables({ status: statusFilter || undefined }),
        api.dueReceivableReminders(),
      ]);
      setParties(partyRes.items);
      setAccounts(accountRes.items);
      setReceivables(receivableRes.items);
      setReminders(reminderRes.items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load receivables.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [statusFilter]);

  useEffect(() => {
    if (!invoiceIdQuery || receivables.length === 0) return;
    const match = receivables.find((item) => item.invoice_id === invoiceIdQuery);
    if (!match) return;
    setCollectionForm((prev) => ({
      ...prev,
      receivable_id: match.id,
      amount: prev.amount || String(match.balance_amount),
    }));
  }, [invoiceIdQuery, receivables]);

  const createReceivable = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const amountDue = Number(receivableForm.amount_due);
      if (!receivableForm.party_id) throw new Error("Select party");
      if (!amountDue || amountDue <= 0) throw new Error("Amount due must be greater than zero");

      await api.createReceivable({
        party_id: receivableForm.party_id,
        reference: receivableForm.reference || undefined,
        amount_due: amountDue,
        due_date: receivableForm.due_date || undefined,
        reminder_date: receivableForm.reminder_date || undefined,
        notes: receivableForm.notes || undefined,
      });

      setReceivableForm(EMPTY_RECEIVABLE_FORM);
      setSuccess("Receivable created.");
      await load();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create receivable.");
    } finally {
      setSaving(false);
    }
  };

  const collect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCollecting(true);
    setError(null);

    try {
      const amount = Number(collectionForm.amount);
      if (!collectionForm.receivable_id) throw new Error("Select receivable");
      if (!amount || amount <= 0) throw new Error("Amount must be greater than zero");
      if (!collectionForm.account_id) throw new Error("Select account where payment was received.");

      await api.collectReceivable(collectionForm.receivable_id, {
        amount,
        account_id: collectionForm.account_id,
        payment_mode: collectionForm.payment_mode,
        idempotency_key: collectionForm.idempotency_key,
        reference: collectionForm.reference || undefined,
        payment_date: collectionForm.payment_date || undefined,
        notes: collectionForm.notes || undefined,
      });

      setCollectionForm(createEmptyCollectionForm());
      setSuccess("Collection recorded.");
      await load();
    } catch (collectError) {
      setError(collectError instanceof Error ? collectError.message : "Unable to collect payment.");
    } finally {
      setCollecting(false);
    }
  };

  const markBadDebt = async (receivableId: string) => {
    setError(null);
    try {
      await api.updateReceivable(receivableId, {
        status: "BAD_DEBT",
        bad_debt_reason: "Marked from operations page",
      });
      setSuccess("Receivable marked as bad debt.");
      await load();
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "Unable to mark bad debt.");
    }
  };

  const markReminder = async (receivableId: string, nextReminderDate?: string) => {
    setError(null);
    setRemindingId(receivableId);
    try {
      await api.markReceivableReminder(receivableId, {
        next_reminder_date: nextReminderDate || undefined,
        notes: "Reminder sent from operations page",
        reminded_by: "operations_user",
      });
      setNextReminderById((prev) => {
        const next = { ...prev };
        delete next[receivableId];
        return next;
      });
      setSuccess("Reminder marked.");
      await load();
    } catch (reminderError) {
      setError(reminderError instanceof Error ? reminderError.message : "Unable to mark reminder.");
    } finally {
      setRemindingId(null);
    }
  };

  const openReminderHistory = async (
    receivableId: string,
    label: string,
    filters?: ReminderHistoryFilters
  ) => {
    setError(null);
    setHistoryForReceivableId(receivableId);
    setHistoryForReceivableLabel(label);
    setHistoryLoading(true);
    try {
      const appliedFilters = filters || historyFilters;
      const response = await api.receivableReminderHistory(receivableId, {
        from_date: appliedFilters.from_date || undefined,
        to_date: appliedFilters.to_date || undefined,
        reminded_by: appliedFilters.reminded_by || undefined,
      });
      setReminderHistory(response.items);
    } catch (historyError) {
      setError(
        historyError instanceof Error ? historyError.message : "Unable to load reminder history."
      );
      setReminderHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const applyHistoryFilters = async () => {
    if (!historyForReceivableId) return;
    await openReminderHistory(historyForReceivableId, historyForReceivableLabel);
  };

  const resetHistoryFilters = async () => {
    setHistoryFilters(EMPTY_HISTORY_FILTERS);
    if (!historyForReceivableId) return;
    await openReminderHistory(historyForReceivableId, historyForReceivableLabel, EMPTY_HISTORY_FILTERS);
  };

  const exportArAgingCsv = () => {
    void (async () => {
      setError(null);
      setSuccess(null);
      try {
        const blob = await api.exportArAgingCsv();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `ar_aging_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setSuccess("AR aging exported.");
      } catch (exportError) {
        setError(exportError instanceof Error ? exportError.message : "Unable to export AR aging.");
      }
    })();
  };

  return (
    <div className="ops-page">
      <section className="ops-hero">
        <PortalHomeLink />
        <p className="eyebrow">Operations</p>
        <h1>Receivables & Collections</h1>
        <p>
          Track outstanding sales, confirm collection mode and account receipt, set reminders,
          and mark bad debt when required.
        </p>
      </section>

      {success ? <p className="ops-success-banner">{success}</p> : null}

      <section className="ops-grid">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Create Receivable</h2>
          </div>
          <form className="ops-form" onSubmit={createReceivable}>
            <label>
              Party
              <select
                value={receivableForm.party_id}
                onChange={(event) =>
                  setReceivableForm((prev) => ({ ...prev, party_id: event.target.value }))
                }
                required
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
              Reference
              <input
                value={receivableForm.reference}
                onChange={(event) =>
                  setReceivableForm((prev) => ({ ...prev, reference: event.target.value }))
                }
                placeholder="Invoice or sale reference"
              />
            </label>
            <label>
              Amount Due
              <input
                type="number"
                step="0.01"
                value={receivableForm.amount_due}
                onChange={(event) =>
                  setReceivableForm((prev) => ({ ...prev, amount_due: event.target.value }))
                }
                required
              />
            </label>
            <label>
              Due Date
              <input
                type="date"
                value={receivableForm.due_date}
                onChange={(event) =>
                  setReceivableForm((prev) => ({ ...prev, due_date: event.target.value }))
                }
              />
            </label>
            <label>
              Reminder Date
              <input
                type="date"
                value={receivableForm.reminder_date}
                onChange={(event) =>
                  setReceivableForm((prev) => ({ ...prev, reminder_date: event.target.value }))
                }
              />
            </label>
            <label>
              Notes
              <textarea
                rows={3}
                value={receivableForm.notes}
                onChange={(event) =>
                  setReceivableForm((prev) => ({ ...prev, notes: event.target.value }))
                }
              />
            </label>
            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Create Receivable"}
            </button>
          </form>
        </article>

        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Collect Payment</h2>
          </div>
          <form className="ops-form" onSubmit={collect}>
            <label>
              Receivable
              <select
                value={collectionForm.receivable_id}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, receivable_id: event.target.value }))
                }
                required
              >
                <option value="">Select receivable</option>
                {receivables
                  .filter((item) => item.status === "UNPAID" || item.status === "PARTIAL")
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.party_name} - {item.reference || item.id} - Bal {item.balance_amount.toFixed(2)}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Amount
              <input
                type="number"
                step="0.01"
                value={collectionForm.amount}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, amount: event.target.value }))
                }
                required
              />
            </label>
            <label>
              Received In Account
              <select
                value={collectionForm.account_id}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, account_id: event.target.value }))
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
              Mode
              <input
                value={collectionForm.payment_mode}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, payment_mode: event.target.value }))
                }
                placeholder="cash / bank / upi"
                required
              />
            </label>
            <label>
              Reference
              <input
                value={collectionForm.reference}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, reference: event.target.value }))
                }
              />
            </label>
            <label>
              Date
              <input
                type="date"
                value={collectionForm.payment_date}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, payment_date: event.target.value }))
                }
              />
            </label>
            <label>
              Notes
              <textarea
                rows={3}
                value={collectionForm.notes}
                onChange={(event) =>
                  setCollectionForm((prev) => ({ ...prev, notes: event.target.value }))
                }
              />
            </label>
            <button className="btn" type="submit" disabled={collecting}>
              {collecting ? "Saving..." : "Collect"}
            </button>
          </form>
        </article>
      </section>

      <section className="ops-grid ops-grid-single">
        <article className="ops-card ops-list-card">
          <div className="ops-card-head">
            <h2>Receivable Ledger</h2>
            <span className="catalog-count">{ledgerRows.length} records</span>
          </div>

          <div className="ops-list-tools">
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setShowOpenOnly(false);
              }}
            >
              <option value="">All status</option>
              <option value="UNPAID">UNPAID</option>
              <option value="PARTIAL">PARTIAL</option>
              <option value="SETTLED">SETTLED</option>
              <option value="BAD_DEBT">BAD_DEBT</option>
            </select>
            <label className="ops-toggle">
              <input
                type="checkbox"
                checked={showOpenOnly}
                onChange={(event) => {
                  setShowOpenOnly(event.target.checked);
                  if (event.target.checked) {
                    setStatusFilter("");
                  }
                }}
              />
              Open only
            </label>
            <button className="btn" type="button" onClick={() => void load()}>
              Refresh
            </button>
            <button className="btn" type="button" onClick={exportArAgingCsv}>
              Export AR Aging
            </button>
          </div>

          {error ? <p className="ops-error">{error}</p> : null}
          {loading ? <p>Loading...</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Party</th>
                  <th>Reference</th>
                  <th>Due</th>
                  <th>Received</th>
                  <th>Balance</th>
                  <th>Status</th>
                  <th>Reminder</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {ledgerRows.length === 0 ? (
                  <tr>
                    <td colSpan={8}>No receivables found.</td>
                  </tr>
                ) : (
                  ledgerRows.map((item) => (
                    <tr key={item.id}>
                      <td>{item.party_name}</td>
                      <td>{item.reference || "-"}</td>
                      <td>{item.amount_due.toFixed(2)}</td>
                      <td>{item.amount_received.toFixed(2)}</td>
                      <td>{item.balance_amount.toFixed(2)}</td>
                      <td>{item.status}</td>
                      <td>{item.reminder_date || item.due_date || "-"}</td>
                      <td>
                        {(item.status === "UNPAID" || item.status === "PARTIAL") && (
                          <>
                            <button
                              className="ops-link-btn"
                              type="button"
                              onClick={() => void markBadDebt(item.id)}
                            >
                              Mark bad debt
                            </button>
                            <button
                              className="ops-link-btn"
                              type="button"
                              onClick={() =>
                                void openReminderHistory(item.id, item.reference || item.party_name)
                              }
                            >
                              Reminder history
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="ops-card ops-list-card" ref={remindersRef}>
          <div className="ops-card-head">
            <h2>Due Reminders</h2>
            <span className="catalog-count">{reminders.length} due</span>
          </div>
          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Party</th>
                  <th>Reference</th>
                  <th>Balance</th>
                  <th>Reminder Date</th>
                  <th>Status</th>
                  <th>Next Reminder</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {reminders.length === 0 ? (
                  <tr>
                    <td colSpan={7}>No reminders due.</td>
                  </tr>
                ) : (
                  reminders.map((item) => (
                    <tr key={`r-${item.id}`}>
                      <td>{item.party_name}</td>
                      <td>{item.reference || "-"}</td>
                      <td>{item.balance_amount.toFixed(2)}</td>
                      <td>{item.reminder_date || item.due_date || "-"}</td>
                      <td>{item.status}</td>
                      <td>
                        <input
                          type="date"
                          value={nextReminderById[item.id] || ""}
                          onChange={(event) =>
                            setNextReminderById((prev) => ({
                              ...prev,
                              [item.id]: event.target.value,
                            }))
                          }
                        />
                      </td>
                      <td>
                        <button
                          className="ops-link-btn"
                          type="button"
                          disabled={remindingId === item.id}
                          onClick={() => void markReminder(item.id, nextReminderById[item.id])}
                        >
                          {remindingId === item.id ? "Saving..." : "Mark reminded"}
                        </button>
                        <button
                          className="ops-link-btn"
                          type="button"
                          disabled={remindingId === item.id}
                          onClick={() => void markReminder(item.id, addDaysIso(7))}
                        >
                          +7 days
                        </button>
                        <button
                          className="ops-link-btn"
                          type="button"
                          onClick={() =>
                            void openReminderHistory(item.id, item.reference || item.party_name)
                          }
                        >
                          History
                        </button>
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
            <h2>Reminder History</h2>
            <span className="catalog-count">
              {historyForReceivableId ? historyForReceivableLabel : "Select a receivable"}
            </span>
          </div>

          <div className="ops-list-tools">
            <input
              type="date"
              value={historyFilters.from_date}
              onChange={(event) =>
                setHistoryFilters((prev) => ({ ...prev, from_date: event.target.value }))
              }
              placeholder="From date"
            />
            <input
              type="date"
              value={historyFilters.to_date}
              onChange={(event) =>
                setHistoryFilters((prev) => ({ ...prev, to_date: event.target.value }))
              }
              placeholder="To date"
            />
            <input
              value={historyFilters.reminded_by}
              onChange={(event) =>
                setHistoryFilters((prev) => ({ ...prev, reminded_by: event.target.value }))
              }
              placeholder="Reminded by"
            />
            <button
              className="btn"
              type="button"
              disabled={!historyForReceivableId || historyLoading}
              onClick={() => void applyHistoryFilters()}
            >
              Apply
            </button>
            <button
              className="btn"
              type="button"
              disabled={!historyForReceivableId || historyLoading}
              onClick={() => void resetHistoryFilters()}
            >
              Reset
            </button>
          </div>

          {historyLoading ? <p>Loading history...</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Reminded At</th>
                  <th>Reminder Date</th>
                  <th>Next Reminder</th>
                  <th>By</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {!historyForReceivableId ? (
                  <tr>
                    <td colSpan={5}>Use a History action to load entries.</td>
                  </tr>
                ) : reminderHistory.length === 0 ? (
                  <tr>
                    <td colSpan={5}>No reminder history yet.</td>
                  </tr>
                ) : (
                  reminderHistory.map((entry) => (
                    <tr key={`h-${entry.id}`}>
                      <td>{entry.reminded_at}</td>
                      <td>{entry.reminder_date || "-"}</td>
                      <td>{entry.next_reminder_date || "-"}</td>
                      <td>{entry.reminded_by || "-"}</td>
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
