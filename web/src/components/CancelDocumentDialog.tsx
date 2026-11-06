import { FormEvent, useEffect, useRef, useState } from "react";
import { Ban } from "lucide-react";
import { api } from "../api";
import { canConfirmCancel, cancellationEffects, type CancelKind } from "../features/cancellation";
import type { CancellationResult } from "../types";
import { FloatingAlert } from "./Notifications";

/** Cancels an invoice or purchase bill; any payments are reversed into pending refunds, never deleted. */
export function CancelDocumentDialog({ kind, id, number, paid, onClose, onDone }:
  { kind: CancelKind; id: string; number: string; paid: number; onClose: () => void; onDone: (result: CancellationResult) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { dialog.current?.showModal(); }, []);
  const label = kind === "invoice" ? "invoice" : "bill";
  const ready = canConfirmCancel({ reason, paid, acknowledged, typed, number });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true); setError("");
    try {
      const reverse = paid > 0;
      const result = kind === "invoice" ? await api.cancelInvoice(id, reason.trim(), reverse) : await api.cancelPurchase(id, reason.trim(), reverse);
      onDone(result);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : `Unable to cancel this ${label}.`);
    } finally { setBusy(false); }
  };

  return <dialog ref={dialog} className="inventory-dialog deletion-dialog" aria-label={`Cancel ${label} ${number}`}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="ops-card-head"><h2><Ban size={18} aria-hidden="true" /> Cancel {label} {number}</h2>
      <button type="button" className="ops-link-btn" disabled={busy} onClick={onClose}>Close</button></div>
    {error ? <FloatingAlert>{error}</FloatingAlert> : null}
    <form className="ops-form" onSubmit={submit}>
      <section className={`deletion-block${paid > 0 ? " deletion-critical" : ""}`} aria-label="What will happen">
        <ul>{cancellationEffects(kind, paid).map(item => <li key={item}>{item}</li>)}</ul>
      </section>
      <label>Reason<textarea required maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason (kept with the cancelled document)" /></label>
      {paid > 0 ? <label className="deletion-check"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />
        I understand the payments will be reversed and must be settled as refunds.</label> : null}
      <label>Type <strong className="deletion-phrase">{number}</strong> to confirm
        <input required autoComplete="off" value={typed} onChange={event => setTyped(event.target.value)} aria-label="Confirmation text" /></label>
      <div className="shop-actions"><button type="button" className="btn light" disabled={busy} onClick={onClose}>Keep {label}</button>
        <button className="btn deletion-danger" disabled={busy || !ready}>{busy ? "Cancelling..." : `Cancel ${label}`}</button></div>
    </form>
  </dialog>;
}
