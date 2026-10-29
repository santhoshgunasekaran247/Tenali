import { FormEvent, useState } from "react";
import { Plus, Save, Trash2, X } from "lucide-react";
import { api } from "../api";
import { toAssetUrl } from "../features/catalog/utils";
import type { HsnMaster, InventoryItemInput, InventoryLookups, InventoryOffer, InventoryOfferInput, InventoryProduct, InventoryProductInput, InventoryVariant } from "../types";

const EMPTY_ITEM: InventoryItemInput = {
  item_name: "", description: "", size: "", colour: "", weight: null, height: null, width: null, length: null,
  attributes: {}, sku: "", pricing_mode: "price", selling_price: null, discount_percent: 0,
  preferred_vendor_id: null, reorder_level: 0, reorder_target: 0, reorder_enabled: false,
  reorder_reminder_date: null, is_active: true,
};
const ITEM_KEYS = Object.keys(EMPTY_ITEM) as Array<keyof InventoryItemInput>;

export function itemPayload(item: InventoryItemInput): InventoryItemInput {
  return Object.fromEntries(ITEM_KEYS.map((key) => [key, item[key] ?? EMPTY_ITEM[key]])) as InventoryItemInput;
}

export function productPayload(product: InventoryProduct): InventoryProductInput {
  return { ...itemPayload(product), name: product.name, brand_id: product.brand_id, category_id: product.category_id,
    minimum_order_quantity: product.minimum_order_quantity,
    hsn_code: product.hsn_code, image_url: product.image_url, image_urls: (product.image_urls || "").split("|").filter(Boolean),
    catalog_visible: product.catalog_visible, best_seller: product.best_seller, sru_special: product.sru_special, home_order: product.home_order };
}

export const inventoryMoney = (value: number | null | undefined) => value == null ? "-" : `INR ${Number(value).toLocaleString("en-IN", {minimumFractionDigits:2,maximumFractionDigits:2})}`;

