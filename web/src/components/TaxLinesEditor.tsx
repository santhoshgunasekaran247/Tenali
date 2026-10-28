import { Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import type { HsnMaster, InvoiceLineInput, InventoryProduct } from "../types";

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

export function TaxLinesEditor({ lines, masters, onChange, disabled = false, products = [], vendorId }: {
  lines: InvoiceLineInput[];
  masters: HsnMaster[];
  onChange: (lines: InvoiceLineInput[]) => void;
  disabled?: boolean;
  products?: InventoryProduct[];
  vendorId?: string;
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
        <label>Product / Inventory
          <select value={line.product_id||""} onChange={event=>{
            const product=products.find(item=>item.id===event.target.value);
            const offer=product?.offers.find(item=>item.vendor_id===vendorId&&item.is_active);
            updateLine(index,product?{product_id:product.id,variant_id:null,description:product.name,hsn:product.hsn_code||"",gst_rate:Number(masters.find(item=>item.code===product.hsn_code)?.gst_rate||0),rate:Number(vendorId?offer?.buying_price||0:product.catalog_price||0)}:{product_id:null,variant_id:null,description:"",hsn:"",gst_rate:0,rate:0});
          }}><option value="">Manual / service item</option>{products.filter(product=>product.is_active&&(!vendorId||[...product.offers,...product.variants.flatMap(variant=>variant.offers)].some(offer=>offer.vendor_id===vendorId&&offer.is_active))).map(product=><option key={product.id} value={product.id}>{product.name} ({product.portal_product_id})</option>)}</select>
        </label>
        {line.product_id&&products.find(item=>item.id===line.product_id)?.variants.some(variant=>variant.is_active)?<label>Variant
          <select required value={line.variant_id||""} onChange={event=>{
            const product=products.find(item=>item.id===line.product_id)!;const variant=product.variants.find(item=>item.id===event.target.value);
            const offer=variant?.offers.find(item=>item.vendor_id===vendorId&&item.is_active);
            updateLine(index,{variant_id:variant?.id||null,description:`${product.name}${variant?` - ${variant.variant_name}`:""}`,rate:Number(vendorId?offer?.buying_price||0:variant?.catalog_price||0)});
          }}><option value="">Select variant</option>{products.find(item=>item.id===line.product_id)!.variants.filter(variant=>variant.is_active&&(!vendorId||variant.offers.some(offer=>offer.vendor_id===vendorId&&offer.is_active))).map(variant=><option key={variant.id} value={variant.id}>{variant.variant_name}</option>)}</select>
        </label>:null}
        <label>HSN / SAC
          <select required disabled={!!line.product_id} value={line.hsn} onChange={(event) => {
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