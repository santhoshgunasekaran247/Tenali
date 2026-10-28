import { useMemo, useState } from "react";
import { api } from "../api";
import { GstReconciliation } from "../components/GstReconciliation";

type ExportState = {
  loading: boolean;
  error: string;
};

function todayIso(): string {
  const date=new Date();return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
}

function monthStartIso(): string {
  return `${todayIso().slice(0,7)}-01`;
}

function triggerCsvDownload(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export function ReportsPage() {
  const [fromDate, setFromDate] = useState<string>(monthStartIso());
  const [toDate, setToDate] = useState<string>(todayIso());
  const [asOfDate, setAsOfDate] = useState<string>(todayIso());
  const [states, setStates] = useState<Record<string, ExportState>>({});

  const periodError = useMemo(() => {
    if (!fromDate || !toDate) return "Select both period dates.";
    if (fromDate > toDate) return "From date cannot be after To date.";
    return "";
  }, [fromDate, toDate]);

  const setExportState = (key: string, next: ExportState) => {
    setStates((prev) => ({ ...prev, [key]: next }));
  };

  const runExport = async (key: string, filename: string, run: () => Promise<Blob>) => {
    setExportState(key, { loading: true, error: "" });
    try {
      const blob = await run();
      triggerCsvDownload(blob, filename);
      setExportState(key, { loading: false, error: "" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to export CSV.";
      setExportState(key, { loading: false, error: message });
    }
  };

  return (
    <div className="ops-page reports-page">
      <section className="ops-hero">
        <p className="eyebrow">Auditor Pack</p>
        <h1>Reports & Exports</h1>
        <p>
          Generate month-end and year-end CSVs from one place. Set the period once and export the
          required reports in sequence.
        </p>
      </section>

      <section className="ops-grid ops-grid-single">
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Period Filters</h2>
          </div>
          <div className="reports-filter-grid">
            <label>
              From Date
              <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
            </label>
            <label>
              To Date
              <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
            </label>
            <label>
              Aging As Of
              <input type="date" value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} />
            </label>
          </div>
          {periodError ? <p className="ops-error">{periodError}</p> : null}
        </article>

        <article className="ops-card">
          <div className="ops-card-head"><h2>Account Records</h2></div>
          <div className="reports-actions-row">
            <button className="btn" type="button" disabled={!!periodError||states.transactions?.loading} onClick={()=>void runExport('transactions',`transactions_${fromDate}_${toDate}.csv`,()=>api.exportAccountTransactionsCsv({from_date:fromDate,to_date:toDate}))}>Export Transactions</button>
            <button className="btn" type="button" disabled={!!periodError||states.journal?.loading} onClick={()=>void runExport('journal',`journal_${fromDate}_${toDate}.csv`,()=>api.exportAccountJournalCsv({from_date:fromDate,to_date:toDate}))}>Export Journal</button>
          </div>
          {states.transactions?.error?<p role="alert" className="ops-error">{states.transactions.error}</p>:null}
          {states.journal?.error?<p role="alert" className="ops-error">{states.journal.error}</p>:null}
        </article>
        <article className="ops-card">
          <div className="ops-card-head">
            <h2>GST Registers</h2>
          </div>
          <p className="ops-copy-note">Uses From/To dates.</p>
          <div className="reports-actions-row">
            <button
              className="btn"
              type="button"
              disabled={Boolean(periodError) || states.salesRegister?.loading}
              onClick={() =>
                runExport("salesRegister", "sales_register.csv", () =>
                  api.exportSalesRegisterCsv({ from_date: fromDate, to_date: toDate })
                )
              }
            >
              {states.salesRegister?.loading ? "Exporting..." : "Export Sales Register"}
            </button>
            <button
              className="btn"
              type="button"
              disabled={Boolean(periodError) || states.purchaseRegister?.loading}
              onClick={() =>
                runExport("purchaseRegister", "purchase_register.csv", () =>
                  api.exportPurchaseRegisterCsv({ from_date: fromDate, to_date: toDate })
                )
              }
            >
              {states.purchaseRegister?.loading ? "Exporting..." : "Export Purchase Register"}
            </button>
          </div>
          {states.salesRegister?.error ? <p className="ops-error">Sales register: {states.salesRegister.error}</p> : null}
          {states.purchaseRegister?.error ? <p className="ops-error">Purchase register: {states.purchaseRegister.error}</p> : null}
        </article>

        <article className="ops-card">
          <div className="ops-card-head">
            <h2>Aging Reports</h2>
          </div>
          <p className="ops-copy-note">Uses Aging As Of date.</p>
          <div className="reports-actions-row">
            <button
              className="btn"
              type="button"
              disabled={!asOfDate||states.arAging?.loading}
              onClick={() =>
                runExport("arAging", "ar_aging.csv", () =>
                  api.exportArAgingCsv({ as_of: asOfDate })
                )
              }
            >
              {states.arAging?.loading ? "Exporting..." : "Export AR Aging"}
            </button>
            <button
              className="btn"
              type="button"
              disabled={!asOfDate||states.apAging?.loading}
              onClick={() =>
                runExport("apAging", "ap_aging.csv", () =>
                  api.exportApAgingCsv({ as_of: asOfDate })
                )
              }
            >
              {states.apAging?.loading ? "Exporting..." : "Export AP Aging"}
            </button>
          </div>
          {states.arAging?.error ? <p className="ops-error">AR aging: {states.arAging.error}</p> : null}
          {states.apAging?.error ? <p className="ops-error">AP aging: {states.apAging.error}</p> : null}
        </article>
        <GstReconciliation fromDate={fromDate} toDate={toDate} invalid={!!periodError}/>
      </section>
    </div>
  );
}
