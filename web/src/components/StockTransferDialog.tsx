import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRightLeft, Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { postingKey } from "../features/postingKey";
import type { InventoryProduct, Store } from "../types";

type Line = { product_id: string; variant_id: string; quantity: string };

export function StockTransferDialog({ products, stores, onClose, onDone }:
  { products: InventoryProduct[]; stores: Store[]; onClose: () => void; onDone: () => Promise<void> | void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [from, setFrom] = useState(stores.find(store => store.is_default)?.id || stores[0]?.id || "");
  const [to, setTo] = useState(stores.find(store => store.id !== from)?.id || "");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([{ product_id: "", variant_id: "", quantity: "" }]);
  const [key] = useState(postingKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { dialog.current?.showModal(); }, []);
  const available = (productId: string, variantId: string, storeId: string) => {
    const product = products.find(item => item.id === productId);
    const item = variantId ? product?.variants.find(variant => variant.id === variantId) : product;
    return Number(item?.store_stocks?.find(entry => entry.store_id === storeId)?.quantity || 0);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.createStockTransfer({
        idempotency_key: key, from_store_id: from, to_store_id: to, transfer_date: date, reference: reference.trim() || null, notes: notes.trim(),
        lines: lines.filter(line => line.product_id).map(line => ({ product_id: line.product_id, variant_id: line.variant_id || null, quantity: Number(line.quantity) })),
      });
      await onDone();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Transfer failed."); }
    finally { setBusy(false); }
  };
  const update = (index: number, patch: Partial<Line>) => setLines(previous => previous.map((line, position) => position === index ? { ...line, ...patch } : line));
  return <dialog ref={dialog} className="inventory-dialog" aria-label="Transfer stock between stores" onCancel={event => { event.preventDefault(); onClose(); }}>
    <form className="ops-form" onSubmit={submit}>
      <div className="ops-card-head"><h2><ArrowRightLeft size={18} /> Transfer stock</h2><button type="button" className="ops-link-btn" onClick={onClose}>Close</button></div>
      <p className="ops-copy-note">Moves stock immediately between two stores of this workspace. Correct a mistake with a reverse transfer, never by editing balances.</p>
      {error ? <p role="alert" className="ops-error">{error}</p> : null}
      <fieldset disabled={busy} className="inventory-fields">
        <label>From store<select required value={from} onChange={event => setFrom(event.target.value)}>{stores.map(store => <option key={store.id} value={store.id}>{store.code} · {store.name}</option>)}</select></label>
        <label>To store<select required value={to} onChange={event => setTo(event.target.value)}>{stores.filter(store => store.id !== from).map(store => <option key={store.id} value={store.id}>{store.code} · {store.name}</option>)}</select></label>
        <label>Date<input type="date" required value={date} onChange={event => setDate(event.target.value)} /></label>
        <label>Reference<input maxLength={200} value={reference} onChange={event => setReference(event.target.value)} placeholder="Challan / vehicle" /></label>
        <label>Notes<input required maxLength={1000} value={notes} onChange={event => setNotes(event.target.value)} placeholder="Why the stock is moving" /></label>
      </fieldset>
      <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Product</th><th>Variant</th><th>Available at source</th><th>Quantity</th><th></th></tr></thead>
        <tbody>{lines.map((line, index) => {
          const product = products.find(item => item.id === line.product_id);
          const variants = product?.variants.filter(variant => variant.is_active) || [];
          return <tr key={index}>
            <td><select required aria-label={`Product ${index + 1}`} value={line.product_id} onChange={event => update(index, { product_id: event.target.value, variant_id: "" })}><option value="">Select product</option>{products.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></td>
            <td>{variants.length ? <select required aria-label={`Variant ${index + 1}`} value={line.variant_id} onChange={event => update(index, { variant_id: event.target.value })}><option value="">Select variant</option>{variants.map(variant => <option key={variant.id} value={variant.id}>{variant.variant_name}</option>)}</select> : "—"}</td>
            <td>{line.product_id ? available(line.product_id, line.variant_id, from) : ""}</td>
            <td><input required aria-label={`Quantity ${index + 1}`} type="number" min="0.001" step="0.001" value={line.quantity} onChange={event => update(index, { quantity: event.target.value })} /></td>
            <td><button type="button" className="ops-link-btn" aria-label={`Remove line ${index + 1}`} disabled={lines.length === 1} onClick={() => setLines(previous => previous.filter((_, position) => position !== index))}><Trash2 size={16} /></button></td>
          </tr>;
        })}</tbody></table></div>
      <div className="shop-actions"><button type="button" className="btn light" onClick={() => setLines(previous => [...previous, { product_id: "", variant_id: "", quantity: "" }])}><Plus size={16} />Add line</button>
        <button className="btn" disabled={busy || !to || from === to}>{busy ? "Transferring..." : "Transfer"}</button></div>
    </form>
  </dialog>;
}
