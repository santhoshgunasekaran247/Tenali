import { useState } from "react";
import type { InventoryMissingSource, InventoryReconciliation } from "../types";

export function StockCheckPanel({ rows, missingSources, busy, onOpen, onAttribute }: {
  rows: InventoryReconciliation[];
  missingSources: InventoryMissingSource[];
  busy: boolean;
  onOpen: (productId: string) => void;
  onAttribute: (movementId: string, reference: string, notes: string) => Promise<void>;
}) {
  const [showAll, setShowAll] = useState(false);
  const [storeId, setStoreId] = useState("");
  const [sourceForm, setSourceForm] = useState<Record<string, {reference: string; notes: string}>>({});
  const stores = [...new Map(rows.map(row => [row.store_id, row.store_code])).entries()];
  const scoped = rows.filter(row => !storeId || row.store_id === storeId);
  const differences = scoped.filter(row => Number(row.difference) !== 0);
  const sourceCount = scoped.reduce((total, row) => total + Number(row.missing_document_references), 0);
  const visible = showAll ? scoped : scoped.filter(row => Number(row.difference) !== 0 || Number(row.missing_document_references) > 0);
  const missing = missingSources.filter(row => !storeId || row.store_id === storeId);
  return <section className="ops-card stock-check" aria-labelledby="stock-check-title">
    <h2 id="stock-check-title">Check stock records</h2>
    <p>Does the quantity on hand match the recorded stock activity? This checks your records, not the items physically on your shelves.</p>
    <div className="inventory-summary" aria-label="Stock check summary">
      <div><span>Quantity mismatches</span><strong>{differences.length}</strong></div>
      <div><span>Missing source documents</span><strong>{sourceCount}</strong></div>
      <div><span>Product / store entries checked</span><strong>{scoped.length}</strong></div>
    </div>
    <div className="inventory-toolbar">
      <label>Store<select value={storeId} onChange={event => setStoreId(event.target.value)}><option value="">All permitted stores</option>
        {stores.map(([id, code]) => <option key={id} value={id}>{code}</option>)}</select></label>
      <label className="inventory-check"><input type="checkbox" checked={showAll} onChange={event => setShowAll(event.target.checked)} />Show matching entries too</label>
    </div>
    {!scoped.length ? <p role="status">No stock activity yet. Products with no stock records start at zero and need no reconciliation.</p> :
      !differences.length && !sourceCount ? <p className="stock-check-ok" role="status">All recorded quantities match. No missing source documents.</p> : null}
    {visible.length ? <div className="ops-table-wrap"><table className="ops-table">
      <thead><tr><th>Store</th><th>Product / variant</th>
        <th title="Quantity currently stored as on hand">On hand</th>
        <th title="All stock added minus all stock removed">Expected from activity</th>
        <th title="On hand minus expected. Zero means the records match.">Difference</th><th>What to do</th></tr></thead>
      <tbody>{visible.map(row => <tr key={`${row.store_id}:${row.product_id}:${row.variant_id || "base"}`}>
        <td>{row.store_code}</td><td><button className="ops-link-btn" type="button" onClick={() => onOpen(row.product_id)}>{row.product_name}</button><small>{row.variant_name}</small></td>
        <td>{Number(row.balance_quantity)}</td><td>{Number(row.movement_quantity)}</td>
        <td>{Number(row.difference) > 0 ? "+" : ""}{Number(row.difference)}</td>
        <td>{Number(row.difference) !== 0 ? "Review stock history and compare it with a physical count." : "Quantities match."}
          {Number(row.missing_document_references) > 0 ? <small>{row.missing_document_references} source document(s) need investigation.</small> : null}</td>
      </tr>)}</tbody></table></div> : null}
    <details className="stock-check-help"><summary>How to read this check</summary>
      <ul><li><strong>On hand:</strong> the quantity the system currently says you own.</li>
        <li><strong>Expected from activity:</strong> opening adjustments, purchases and transfers in, minus sales and transfers out.</li>
        <li><strong>Difference:</strong> on hand minus expected. For example, 10 on hand and 8 expected gives +2.</li>
        <li><strong>Missing source:</strong> a movement still exists but its invoice, purchase, order or transfer cannot be found. This is separate from a quantity mismatch.</li></ul>
      <p>Start by opening the product's Owned Stock tab. Do not add a stock adjustment just to hide a record mismatch: adjustments change both the balance and the activity. Investigate the original records first.</p>
    </details>
    {missing.length ? <details className="stock-check-help"><summary>Record evidence for {missing.length} missing invoice / purchase document(s)</summary>
      <p>Only use this when a genuine paper or external document exists. Adding a reference does not change stock or recreate the missing document. Missing orders and transfers must be investigated separately.</p>
      <div className="stock-evidence-list">{missing.map(item => {
        const form = sourceForm[item.id] || {reference: "", notes: ""};
        return <article className="stock-evidence" key={item.id}>
          <h3>{item.product_name}{item.variant_name ? ` - ${item.variant_name}` : ""}</h3>
          <p>{item.store_code} / {item.created_at.slice(0, 10)} / {item.movement_type.split("_").join(" ")} / Qty {Number(item.quantity)}</p>
          <label>External document number<input aria-label={`External document ${item.id}`} maxLength={200} value={form.reference} placeholder="Actual vendor bill or invoice number"
            onChange={event => setSourceForm(previous => ({...previous, [item.id]: {...form, reference: event.target.value}}))} /></label>
          <label>Where is the evidence?<input aria-label={`Source notes ${item.id}`} maxLength={1000} value={form.notes} placeholder="Where the original document is filed"
            onChange={event => setSourceForm(previous => ({...previous, [item.id]: {...form, notes: event.target.value}}))} /></label>
          <button className="btn light" type="button" disabled={busy || !form.reference.trim() || !form.notes.trim()}
            onClick={() => void onAttribute(item.id, form.reference.trim(), form.notes.trim())}>Save document reference</button>
        </article>;
      })}</div>
    </details> : null}
  </section>;
}
