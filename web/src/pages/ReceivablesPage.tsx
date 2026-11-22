import { CursorPagination } from "../components/CursorPagination";
import { FloatingAlert } from "../components/Notifications";
import { useDraftState } from "../features/drafts";
import { FormEvent, useEffect, useRef, useState } from "react";
import { PartySelect } from "../components/PartySelect";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { receivablesClient } from "../features/receivablesClient";
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
  const storeIdQuery = searchParams.get("store_id") || undefined;
  const [parties, setParties] = useState<Party[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [receivables, setReceivables] = useState<Receivable[]>([]);
  const [selectionSearch, setSelectionSearch] = useState("");
  const [selectionCursors, setSelectionCursors] = useState<Array<string | null>>([null]);
  const [selectionPage, setSelectionPage] = useState(0);
  const [selectionSize, setSelectionSize] = useState(25);
  const [selectionNext, setSelectionNext] = useState<string | null>(null);
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [selectedReceivable, setSelectedReceivable] = useState<Receivable | null>(null);
  const [selectionRefresh, setSelectionRefresh] = useState(0);
  const selectionVersion = useRef(0);
  const resolutionVersion = useRef(0);
  const [ledgerRows, setLedgerRows] = useState<Receivable[]>([]);
  const [ledgerSize, setLedgerSize] = useState(25);
  const [ledgerCursors, setLedgerCursors] = useState<Array<string | null>>([null]);
  const [ledgerPage, setLedgerPage] = useState(0);
  const [ledgerNext, setLedgerNext] = useState<string | null>(null);
  const loadVersion = useRef(0);
  const [reminders, setReminders] = useState<Receivable[]>([]);
  const [dueSize, setDueSize] = useState(25);
  const [dueCursors, setDueCursors] = useState<Array<string | null>>([null]);
  const [duePage, setDuePage] = useState(0);
  const [dueNext, setDueNext] = useState<string | null>(null);
  const [dueAsOf, setDueAsOf] = useState("");
  const [dueLoading, setDueLoading] = useState(false);
  const dueVersion = useRef(0);
  const [statusFilter, setStatusFilter] = useState(
    statusQuery && statusQuery !== "OPEN" ? statusQuery : ""
  );
  const [showOpenOnly, setShowOpenOnly] = useState(!statusQuery || statusQuery === "OPEN");
  const [receivableForm, setReceivableForm] = useDraftState<ReceivableForm>("ReceivablesPage.receivableForm", EMPTY_RECEIVABLE_FORM);
  const [collectionForm, setCollectionForm] = useDraftState<CollectionForm>("ReceivablesPage.collectionForm", createEmptyCollectionForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [badDebtTarget, setBadDebtTarget] = useState<Receivable | null>(null);
  const [badDebtReason, setBadDebtReason] = useState("");
  const [badDebtConfirmed, setBadDebtConfirmed] = useState(false);
  const [badDebtSaving, setBadDebtSaving] = useState(false);
  const [badDebtError, setBadDebtError] = useState("");
  const badDebtDialog = useRef<HTMLDialogElement>(null);
  const [remindingId, setRemindingId] = useState<string | null>(null);
  const [nextReminderById, setNextReminderById] = useDraftState<Record<string, string>>("ReceivablesPage.nextReminderById", {});
  const [historyForReceivableId, setHistoryForReceivableId] = useState<string | null>(null);
  const [historyForReceivableLabel, setHistoryForReceivableLabel] = useState<string>("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [reminderHistory, setReminderHistory] = useState<ReceivableReminderLog[]>([]);
  const [historySize, setHistorySize] = useState(25);
  const [historyCursors, setHistoryCursors] = useState<Array<string | null>>([null]);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const [appliedHistoryFilters, setAppliedHistoryFilters] = useState<ReminderHistoryFilters>(EMPTY_HISTORY_FILTERS);
  const historyVersion = useRef(0);
  const [historyFilters, setHistoryFilters] = useState<ReminderHistoryFilters>(
    EMPTY_HISTORY_FILTERS
  );
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const remindersRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (badDebtTarget) badDebtDialog.current?.showModal();
  }, [badDebtTarget]);

  useEffect(() => {
    setLedgerCursors([null]); setLedgerPage(0);
    if (!statusQuery) {
      setStatusFilter("");
      setShowOpenOnly(true);
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
    if (!loading && focusQuery === "reminders") {
      remindersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focusQuery, loading]);

  const load = async () => {
    const version = ++loadVersion.current;
    setLoading(true);
    setLedgerRows([]); setLedgerNext(null);
    setError(null);
    try {
      const ledgerRes = await receivablesClient.ledger({ status: statusFilter || undefined, open_only: showOpenOnly, store_id: storeIdQuery, page_size: ledgerSize, cursor: ledgerCursors[ledgerPage] });
      if (version !== loadVersion.current) return;
      setLedgerRows(ledgerRes.items);
      setLedgerNext(ledgerRes.next_cursor || null);
    } catch (loadError) {
      if (version === loadVersion.current) setError(loadError instanceof Error ? loadError.message : "Unable to load receivables.");
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => { loadVersion.current++; };
  }, [statusFilter, showOpenOnly, ledgerSize, ledgerCursors, ledgerPage, storeIdQuery]);

  useEffect(() => {
    let active = true;
    void Promise.all([api.parties({ active_only: true }), api.accounts({ active_only: true })])
      .then(([partyRes, accountRes]) => { if (active) { setParties(partyRes.items); setAccounts(accountRes.items); } })
      .catch(failure => { if (active) setError(failure instanceof Error ? failure.message : "Unable to load contacts and accounts."); });
    return () => { active = false; };
  }, [storeIdQuery]);

  useEffect(() => {
    const version = ++selectionVersion.current;
    setSelectionLoading(true); setReceivables([]); setSelectionNext(null);
    void receivablesClient.ledger({ page_size: selectionSize, open_only: true, search: selectionSearch, cursor: selectionCursors[selectionPage], store_id: storeIdQuery })
      .then(response => {
        if (version !== selectionVersion.current) return;
        setReceivables(response.items); setSelectionNext(response.next_cursor || null);
      })
      .catch(failure => { if (version === selectionVersion.current) setError(failure instanceof Error ? failure.message : "Unable to load collection choices."); })
      .finally(() => { if (version === selectionVersion.current) setSelectionLoading(false); });
    return () => { selectionVersion.current++; };
  }, [selectionSearch, selectionCursors, selectionPage, selectionSize, storeIdQuery, selectionRefresh]);

  useEffect(() => {
    if (!invoiceIdQuery) return;
    const version = ++resolutionVersion.current;
    setSelectedReceivable(null);
    void receivablesClient.ledger({ invoice_id: invoiceIdQuery, page_size: 1, store_id: storeIdQuery })
      .then(response => {
        if (version !== resolutionVersion.current) return;
        const match = response.items[0];
        setSelectedReceivable(match || null);
        if (match && invoiceIdQuery) setCollectionForm(prev => ({
          ...prev, receivable_id: match.id, amount: prev.amount || String(match.balance_amount),
        }));
      })
      .catch(failure => { if (version === resolutionVersion.current) setError(failure instanceof Error ? failure.message : "Unable to resolve selected receivable."); });
    return () => { resolutionVersion.current++; };
  }, [invoiceIdQuery, storeIdQuery, selectionRefresh]);

  useEffect(() => {
    if (invoiceIdQuery || !collectionForm.receivable_id) return;
    const version = ++resolutionVersion.current;
    setSelectedReceivable(null);
    void receivablesClient.ledger({ receivable_id: collectionForm.receivable_id, page_size: 1, store_id: storeIdQuery })
      .then(response => { if (version === resolutionVersion.current) setSelectedReceivable(response.items[0] || null); })
      .catch(failure => { if (version === resolutionVersion.current) setError(failure instanceof Error ? failure.message : "Unable to resolve selected receivable."); });
    return () => { resolutionVersion.current++; };
  }, [collectionForm.receivable_id, storeIdQuery, selectionRefresh, invoiceIdQuery]);

  const loadDue = async () => {
    const version = ++dueVersion.current;
    setDueLoading(true); setReminders([]); setDueNext(null);
    try {
      const response = await receivablesClient.due({ page_size: dueSize, cursor: dueCursors[duePage], as_of: dueAsOf || undefined, store_id: storeIdQuery });
      if (version !== dueVersion.current) return;
      setReminders(response.items); setDueNext(response.next_cursor || null);
    } catch (failure) {
      if (version === dueVersion.current) setError(failure instanceof Error ? failure.message : "Unable to load reminders.");
    } finally {
      if (version === dueVersion.current) setDueLoading(false);
    }
  };

  useEffect(() => {
    void loadDue();
    return () => { dueVersion.current++; };
  }, [dueSize, dueCursors, duePage, dueAsOf, storeIdQuery]);

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
      setSelectionRefresh(value => value + 1);
      await load();
      await loadDue();
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
      setSelectedReceivable(null); setSelectionRefresh(value => value + 1);
      await load();
      await loadDue();
    } catch (collectError) {
      setError(collectError instanceof Error ? collectError.message : "Unable to collect payment.");
    } finally {
      setCollecting(false);
    }
  };

  const markBadDebt = async (event: FormEvent) => {
    event.preventDefault();
    if (!badDebtTarget || !badDebtReason.trim() || !badDebtConfirmed || badDebtSaving || badDebtError) return;
    setBadDebtSaving(true);
    try {
      await api.updateReceivable(badDebtTarget.id, {
        status: "BAD_DEBT",
        bad_debt_reason: badDebtReason.trim(),
      });
      setSuccess("Receivable marked as bad debt.");
      setSelectionRefresh(value => value + 1);
      setBadDebtTarget(null);
      await load();
      await loadDue();
    } catch (updateError) {
      setBadDebtError(`${updateError instanceof Error ? updateError.message : "Unable to confirm the result."} Close and refresh the ledger to check the status before trying again.`);
    } finally { setBadDebtSaving(false); }
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
      await loadDue();
      if (historyForReceivableId === receivableId) await loadHistory();
    } catch (reminderError) {
      setError(reminderError instanceof Error ? reminderError.message : "Unable to mark reminder.");
    } finally {
      setRemindingId(null);
    }
  };

  const openReminderHistory = (receivableId: string, label: string) => {
    historyVersion.current++;
    setHistoryForReceivableId(receivableId);
    setHistoryForReceivableLabel(label);
    setAppliedHistoryFilters({ ...historyFilters });
    setHistoryCursors([null]); setHistoryPage(0);
  };

  const loadHistory = async () => {
    if (!historyForReceivableId) return;
    const version = ++historyVersion.current;
    setError(null);
    setHistoryLoading(true);
    setReminderHistory([]); setHistoryNext(null);
    try {
      const response = await receivablesClient.history(historyForReceivableId, {
        from_date: appliedHistoryFilters.from_date || undefined,
        to_date: appliedHistoryFilters.to_date || undefined,
        reminded_by: appliedHistoryFilters.reminded_by || undefined,
        page_size: historySize, cursor: historyCursors[historyPage], store_id: storeIdQuery,
      });
      if (version !== historyVersion.current) return;
      setReminderHistory(response.items);
      setHistoryNext(response.next_cursor || null);
    } catch (historyError) {
      if (version !== historyVersion.current) return;
      setError(
        historyError instanceof Error ? historyError.message : "Unable to load reminder history."
      );
      setReminderHistory([]);
    } finally {
      if (version === historyVersion.current) setHistoryLoading(false);
    }
  };

  useEffect(() => {
    void loadHistory();
    return () => { historyVersion.current++; };
  }, [historyForReceivableId, appliedHistoryFilters, historySize, historyCursors, historyPage, storeIdQuery]);

  const applyHistoryFilters = async () => {
    if (!historyForReceivableId) return;
    setAppliedHistoryFilters({ ...historyFilters });
    setHistoryCursors([null]); setHistoryPage(0);
  };

  const resetHistoryFilters = async () => {
    setHistoryFilters(EMPTY_HISTORY_FILTERS);
    if (!historyForReceivableId) return;
    setAppliedHistoryFilters(EMPTY_HISTORY_FILTERS);
    setHistoryCursors([null]); setHistoryPage(0);
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

      {success ? <FloatingAlert tone="success">{success}</FloatingAlert> : null}

      <section className="ops-grid">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Create Receivable</h2>
          </div>
          <form className="ops-form" onSubmit={createReceivable}>
            <PartySelect parties={parties} value={receivableForm.party_id} label="Contact" required
              onChange={id => setReceivableForm(previous => ({ ...previous, party_id: id }))} />
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
            <label>Search open receivables
              <input type="search" value={selectionSearch} placeholder="Contact or reference"
                onChange={event => { setSelectionSearch(event.target.value); setSelectionCursors([null]); setSelectionPage(0); }} />
            </label>
            <label>
              Receivable
              <select
                value={collectionForm.receivable_id}
                onChange={event => {
                  setSelectedReceivable(receivables.find(item => item.id === event.target.value) || null);
                  setCollectionForm(prev => ({ ...prev, receivable_id: event.target.value }));
                }}
                required
              >
                <option value="">Select receivable</option>
                {selectedReceivable && !receivables.some(item => item.id === selectedReceivable.id) ?
                  <option value={selectedReceivable.id} disabled={!["UNPAID", "PARTIAL"].includes(selectedReceivable.status)}>
                    {selectedReceivable.party_name} - {selectedReceivable.reference || selectedReceivable.id} - {selectedReceivable.status} - Bal {selectedReceivable.balance_amount.toFixed(2)}
                  </option> : null}
                {receivables
                  .filter((item) => item.status === "UNPAID" || item.status === "PARTIAL")
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.party_name} - {item.reference || item.id} - Bal {item.balance_amount.toFixed(2)}
                    </option>
                  ))}
              </select>
            </label>
            <CursorPagination size={selectionSize} page={selectionPage} hasNext={!!selectionNext} busy={selectionLoading} onSize={size => { setSelectionSize(size); setSelectionCursors([null]); setSelectionPage(0); }} onPrevious={() => setSelectionPage(page => page - 1)} onNext={() => { if (selectionNext) { setSelectionCursors(previous => [...previous.slice(0, selectionPage + 1), selectionNext]); setSelectionPage(page => page + 1); } }} />
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
            <span className="catalog-count">{ledgerRows.length} records on this page</span>
          </div>

          <div className="ops-list-tools">
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setShowOpenOnly(false);
                setLedgerCursors([null]); setLedgerPage(0);
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
                  setLedgerCursors([null]); setLedgerPage(0);
                  if (event.target.checked) {
                    setStatusFilter("");
                  }
                }}
              />
              Open only
            </label>
            <button className="btn" type="button" onClick={() => { setSelectionRefresh(value => value + 1); void Promise.all([load(), loadDue(), loadHistory()]); }}>
              Refresh
            </button>
            <button className="btn" type="button" onClick={exportArAgingCsv}>
              Export AR Aging
            </button>
          </div>

          {error ? <FloatingAlert>{error}</FloatingAlert> : null}
          {loading ? <p>Loading...</p> : null}

          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Contact</th>
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
                    <td colSpan={8}>{loading ? "Loading receivables..." : error ? "Unable to load receivables." : "No receivables on this page."}</td>
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
                              onClick={() => { setBadDebtReason(""); setBadDebtConfirmed(false); setBadDebtError(""); setBadDebtTarget(item); }}
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
          <CursorPagination size={ledgerSize} page={ledgerPage} hasNext={!!ledgerNext} busy={loading} onSize={size => { setLedgerSize(size); setLedgerCursors([null]); setLedgerPage(0); }} onPrevious={() => setLedgerPage(page => page - 1)} onNext={() => { if (ledgerNext) { setLedgerCursors(previous => [...previous.slice(0, ledgerPage + 1), ledgerNext]); setLedgerPage(page => page + 1); } }} />
        </article>

        <article className="ops-card ops-list-card" ref={remindersRef}>
          <div className="ops-card-head">
            <h2>Due Reminders</h2>
            <span className="catalog-count">{reminders.length} on this page</span>
          </div>
          <label>Due as of (blank = today)<input type="date" value={dueAsOf} onChange={event => { setDueAsOf(event.target.value); setDueCursors([null]); setDuePage(0); }} /></label>
          <div className="ops-table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Contact</th>
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
                    <td colSpan={7}>{dueLoading ? "Loading reminders..." : "No reminders due on this page."}</td>
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
          <CursorPagination size={dueSize} page={duePage} hasNext={!!dueNext} busy={dueLoading || !!remindingId} onSize={size => { setDueSize(size); setDueCursors([null]); setDuePage(0); }} onPrevious={() => setDuePage(page => page - 1)} onNext={() => { if (dueNext) { setDueCursors(previous => [...previous.slice(0, duePage + 1), dueNext]); setDuePage(page => page + 1); } }} />
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
                    <td colSpan={5}>{historyLoading ? "Loading history..." : "No reminder history on this page."}</td>
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
          <CursorPagination size={historySize} page={historyPage} hasNext={!!historyNext} busy={historyLoading || !historyForReceivableId} onSize={size => { setHistorySize(size); setHistoryCursors([null]); setHistoryPage(0); }} onPrevious={() => setHistoryPage(page => page - 1)} onNext={() => { if (historyNext) { setHistoryCursors(previous => [...previous.slice(0, historyPage + 1), historyNext]); setHistoryPage(page => page + 1); } }} />
        </article>
      </section>
      {badDebtTarget ? <dialog ref={badDebtDialog} className="inventory-dialog" aria-labelledby="bad-debt-title" onCancel={event => { event.preventDefault(); if (!badDebtSaving) setBadDebtTarget(null); }}>
        <form className="ops-form" onSubmit={event => void markBadDebt(event)}>
          <h2 id="bad-debt-title">Mark receivable as bad debt</h2>
          <p>{badDebtTarget.party_name} · {badDebtTarget.reference || "No reference"} · balance {badDebtTarget.balance_amount.toFixed(2)}</p>
          <p>Collections are blocked while this receivable is marked bad debt. This changes its status; it does not record a payment.</p>
          {badDebtError ? <p role="alert" className="ops-error">{badDebtError}</p> : null}
          <label>Reason<textarea required maxLength={1000} value={badDebtReason} disabled={badDebtSaving} onChange={event => setBadDebtReason(event.target.value)} /></label>
          <label className="ops-toggle"><input type="checkbox" checked={badDebtConfirmed} disabled={badDebtSaving} onChange={event => setBadDebtConfirmed(event.target.checked)} />I understand collections will be blocked.</label>
          <div className="shop-actions"><button type="button" disabled={badDebtSaving} onClick={() => { setBadDebtTarget(null); if (badDebtError) void load(); }}>Cancel / check ledger</button>
            <button type="submit" className="btn" disabled={badDebtSaving || !badDebtReason.trim() || !badDebtConfirmed || !!badDebtError}>{badDebtSaving ? "Saving..." : "Mark bad debt"}</button></div>
        </form>
      </dialog> : null}
    </div>
  );
}