export function ProductEditor({ product, variant, variantMode = false, lookups, hsn, onSaved, onClose }: {
  product?: InventoryProduct; variant?: InventoryVariant; variantMode?: boolean; lookups: InventoryLookups; hsn: HsnMaster[];
  onSaved: (product: InventoryProduct) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<InventoryProductInput & {variant_name:string}>(() => ({
    ...EMPTY_ITEM, name: "", brand_id: null, category_id: null, hsn_code: null, image_url: null, image_urls: [],
    catalog_visible: false, best_seller: false, sru_special: false, home_order: 999, minimum_order_quantity: 1,
    ...(product && !variantMode ? productPayload(product) : {}),
    ...(variantMode ? { pricing_mode: "inherit" as const, ...(variant ? itemPayload(variant) : {}) } : {}),
    variant_name: variant?.variant_name || "",
  }));
  const [attributes, setAttributes] = useState<Array<[string,string]>>(Object.entries(variant?.attributes || (!variantMode ? product?.attributes : {}) || {}));
  const [gallery, setGallery] = useState((!variantMode ? product?.image_urls : "")?.split("|").join("\n") || "");
  const [saving, setSaving] = useState(false);
  const [imageBusy, setImageBusy] = useState(false);
  const [error, setError] = useState("");
  const offers = (variantMode ? variant?.offers : product?.offers) || [];
  const current = variantMode ? variant : product;
  const selectedOffer = offers.find((offer) => offer.vendor_id === draft.preferred_vendor_id && offer.is_active && offer.vendor_active);
  const mrp = selectedOffer?.mrp ?? (draft.preferred_vendor_id === current?.preferred_vendor_id ? current?.effective_mrp : null);
  const buyingPrice = selectedOffer ? selectedOffer.buying_price : draft.preferred_vendor_id === current?.preferred_vendor_id ? current?.effective_buying_price : null;
  const previewMode = draft.pricing_mode === "inherit" ? product?.pricing_mode : draft.pricing_mode;
  const previewPrice = draft.pricing_mode === "inherit" ? product?.selling_price : draft.selling_price;
  const previewDiscount = draft.pricing_mode === "inherit" ? product?.discount_percent : draft.discount_percent;
  const price = previewMode === "discount" ? (mrp != null ? Math.round(mrp * (1 - Number(previewDiscount) / 100) * 100) / 100 : null) : previewPrice;
  const discount = previewMode === "price" && mrp && price != null ? Math.round((mrp - price) * 10000 / mrp) / 100 : previewDiscount;
  const patch = (values: Partial<typeof draft>) => setDraft((previous) => ({...previous,...values}));
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const entries = attributes.filter(([key,value]) => key.trim() || value.trim());
      if (entries.some(([key]) => !key.trim()) || new Set(entries.map(([key])=>key.trim())).size !== entries.length) throw new Error("Custom attributes need unique, non-empty names.");
      const item = itemPayload({...draft, attributes:Object.fromEntries(entries.map(([key,value])=>[key.trim(),value.trim()]))});
      const result = variantMode && product
        ? await api.inventorySaveVariant(product.id,{...item,variant_name:draft.variant_name.trim() || [draft.size,draft.colour].filter(Boolean).join(" / ")},variant?.id)
        : await api.inventorySaveProduct({...draft,...item,image_urls:[...new Set([draft.image_url,...gallery.split(/\r?\n/)].filter((value):value is string=>!!value?.trim()).map(value=>value.trim()))], variant_name:undefined} as InventoryProductInput,product?.id);
      onSaved(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to save product."); }
    finally { setSaving(false); }
  };
  const imageUpload = async (file?:File) => {
    if (!file) return;
    setImageBusy(true);setError("");
    try {
      if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>1024*1024) throw new Error("Use a PNG, JPEG or WebP image under 1 MB.");
      const data = await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error("Unable to read image."));reader.readAsDataURL(file);});
      patch({image_url:data});
    } catch(failure){setError(failure instanceof Error?failure.message:"Unable to upload image.");}
    finally{setImageBusy(false);}
  };
  return <section className="inventory-editor" aria-label={variantMode ? "Variant editor" : "Product editor"}>
    <div className="inventory-section-head"><h2>{variantMode ? variant ? "Edit Variant" : "Add Variant" : product ? "Edit Product" : "Add Product"}</h2><button className="ops-link-btn" type="button" title="Close editor" aria-label="Close product editor" disabled={saving} onClick={onClose}><X size={18}/></button></div>
    {error?<p role="alert" className="ops-error">{error}</p>:null}
    <form className="ops-form" onSubmit={submit}><fieldset disabled={saving} className="inventory-fields">
      <label>{variantMode?"Variant Name":"Product Name"}<input required={!variantMode} maxLength={200} value={variantMode?draft.variant_name:draft.name} onChange={event=>patch(variantMode?{variant_name:event.target.value}:{name:event.target.value})}/></label>
      <label>Item Name<input maxLength={200} value={draft.item_name||""} onChange={event=>patch({item_name:event.target.value})}/></label>
      <label>SKU<input maxLength={100} value={draft.sku||""} onChange={event=>patch({sku:event.target.value})}/></label>
      {!variantMode?<><label>Brand<select value={draft.brand_id||""} onChange={event=>patch({brand_id:event.target.value||null})}><option value="">No brand</option>{lookups.brands.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Category<select value={draft.category_id||""} onChange={event=>patch({category_id:event.target.value||null})}><option value="">No category</option>{lookups.categories.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>HSN / SAC<select value={draft.hsn_code||""} onChange={event=>patch({hsn_code:event.target.value||null})}><option value="">Not set</option>{draft.hsn_code&&!hsn.some(item=>item.code===draft.hsn_code)?<option value={draft.hsn_code}>{draft.hsn_code} (inactive)</option>:null}{hsn.map(item=><option key={item.id} value={item.code}>{item.code} - {item.description} ({item.gst_rate}%)</option>)}</select></label></>:null}
      <label>Size<input maxLength={100} value={draft.size||""} onChange={event=>patch({size:event.target.value})}/></label>
      <label>Colour<input maxLength={100} value={draft.colour||""} onChange={event=>patch({colour:event.target.value})}/></label>
      {([["weight","Weight (kg)"],["height","Height (cm)"],["width","Width (cm)"],["length","Length (cm)"]] as const).map(([key,label])=><label key={key}>{label}<input type="number" min="0" step="0.001" value={draft[key]??""} onChange={event=>patch({[key]:event.target.value===""?null:Number(event.target.value)})}/></label>)}
      <label className="inventory-wide">Description<textarea rows={3} maxLength={6000} value={draft.description||""} onChange={event=>patch({description:event.target.value})}/></label>
      <label>Preferred Vendor<select value={draft.preferred_vendor_id||""} onChange={event=>patch({preferred_vendor_id:event.target.value||null})}><option value="">{variantMode?"Use parent preference":"Not selected"}</option>{offers.filter(offer=>offer.is_active&&offer.vendor_active).map(offer=><option key={offer.id} value={offer.vendor_id}>{offer.vendor_name}</option>)}</select></label>
      <label>Pricing Rule<select value={draft.pricing_mode} onChange={event=>patch({pricing_mode:event.target.value as InventoryItemInput['pricing_mode'],selling_price:price??null,discount_percent:Number(discount||0)})}>{variantMode?<option value="inherit">Use parent pricing</option>:null}<option value="price">Keep catalog price</option><option value="discount">Keep discount %</option></select></label>
      <label>Catalog Price (INR)<input type="number" min="0" step="0.01" disabled={draft.pricing_mode==="inherit"} value={price??""} onChange={event=>patch({pricing_mode:"price",selling_price:event.target.value===""?null:Number(event.target.value)})}/></label>
      <label>Discount %<input type="number" min="0" max="100" step="0.01" disabled={draft.pricing_mode==="inherit"} value={discount??""} onChange={event=>patch({pricing_mode:"discount",discount_percent:Number(event.target.value)})}/></label>
      <div className="inventory-price-reference"><span>Preferred vendor MRP</span><strong>{inventoryMoney(mrp)}</strong><span>Buying price</span><strong>{inventoryMoney(buyingPrice)}</strong></div>
      <label className="inventory-check"><input type="checkbox" checked={draft.is_active} onChange={event=>patch({is_active:event.target.checked})}/>Active</label>
      {!variantMode?<><label>Primary Image URL / Asset Path<input value={draft.image_url?.startsWith('data:')?"":draft.image_url||""} placeholder={draft.image_url?.startsWith('data:')?"Uploaded image":""} onChange={event=>patch({image_url:event.target.value||null})}/></label>
        <label>Product Image<input type="file" accept="image/png,image/jpeg,image/webp" onChange={event=>{void imageUpload(event.target.files?.[0]);event.target.value="";}}/>{draft.image_url?<img className="inventory-image-preview" src={toAssetUrl(draft.image_url)} alt="Product preview"/>:null}</label>
        <label className="inventory-wide">Gallery Image URLs<textarea rows={2} value={gallery} onChange={event=>setGallery(event.target.value)}/></label>
        <label className="inventory-check"><input type="checkbox" checked={draft.catalog_visible} onChange={event=>patch({catalog_visible:event.target.checked})}/>Visible in customer catalog</label>
        <label>Minimum online order quantity<input required type="number" min={1} max={100} step={1} value={draft.minimum_order_quantity} onChange={event=>patch({minimum_order_quantity:Number(event.target.value)})}/><small>Starts the cart at this quantity. Applies separately to each size / colour. Use 1 for no bulk minimum; online checkout supports up to 100 units per item.</small></label>
        <label className="inventory-check"><input type="checkbox" checked={draft.best_seller} onChange={event=>patch({best_seller:event.target.checked})}/>Best seller</label>
        <label className="inventory-check"><input type="checkbox" checked={draft.sru_special} onChange={event=>patch({sru_special:event.target.checked})}/>SRU special</label>
        <label>Catalog Order<input type="number" min="0" max="99999" value={draft.home_order} onChange={event=>patch({home_order:Number(event.target.value)})}/></label></>:null}
      <label className="inventory-check"><input type="checkbox" checked={draft.reorder_enabled} onChange={event=>patch({reorder_enabled:event.target.checked})}/>Reorder alerts enabled</label>
      <label>Reorder At / Below<input type="number" required min="0" step="0.001" value={draft.reorder_level} onChange={event=>patch({reorder_level:Number(event.target.value)})}/></label>
      <label>Restock Target<input type="number" required min={draft.reorder_enabled?draft.reorder_level:0} step="0.001" value={draft.reorder_target} onChange={event=>patch({reorder_target:Number(event.target.value)})}/></label>
      <label>Reorder Reminder<input type="date" value={draft.reorder_reminder_date||""} onChange={event=>patch({reorder_reminder_date:event.target.value||null})}/></label>
      <div className="inventory-wide inventory-attributes"><h3>Additional Attributes</h3>{attributes.map(([key,value],index)=><div className="inventory-attribute-row" key={index}>
        <input aria-label={`Attribute ${index+1} name`} value={key} maxLength={100} onChange={event=>setAttributes(previous=>previous.map((entry,position)=>position===index?[event.target.value,entry[1]]:entry))}/>
        <input aria-label={`Attribute ${index+1} value`} value={value} maxLength={500} onChange={event=>setAttributes(previous=>previous.map((entry,position)=>position===index?[entry[0],event.target.value]:entry))}/>
        <button className="ops-link-btn" type="button" title="Remove attribute" aria-label={`Remove attribute ${index+1}`} onClick={()=>setAttributes(previous=>previous.filter((_,position)=>position!==index))}><Trash2 size={16}/></button>
      </div>)}<button className="ops-link-btn" type="button" disabled={attributes.length>=40} onClick={()=>setAttributes(previous=>[...previous,["",""]])}><Plus size={16}/> Add Attribute</button></div>
    </fieldset><div className="inventory-actions"><button className="btn" type="submit" disabled={saving||imageBusy}><Save size={16}/>{saving?"Saving...":variantMode?"Save Variant":"Save Product"}</button></div></form>
  </section>;
}

export function VendorOfferEditor({ product, offer, variantId, vendors, onSaved, onClose }: {
  product:InventoryProduct; offer?:InventoryOffer; variantId:string|null; vendors:InventoryLookups['vendors']; onSaved:(product:InventoryProduct)=>void;onClose:()=>void;
}) {
  const [draft,setDraft]=useState<InventoryOfferInput>({vendor_id:offer?.vendor_id||"",variant_id:offer?.variant_id||variantId,mrp:offer?.mrp??null,buying_price:offer?.buying_price??null,
    available_quantity:offer?.available_quantity??0,availability:offer?.availability||"UNKNOWN",lead_time_days:offer?.lead_time_days||0,sku:offer?.sku||null,
    vendor_reference:offer?.vendor_reference||null,vendor_product_url:offer?.vendor_product_url||null,is_active:offer?.is_active??true});
  const [saving,setSaving]=useState(false);const[error,setError]=useState("");
  const patch=(values:Partial<InventoryOfferInput>)=>setDraft(previous=>({...previous,...values}));
  const submit=async(event:FormEvent)=>{event.preventDefault();setSaving(true);setError("");try{onSaved(await api.inventorySaveOffer(product.id,draft,offer?.id));}catch(failure){setError(failure instanceof Error?failure.message:"Unable to save vendor offer.");}finally{setSaving(false);}};
  return <section className="inventory-editor" aria-label="Vendor offer editor"><div className="inventory-section-head"><h3>{offer?"Edit Vendor Offer":"Map Vendor to Product"}</h3><button className="ops-link-btn" type="button" aria-label="Close vendor offer" title="Close vendor offer" onClick={onClose}><X size={18}/></button></div>
    {error?<p className="ops-error" role="alert">{error}</p>:null}<form className="ops-form" onSubmit={submit}><fieldset disabled={saving} className="inventory-fields">
      <label>Vendor<select required disabled={!!offer} value={draft.vendor_id} onChange={event=>patch({vendor_id:event.target.value})}><option value="">Select vendor</option>{vendors.map(vendor=><option value={vendor.id} key={vendor.id}>{vendor.legal_name}</option>)}</select></label>
      <label>Product / Variant<select disabled={!!offer} value={draft.variant_id||""} onChange={event=>patch({variant_id:event.target.value||null})}><option value="">{product.name} - Base product</option>{product.variants.map(variant=><option value={variant.id} key={variant.id}>{variant.variant_name}</option>)}</select></label>
      <label>Vendor MRP (INR)<input type="number" min="0" step="0.01" value={draft.mrp??""} onChange={event=>patch({mrp:event.target.value===""?null:Number(event.target.value)})}/></label>
      <label>Buying Price (INR)<input type="number" min="0" step="0.01" value={draft.buying_price??""} onChange={event=>patch({buying_price:event.target.value===""?null:Number(event.target.value)})}/></label>
      <label>Vendor Available Quantity<input required type="number" min="0" step="0.001" value={draft.available_quantity} onChange={event=>patch({available_quantity:Number(event.target.value)})}/></label>
      <label>Availability<select value={draft.availability} onChange={event=>patch({availability:event.target.value as InventoryOfferInput['availability']})}>{['UNKNOWN','AVAILABLE','OUT_OF_STOCK','ON_ORDER'].map(value=><option key={value} value={value}>{value.split('_').join(' ')}</option>)}</select></label>
      <label>Lead Time (days)<input required type="number" min="0" max="3650" value={draft.lead_time_days} onChange={event=>patch({lead_time_days:Number(event.target.value)})}/></label>
      <label>Vendor SKU<input maxLength={100} value={draft.sku||""} onChange={event=>patch({sku:event.target.value||null})}/></label>
      <label>Vendor Reference<input maxLength={300} value={draft.vendor_reference||""} onChange={event=>patch({vendor_reference:event.target.value||null})}/></label>
      <label>Vendor Product URL<input maxLength={1000} value={draft.vendor_product_url||""} onChange={event=>patch({vendor_product_url:event.target.value||null})}/></label>
      <label className="inventory-check"><input type="checkbox" checked={draft.is_active} onChange={event=>patch({is_active:event.target.checked})}/>Offer active</label>
    </fieldset><button className="btn" type="submit" disabled={saving}><Save size={16}/>{saving?"Saving...":"Save Vendor Offer"}</button></form></section>;
}