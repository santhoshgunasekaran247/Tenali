import { FloatingAlert } from "./Notifications";
import { FormEvent, useEffect, useRef, useState } from "react";
import { AlertTriangle, Ban, Trash2 } from "lucide-react";
import { api } from "../api";
import { confirmationMatches, deletionTotal, reviewState, signed } from "../features/deletions";
import type { DeletionKind, DeletionPreview, DeletionResult } from "../types";

/** Two-step reviewed deletion: impact review first, then typed confirmation with a reason. */
export function DeleteTransactionDialog({ kind, id, title, onClose, onDone }:
  { kind: DeletionKind; id: string | null; title: string; onClose: () => void; onDone: (result: DeletionResult) => Promise<void> | void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<DeletionPreview | null>(null);
  const [cascade, setCascade] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [step, setStep] = useState<"review" | "confirm">("review");
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    let live = true;
    setBusy(true); setError(""); setAcknowledged(false);
    api.deletionPreview(kind, id, cascade)
      .then(result => { if (live) setPreview(result); })
      .catch(failure => { if (live) setError(failure instanceof Error ? failure.message : "Unable to review this deletion."); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [kind, id, cascade]);

  const review = preview ? reviewState(preview, acknowledged) : { ready: false, reason: "" };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!preview || !confirmationMatches(preview, typed) || !reason.trim()) return;
    setBusy(true); setError("");
    try {
      const result = await api.deleteTransaction({ kind, id, cascade: preview.cascade, token: preview.token, confirm_text: typed.trim(), reason: reason.trim() });
      await onDone(result);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Deletion failed.");
      setStep("review");
      setAcknowledged(false);
      api.deletionPreview(kind, id, cascade).then(setPreview).catch(() => undefined);
    } finally { setBusy(false); }
  };

  return <dialog ref={dialog} className="inventory-dialog deletion-dialog" aria-label={`Delete ${title}`} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="ops-card-head"><h2><Trash2 size={18} aria-hidden="true" /> Delete {title}</h2>
      <button type="button" className="ops-link-btn" disabled={busy && step === "confirm"} onClick={onClose}>Close</button></div>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    {!preview ? <p className="ops-copy-note">{busy ? "Checking everything linked to this record..." : "Nothing to review."}</p> : step === "review" ? <>
      <p className="ops-copy-note">Step 1 of 2 · Review. {deletionTotal(preview)} record(s) will be permanently removed from your books. A full copy is kept in the deletion history.</p>
      {preview.blockers.length ? <section className="deletion-block deletion-blockers" aria-label="Blocking items">
        <h3><Ban size={16} aria-hidden="true" /> Cannot delete yet</h3><ul>{preview.blockers.map(item => <li key={item}>{item}</li>)}</ul></section> : null}
      {preview.critical.length ? <section className="deletion-block deletion-critical" aria-label="Linked records">
        <h3><AlertTriangle size={16} aria-hidden="true" /> Linked records that must go first</h3>
        <ul>{preview.critical.map(item => <li key={`${item.table}:${item.id}`}><strong>{item.title}:</strong> {item.label} <em>({item.reason})</em></li>)}</ul>
        <p className="ops-copy-note">Delete these from their own screens first, or delete everything together.</p>
        <label className="deletion-check"><input type="checkbox" checked={cascade} disabled={busy} onChange={event => setCascade(event.target.checked)} /> Delete everything together</label>
      </section> : null}
      {preview.warnings.length ? <section className="deletion-block" aria-label="Warnings"><ul>{preview.warnings.map(item => <li key={item}>{item}</li>)}</ul></section> : null}
      <section className="deletion-block" aria-label="Records that will be deleted"><h3>Will be deleted</h3>
        {preview.deletes.map(group => <details key={group.table} open={group.items.length > 0 && group.items.length <= 5}>
          <summary>{group.title} · {group.count}</summary>
          {group.items.length ? <ul>{group.items.map(item => <li key={item.id}>{item.label}{item.critical ? <em> · {item.critical}</em> : null}</li>)}</ul> : null}
        </details>)}
      </section>
      {preview.stock_changes.length ? <section className="deletion-block" aria-label="Stock changes"><h3>Stock changes</h3>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Product</th><th>Store</th><th>Now</th><th>Change</th><th>After</th></tr></thead>
          <tbody>{preview.stock_changes.map(row => <tr key={`${row.store_code}:${row.product_name}`} className={row.after < 0 ? "deletion-negative" : undefined}>
            <td>{row.product_name}</td><td>{row.store_code}</td><td>{row.current}</td><td>{signed(row.change)}</td><td>{row.after}</td></tr>)}</tbody></table></div></section> : null}
      {preview.account_changes.length ? <section className="deletion-block" aria-label="Account balance changes"><h3>Account balance changes</h3>
        <ul>{preview.account_changes.map(row => <li key={row.account_id}>{row.account_name}: {signed(row.change)}</li>)}</ul></section> : null}
      {!preview.blockers.length && (!preview.critical.length || preview.cascade) ? <label className="deletion-check">
        <input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /> I have reviewed every record above and understand this cannot be undone from the app.</label> : null}
      {!review.ready && review.reason ? <p className="ops-copy-note">{review.reason}</p> : null}
      <div className="shop-actions"><button type="button" className="btn light" onClick={onClose}>Keep records</button>
        <button type="button" className="btn deletion-danger" disabled={busy || !review.ready} onClick={() => { setTyped(""); setStep("confirm"); }}>Continue</button></div>
    </> : <form className="ops-form" onSubmit={submit}>
      <p className="ops-copy-note">Step 2 of 2 · Confirm. {deletionTotal(preview)} record(s) will be deleted{preview.cascade ? ", including the linked records" : ""}.</p>
      <label>Type <strong className="deletion-phrase">{preview.confirm_text}</strong> to confirm
        <input required autoComplete="off" value={typed} onChange={event => setTyped(event.target.value)} aria-label="Confirmation text" /></label>
      <label>Reason<textarea required maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} placeholder="Why these records are being deleted" /></label>
      <div className="shop-actions"><button type="button" className="btn light" disabled={busy} onClick={() => setStep("review")}>Back</button>
        <button className="btn deletion-danger" disabled={busy || !confirmationMatches(preview, typed) || !reason.trim()}>{busy ? "Deleting..." : "Delete permanently"}</button></div>
    </form>}
  </dialog>;
}
