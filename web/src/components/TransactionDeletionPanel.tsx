import { FloatingAlert } from "./Notifications";
import { useEffect, useState } from "react";
import { History, Trash2 } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../features/auth";
import { canDeleteTransactions } from "../features/deletions";
import { DeleteTransactionDialog } from "./DeleteTransactionDialog";
import type { DeletionHistoryItem } from "../types";

/** Owner/admin area: erase every transaction and see what was deleted, when, by whom and why. */
export function TransactionDeletionPanel() {
  const { user } = useAuth();
  const allowed = canDeleteTransactions(user?.role);
  const [items, setItems] = useState<DeletionHistoryItem[]>([]);
  const [resetOpen, setResetOpen] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = () => api.deletionHistory().then(result => setItems(result.items))
    .catch(failure => setError(failure instanceof Error ? failure.message : "Unable to load deletion history."));
  useEffect(() => { if (allowed) void load(); }, [allowed]);
  if (!allowed) return null;
  return <section id="transaction-deletions" className="company-setup-section deletion-panel" aria-label="Deleted transactions">
    <h2><History size={18} aria-hidden="true" /> Deleted transactions</h2>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {message ? <FloatingAlert tone="success">{message}</FloatingAlert> : null}
    <p className="ops-copy-note">Purchases, payments, account entries, stock adjustments, transfers and COD settlements can be deleted from their own screens.
      Issued sales invoices are cancelled instead (use Reissue for a corrected copy). Every deletion is reviewed twice and a full copy is kept here.</p>
    <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>When</th><th>What</th><th>Records</th><th>By</th><th>Reason</th></tr></thead>
      <tbody>{items.length ? items.map(item => <tr key={item.id}><td>{new Date(item.deleted_at).toLocaleString()}</td><td>{item.label}</td>
        <td>{(item.deletes || []).map(group => `${group.title} ${group.count}`).join(", ")}</td><td>{item.deleted_by || ""}</td><td>{item.reason}</td></tr>)
        : <tr><td colSpan={5}>Nothing has been deleted.</td></tr>}</tbody></table></div>
    <div className="deletion-block deletion-blockers">
      <h3><Trash2 size={16} aria-hidden="true" /> Erase all transactions</h3>
      <p>Removes every sale, purchase, payment, account entry, stock movement and online order record of this workspace and sets all stock to zero.
        Products, customers, vendors, accounts, stores and settings are kept. Use this only to clear test data before going live.</p>
      <button type="button" className="btn deletion-danger" onClick={() => setResetOpen(true)}>Review erase all</button>
    </div>
    {resetOpen ? <DeleteTransactionDialog kind="all" id={null} title="all transactions" onClose={() => setResetOpen(false)}
      onDone={async () => { setResetOpen(false); setMessage("All transactions were erased."); await load(); }} /> : null}
  </section>;
}
