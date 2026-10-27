import { Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import type { HsnMaster, InvoiceLineInput } from "../types";

export const newTaxLine = (): InvoiceLineInput => ({ description: "", hsn: "", quantity: 1, rate: 0, gst_rate: 0 });

export function calculateLineTotals(lines: InvoiceLineInput[]) {
  let subtotalCents = 0;
  let gstCents = 0;
  for (const line of lines) {
    const taxableCents = Math.round((line.quantity * line.rate + Number.EPSILON) * 100);
    subtotalCents += taxableCents;
    gstCents += Math.round((taxableCents * line.gst_rate / 100) + Number.EPSILON);
  }
  return { subtotal: subtotalCents / 100, gstTotal: gstCents / 100, total: (subtotalCents + gstCents) / 100 };
}

export function TaxLinesEditor({ lines, masters, onChange, disabled = false }: {
  lines: InvoiceLineInput[];
  masters: HsnMaster[];
  onChange: (lines: InvoiceLineInput[]) => void;
  disabled?: boolean;
}) {
  const updateLine = (index: number, patch: Partial<InvoiceLineInput>) => {
    onChange(lines.map((line, position) => position === index ? { ...line, ...patch } : line));
  };
  const { subtotal, gstTotal, total } = calculateLineTotals(lines);
  return <>
    <fieldset className="invoice-lines" disabled={disabled}>
      <legend>Items</legend>
      <Link className="ops-inline-link" to="/portal/masters/hsn">Manage HSN / GST</Link>
      {lines.map((line, index) => <div className="invoice-line" key={index}>
        <div className="invoice-line-heading">
          <strong>Item {index + 1}</strong>
          <button className="ops-link-btn" type="button" title="Remove item" aria-label={`Remove item ${index + 1}`}
            disabled={lines.length === 1} onClick={() => onChange(lines.filter((_, position) => position !== index))}>
            <Trash2 size={16} aria-hidden="true" />
          </button>
        </div>
        <label>Product / Description
          <input required maxLength={500} value={line.description} onChange={(event) => updateLine(index, { description: event.target.value })} />
        </label>
        <label>HSN / SAC
          <select required value={line.hsn} onChange={(event) => {
            const selected = masters.find((master) => master.code === event.target.value);
            updateLine(index, { hsn: selected?.code || "", gst_rate: selected ? Number(selected.gst_rate) : 0 });
          }}>
            <option value="">{masters.length ? "Select HSN / SAC" : "No active HSN / SAC codes"}</option>
            {line.hsn && !masters.some((master) => master.code === line.hsn) ? <option value={line.hsn} disabled>{line.hsn} (unavailable)</option> : null}
            {masters.map((master) => <option value={master.code} key={master.id}>{master.code} - {master.description} ({Number(master.gst_rate)}%)</option>)}
          </select>
        </label>
        <div className="invoice-line-values">
          <label>Quantity<input required type="number" min="0.001" step="0.001" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
          <label>Rate (INR)<input required type="number" min="0" step="0.01" value={line.rate} onChange={(event) => updateLine(index, { rate: Number(event.target.value) })} /></label>
          <label>GST %<input type="number" readOnly value={line.gst_rate} /></label>
        </div>
      </div>)}
      <button className="ops-link-btn" type="button" disabled={lines.length >= 200} onClick={() => onChange([...lines, newTaxLine()])}>
        <Plus size={16} aria-hidden="true" /> Add Item
      </button>
    </fieldset>
    <dl className="invoice-totals">
      <div><dt>Taxable Value</dt><dd>INR {subtotal.toFixed(2)}</dd></div>
      <div><dt>Total GST</dt><dd>INR {gstTotal.toFixed(2)}</dd></div>
      <div><dt>Total</dt><dd>INR {total.toFixed(2)}</dd></div>
    </dl>
  </>;
}