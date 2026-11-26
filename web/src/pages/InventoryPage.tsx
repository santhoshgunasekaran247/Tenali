import { PaginatedTableBody } from "../components/PaginatedTableBody";
import { CursorPagination } from "../components/CursorPagination";
import { useDraftState } from "../features/drafts";
import { FloatingAlert } from "../components/Notifications";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRightLeft, Bell, ChevronRight, PackagePlus, Pencil, Plus, RefreshCw, Save, Star, Tags, Trash2, Users } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { PortalHomeLink } from "../components/PortalHomeLink";
import { postingKey } from "../features/postingKey";
import { ProductEditor, VendorOfferEditor, inventoryMoney, itemPayload, productPayload } from "../components/InventoryForms";
import { toAssetUrl } from "../features/catalog/utils";
import type { HsnMaster, InventoryAlert, InventoryLookups, InventoryMissingSource, InventoryMovement, InventoryOffer, InventoryProduct, InventoryReconciliation, InventoryVariant } from "../types";
import { StoreSelect, useStores } from "../features/stores";
import { StockTransferDialog } from "../components/StockTransferDialog";
import { PartySelect } from "../components/PartySelect";
import { StockCheckPanel } from "../components/StockCheckPanel";
import { inventoryStockRows } from "../features/inventoryStockRows";
import { useAuth } from "../features/auth";
import { DeleteTransactionDialog } from "../components/DeleteTransactionDialog";

function inventoryViewFrom(search: string): 'alerts'|'check'|null {
  const view=new URLSearchParams(search).get('view');
  return view==='alerts'||view==='check'?view:null;
}

export function InventoryPage() {
  const [products,setProducts]=useState<InventoryProduct[]>([]);
  const [allProducts,setAllProducts]=useState<InventoryProduct[]|null>(null);
  const [selectedProduct,setSelectedProduct]=useState<InventoryProduct|null>(null);
  const [productSize,setProductSize]=useState(25);const[productCursors,setProductCursors]=useState<Array<string|null>>([null]);
  const [productPage,setProductPage]=useState(0);const[productNext,setProductNext]=useState<string|null>(null);
  const [productLoading,setProductLoading]=useState(false);const[productError,setProductError]=useState("");
  const [revision,setRevision]=useState(0);const[allLoading,setAllLoading]=useState(false);
  const [selectionLoading,setSelectionLoading]=useState(false);const[allSelected,setAllSelected]=useState(false);
  const selectionVersion=useRef(0);
  const openVersion=useRef(0);
  const [lookups,setLookups]=useState<InventoryLookups>({brands:[],categories:[],tags:[],vendors:[]});
  const [hsn,setHsn]=useState<HsnMaster[]>([]);const[alerts,setAlerts]=useState<InventoryAlert[]>([]);
  const [gstRegistered,setGstRegistered]=useState(true);
  const [reconciliation,setReconciliation]=useState<InventoryReconciliation[]>([]);
  const [missingSources,setMissingSources]=useState<InventoryMissingSource[]>([]);
  const [search,setSearch]=useState("");const[vendorFilter,setVendorFilter]=useState("");const[includeInactive,setIncludeInactive]=useState(false);
  const [selectedIds,setSelectedIds]=useState<string[]>([]);const[bulkVendor,setBulkVendor]=useState("");
  const [selectedId,setSelectedId]=useDraftState<string|null>("InventoryPage.selectedId", null);const[tab,setTab]=useDraftState<'details'|'variants'|'vendors'|'stock'>("InventoryPage.tab", 'details');
  const routeLocation=useLocation();
  const [view,setView]=useState<'products'|'alerts'|'check'>(()=>inventoryViewFrom(routeLocation.search)??'products');const[editor,setEditor]=useDraftState<'product'|'variant'|null>("InventoryPage.editor", null);
  useEffect(()=>{const requested=inventoryViewFrom(routeLocation.search);if(requested)setView(requested);},[routeLocation.search]);
  const [newProduct,setNewProduct]=useDraftState("InventoryPage.newProduct", false);const[variantTarget,setVariantTarget]=useDraftState<InventoryVariant|undefined>("InventoryPage.variantTarget", undefined);
  const [offerEditor,setOfferEditor]=useDraftState<{offer?:InventoryOffer;variantId:string|null}|null>("InventoryPage.offerEditor", null);
  const [loading,setLoading]=useState(true);const[busy,setBusy]=useState(false);const[error,setError]=useState("");const[message,setMessage]=useState("");
  const [stock,setStock]=useDraftState("InventoryPage.stock", {variant_id:"",direction:"IN" as "IN"|"OUT",quantity:"",notes:""});const[movements,setMovements]=useState<InventoryMovement[]>([]);
  const [movementSize,setMovementSize]=useState(25);const[movementCursors,setMovementCursors]=useState<Array<string|null>>([null]);
  const [movementPage,setMovementPage]=useState(0);const[movementNext,setMovementNext]=useState<string|null>(null);
  const [movementLoading,setMovementLoading]=useState(false);const[movementError,setMovementError]=useState("");
  const [reminders,setReminders]=useDraftState<Record<string,string>>("InventoryPage.reminders", {});
  const [lookupKind,setLookupKind]=useDraftState<'brands'|'categories'>("InventoryPage.lookupKind", 'brands');const[lookupName,setLookupName]=useDraftState("InventoryPage.lookupName", "");const[showLookup,setShowLookup]=useDraftState("InventoryPage.showLookup", false);
  const detailDialog=useRef<HTMLDialogElement>(null);
  const createDialog=useRef<HTMLDialogElement>(null);
  const selected=selectedProduct?.id===selectedId?selectedProduct:undefined;
  const [stockKey,setStockKey]=useDraftState("InventoryPage.stockKey", postingKey);
  const storeContext=useStores();
  const [transferOpen,setTransferOpen]=useState(false);
  const [movementDelete,setMovementDelete]=useState<{kind:'stock_adjustment'|'stock_transfer';id:string;title:string}|null>(null);
  const [transferProductId,setTransferProductId]=useState<string|null>(null);
  const {user}=useAuth();
  const canDelete=!!user&&['owner','admin'].includes(user.role);
  const [deleteConfirm,setDeleteConfirm]=useState(false);
  const [deleteName,setDeleteName]=useState("");
  const [merge,setMerge]=useState({target:"",variant:""});
  const load=async()=>{setLoading(true);setError("");try{const[options,codes,notifications,stockCheck,missing,company]=await Promise.all([api.inventoryLookups(),api.hsnMasters(),api.inventoryAlerts(),api.inventoryReconciliation(),api.inventoryMissingSources(),api.company()]);setLookups(options);setHsn(codes.items);setGstRegistered(company.gst_registered !== false);setAlerts(notifications.items);setReconciliation(stockCheck.items);setMissingSources(missing.items);setAllProducts(null);setRevision(previous=>previous+1);return true;}catch(failure){setError(failure instanceof Error?failure.message:"Unable to load inventory.");return false;}finally{setLoading(false);}};
  useEffect(()=>{void load();},[]);
  useEffect(()=>{let active=true;setProductLoading(true);setProductError("");setProducts([]);setProductNext(null);
    api.inventoryProductPage(productSize,productCursors[productPage],search,vendorFilter,includeInactive).then(result=>{if(active){setProducts(result.items);setProductNext(result.next_cursor);}}).catch(failure=>{if(active)setProductError(failure instanceof Error?failure.message:"Unable to load products.");}).finally(()=>{if(active)setProductLoading(false);});
    return()=>{active=false;};},[productSize,productCursors,productPage,search,vendorFilter,includeInactive,revision]);
  useEffect(()=>{let active=true;if(selectedId)api.inventoryProduct(selectedId).then(product=>{if(active)setSelectedProduct(product);}).catch(failure=>{if(active)setError(failure instanceof Error?failure.message:"Unable to load product.");});return()=>{active=false;};},[selectedId,revision]);
  useEffect(()=>{let active=true;if((transferOpen||selected?.is_draft)&&!allProducts){setAllLoading(true);api.inventoryProducts().then(result=>{if(active)setAllProducts(result.items);}).catch(failure=>{if(active)setError(failure instanceof Error?failure.message:"Unable to load products for this operation.");}).finally(()=>{if(active)setAllLoading(false);});}return()=>{active=false;};},[transferOpen,selected?.is_draft,allProducts,revision]);
  useEffect(()=>()=>{selectionVersion.current++;openVersion.current++;},[]);
  const resetProductFilter=()=>{selectionVersion.current++;setSelectionLoading(false);setAllSelected(false);setProductCursors([null]);setProductPage(0);};
  const selectMatching=async(checked:boolean)=>{const version=++selectionVersion.current;setSelectionLoading(true);setProductError("");
    try{let cursor:string|null=null;const ids:string[]=[];do{const result=await api.inventoryProductIds(cursor,search,vendorFilter,includeInactive);if(version!==selectionVersion.current)return;ids.push(...result.items);cursor=result.next_cursor;}while(cursor);
      setSelectedIds(previous=>checked?[...new Set([...previous,...ids])]:previous.filter(id=>!ids.includes(id)));setAllSelected(checked);
    }catch(failure){if(version===selectionVersion.current)setProductError(failure instanceof Error?failure.message:"Unable to select matching products.");}
    finally{if(version===selectionVersion.current)setSelectionLoading(false);}};
  useEffect(()=>{if(selected&&detailDialog.current&&!detailDialog.current.open)detailDialog.current.showModal();},[selected]);
  useEffect(()=>{if(newProduct&&createDialog.current&&!createDialog.current.open)createDialog.current.showModal();},[newProduct]);
  useEffect(()=>{if(!selected&&!newProduct)return;const previous=document.body.style.overflow;document.body.style.overflow='hidden';return()=>{document.body.style.overflow=previous;};},[!!selected,newProduct]);
  useEffect(()=>{if(editor||offerEditor)(detailDialog.current||createDialog.current)?.querySelector('.inventory-editor')?.scrollIntoView({behavior:'smooth',block:'start'});},[editor,offerEditor]);
  const closeProduct=()=>{openVersion.current++;detailDialog.current?.close();setSelectedId(null);setEditor(null);setOfferEditor(null);setDeleteConfirm(false);setDeleteName("");};
  const closeCreate=()=>{createDialog.current?.close();setNewProduct(false);setEditor(null);};
  const perform=async(action:()=>Promise<unknown>,success:string)=>{setBusy(true);setError("");setMessage("");try{await action();if(await load())setMessage(success);}catch(failure){setError(failure instanceof Error?failure.message:"Inventory operation failed.");}finally{setBusy(false);}};
  const open=(product:InventoryProduct,target:'details'|'variants'|'vendors'|'stock'='details')=>{openVersion.current++;setSelectedProduct(product);setSelectedId(product.id);setTab(target);setEditor(null);setNewProduct(false);setOfferEditor(null);setVariantTarget(undefined);setDeleteConfirm(false);setDeleteName("");setStock({variant_id:'',direction:'IN',quantity:'',notes:''});setMovements([]);setMovementCursors([null]);setMovementPage(0);setMovementNext(null);setMovementError("");setError('');setMessage('');};
  const openById=async(id:string)=>{const version=++openVersion.current;try{const product=await api.inventoryProduct(id);if(version===openVersion.current){open(product,'stock');setView('products');}}catch(failure){if(version===openVersion.current)setError(failure instanceof Error?failure.message:"Unable to load product.");}};
  const saved=(product:InventoryProduct)=>{setSelectedProduct(product);setSelectedId(product.id);setEditor(null);setNewProduct(false);setOfferEditor(null);setMessage("");void load().then(loaded=>{if(loaded)setMessage("Product inventory saved.");});};
  const prefer=async(offer:InventoryOffer)=>{if(!selected)return;await perform(async()=>{if(offer.variant_id){const variant=selected.variants.find(item=>item.id===offer.variant_id)!;await api.inventorySaveVariant(selected.id,{...itemPayload(variant),variant_name:variant.variant_name,preferred_vendor_id:offer.vendor_id},variant.id);}else await api.inventorySaveProduct({...productPayload(selected),preferred_vendor_id:offer.vendor_id},selected.id);},"Preferred vendor updated.");};
  useEffect(()=>{let active=true;if(selectedId&&tab==='stock'){setMovementLoading(true);setMovementError("");setMovements([]);setMovementNext(null);api.inventoryMovements(selectedId,movementSize,movementCursors[movementPage]).then(result=>{if(active){setMovements(result.items);setMovementNext(result.next_cursor||null);}}).catch(failure=>{if(active)setMovementError(failure instanceof Error?failure.message:"Unable to load stock history.");}).finally(()=>{if(active)setMovementLoading(false);});}return()=>{active=false;};},[selectedId,tab,products,movementSize,movementPage,movementCursors]);
  const adjust=async(event:FormEvent)=>{event.preventDefault();if(!selected)return;await perform(async()=>{await api.inventoryAdjustStock(selected.id,{store_id:storeContext.selectedId||null,variant_id:stock.variant_id||null,direction:stock.direction,quantity:Number(stock.quantity),notes:stock.notes,idempotency_key:stockKey});setStockKey(postingKey());setStock(previous=>({...previous,quantity:"",notes:""}));},"Owned stock updated.");};
  const allOffers=selected?[...selected.offers,...selected.variants.flatMap(variant=>variant.offers)]:[];
  const stockRows=selected?inventoryStockRows(selected):[];
  return <main className="ops-page inventory-page">
    <header className="inventory-heading"><PortalHomeLink/><div className="inventory-section-head"><h1>Product Inventory</h1><div className="inventory-actions">
      <button className="btn" type="button" disabled={busy||loading||!!error} onClick={()=>{openVersion.current++;setView('products');setNewProduct(true);setEditor('product');setSelectedId(null);}}><Plus size={16}/>Add Product</button>
      {canDelete?<Link className="btn light" to="/portal/bulk-upload" state={{selectedProducts:selectedIds}}>Bulk Excel</Link>:null}
      <button className="ops-link-btn" type="button" title="Refresh inventory" aria-label="Refresh inventory" disabled={loading||busy} onClick={()=>void load()}><RefreshCw size={18}/></button>
    </div></div><div className="inventory-tabs" role="tablist" aria-label="Inventory views">
      <button role="tab" type="button" aria-selected={view==='products'} onClick={()=>setView('products')}>Products</button>
      <button role="tab" type="button" aria-selected={view==='alerts'} onClick={()=>setView('alerts')}><Bell size={16}/>Reorder Alerts ({alerts.length})</button>
      <button role="tab" type="button" aria-selected={view==='check'} onClick={()=>setView('check')}>Stock check ({reconciliation.filter(row=>Number(row.difference)!==0||Number(row.missing_document_references)>0).length})</button>
    </div></header>
    {!selected&&!newProduct&&error?<FloatingAlert>{error}</FloatingAlert>:null}{!selected&&!newProduct&&message?<FloatingAlert tone="success">{message}</FloatingAlert>:null}{loading?<p className="inventory-feedback" role="status">Loading inventory...</p>:null}
    {view==='check'&&!selected&&!newProduct&&!loading&&!error?<StockCheckPanel rows={reconciliation} missingSources={missingSources} busy={busy}
      onOpen={id=>void openById(id)}
      onAttribute={(id,reference,notes)=>perform(()=>api.inventoryAttributeExternalSource(id,reference,notes),"Document reference saved. Stock quantities were not changed.")}/>:null}
    {transferOpen&&allProducts?<StockTransferDialog products={allProducts} stores={storeContext.stockStores} productId={transferProductId||undefined} onClose={()=>{setTransferOpen(false);setTransferProductId(null);}} onDone={async()=>{setTransferOpen(false);setTransferProductId(null);setMessage("");if(await load())setMessage("Stock transferred.");}}/>:null}
    {transferOpen&&!allProducts?<p role="status">{allLoading?"Loading products for transfer...":"Unable to load products for transfer."} <button type="button" onClick={()=>setTransferOpen(false)}>Cancel</button></p>:null}
    {movementDelete?<DeleteTransactionDialog kind={movementDelete.kind} id={movementDelete.id} title={movementDelete.title} onClose={()=>setMovementDelete(null)} onDone={async result=>{setMovementDelete(null);setMessage("");if(await load())setMessage(`Deleted ${result.label}.`);}}/>:null}
    {newProduct&&editor==='product'?<dialog ref={createDialog} className="inventory-dialog inventory-create-dialog" aria-label="Add inventory product" onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();closeCreate();}}} onCancel={event=>{event.preventDefault();closeCreate();}}><ProductEditor lookups={lookups} hsn={hsn} gstRegistered={gstRegistered} onSaved={saved} onClose={closeCreate}/></dialog>:null}
    <section className="inventory-body" hidden={view!=='products'&&!selected}>
      <div className="inventory-toolbar inventory-filter-toolbar"><label>Find a product<input type="search" maxLength={300} value={search} onChange={event=>{resetProductFilter();setSearch(event.target.value);}} placeholder="Product, SKU, brand, category or variant"/></label>
        <label>Vendor<select value={vendorFilter} onChange={event=>{resetProductFilter();setVendorFilter(event.target.value);}}><option value="">All vendors</option>{lookups.vendors.map(vendor=><option key={vendor.id} value={vendor.id}>{vendor.legal_name}</option>)}</select></label>
        <label className="inventory-check"><input type="checkbox" checked={includeInactive} onChange={event=>{resetProductFilter();setIncludeInactive(event.target.checked);}}/>Include inactive</label>
        <div className="inventory-toolbar-actions">
          <button className="inventory-secondary-action" type="button" aria-expanded={showLookup} onClick={()=>setShowLookup(previous=>!previous)}><Tags size={16} aria-hidden="true"/>Brands & Categories</button>
          <Link className="inventory-secondary-action" to="/portal/parties"><Users size={16} aria-hidden="true"/>Vendor Master</Link>
        </div>
        <div className="inventory-results-bar"><p role="status">{productLoading?"Loading products...":`${products.length} products on this page`}{search.trim()?` matching "${search.trim()}"`:''}</p>
          <button className="ops-link-btn" type="button" disabled={!search&&!vendorFilter&&!includeInactive} onClick={()=>{resetProductFilter();setSearch("");setVendorFilter("");setIncludeInactive(false);setSelectedIds([]);}}>Clear filters</button>
          <button className="inventory-secondary-action" type="button" onClick={()=>setTransferOpen(true)} disabled={storeContext.stockStores.length<2} title={storeContext.stockStores.length<2?"Add a second stock-holding store to transfer stock":"Move owned stock between stores"}>Transfer stock</button></div>
      </div>
      {showLookup?<form className="inventory-toolbar" onSubmit={event=>{event.preventDefault();void perform(async()=>{await api.inventoryCreateLookup(lookupKind,lookupName);setLookupName('');},"Master entry added.");}}>
        <label>Master Type<select value={lookupKind} onChange={event=>setLookupKind(event.target.value as 'brands'|'categories')}><option value="brands">Brand</option><option value="categories">Category</option></select></label>
        <label>Name<input required maxLength={150} value={lookupName} onChange={event=>setLookupName(event.target.value)}/></label><button className="btn" disabled={busy}><Plus size={16}/>Add</button>
      </form>:null}
      {selectedIds.length?<div className="inventory-bulk"><strong>{selectedIds.length} selected</strong><PartySelect parties={lookups.vendors} value={bulkVendor} onChange={setBulkVendor} label="Vendor for selected products" placeholder="Select vendor to map" />
        <button className="btn" type="button" disabled={!selectedIds.length||selectedIds.length>200||!bulkVendor||busy||selectionLoading} onClick={()=>void perform(async()=>{await api.inventoryBulkMap(bulkVendor,selectedIds);resetProductFilter();setVendorFilter(bulkVendor);setSelectedIds([]);},"Vendor mapped to selected products.")}>Map Selected Products</button>
        {selectedIds.length>200?<p role="alert">Select at most 200 products for one mapping.</p>:null}
      </div>:null}
      <p className="social-caption">Owned stock totals include all your accessible stores and all variants, not just the selected store. They include stock reserved for online orders; see each product’s Stock tab for the store breakdown.</p>
      <p className="social-caption">The header checkbox selects all matching products across pages.</p>
      {productError?<FloatingAlert>{productError}</FloatingAlert>:null}{selectionLoading?<p role="status">Selecting matching products...</p>:null}
      <div className="ops-table-wrap"><table className="ops-table inventory-register"><thead><tr><th><input type="checkbox" aria-label="Select all matching products across pages" checked={allSelected} disabled={selectionLoading||productLoading||!products.length} onChange={event=>void selectMatching(event.target.checked)}/></th><th>Product</th><th>Brand / Category</th><th>Owned Stock</th><th>Vendors</th><th>Preferred MRP</th><th>Buying Price</th><th>Catalog Price</th><th>Catalog</th><th></th></tr></thead>
        <tbody>{products.length?products.map(product=><tr key={product.id} className={selectedId===product.id?'inventory-selected':''}>
          <td><input type="checkbox" aria-label={`Select ${product.name}`} disabled={selectionLoading} checked={selectedIds.includes(product.id)} onChange={event=>{setAllSelected(false);setSelectedIds(previous=>event.target.checked?[...previous,product.id]:previous.filter(id=>id!==product.id));}}/></td>
          <td><button className="inventory-product-link" type="button" onClick={()=>open(product)}>{product.image_url?<img src={toAssetUrl(product.image_url)} alt=""/>:null}<span><strong>{product.name}</strong>{product.is_draft?<em className="inventory-draft-badge">Draft</em>:null}<small>{product.portal_product_id}{product.variants.length?` · ${product.variants.length} variants`:''}</small></span></button></td>
          <td>{product.brand_name||'-'}<small>{product.category_name||'-'}</small></td><td><button className="ops-link-btn" type="button" aria-label={`View stock by store for ${product.name}`} onClick={()=>open(product,'stock')}>{Number(product.stock_qty)} · By store</button></td><td><button className="ops-link-btn" type="button" onClick={()=>open(product,'vendors')}>{new Set([...product.offers,...product.variants.flatMap(variant=>variant.offers)].filter(offer=>offer.is_active&&offer.vendor_active).map(offer=>offer.vendor_id)).size} vendors</button></td>
          <td>{inventoryMoney(product.effective_mrp)}</td><td>{inventoryMoney(product.effective_buying_price)}</td><td>{inventoryMoney(product.catalog_price)}</td><td>{product.is_draft?'Draft':product.is_active&&product.catalog_visible?'Visible':'Hidden'}</td>
          <td><button className="ops-link-btn" type="button" aria-label={`Open ${product.name}`} title="Open product" onClick={()=>open(product)}><ChevronRight size={18}/></button></td>
        </tr>):<tr><td colSpan={10}>{productLoading?"Loading products...":productError?"Unable to load products.":"No products found."}</td></tr>}</tbody></table></div>
      <CursorPagination size={productSize} page={productPage} hasNext={!!productNext} busy={productLoading} onSize={size=>{setProductSize(size);setProductCursors([null]);setProductPage(0);}} onPrevious={()=>setProductPage(page=>page-1)} onNext={()=>{if(productNext){setProductCursors(previous=>[...previous.slice(0,productPage+1),productNext]);setProductPage(page=>page+1);}}}/>
      {selected?<dialog ref={detailDialog} className="inventory-dialog" aria-labelledby="inventory-product-title" onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();closeProduct();}}} onCancel={event=>{event.preventDefault();closeProduct();}}><section className="inventory-detail" aria-label={`Inventory for ${selected.name}`}>
        <div className="inventory-detail-navigation">
        <div className="inventory-section-head"><div><small>{selected.portal_product_id}</small><h2 id="inventory-product-title">{selected.name}</h2></div><button className="inventory-secondary-action" type="button" title="Back to products" aria-label="Back to products" onClick={closeProduct}><ArrowLeft size={18} aria-hidden="true"/>Back to Products</button></div>
        <div className="inventory-tabs" role="tablist" aria-label="Product detail views">{(['details','variants','vendors','stock'] as const).map(value=><button type="button" role="tab" aria-selected={tab===value} key={value} onClick={()=>{setTab(value);setEditor(null);setOfferEditor(null);}}>{value==='vendors'?'Vendor Offers':value==='stock'?'Owned Stock':value==='details'?'Product Details':'Variants'}</button>)}</div>
        </div>
        {selected.pricing_error?<p className="ops-error">{selected.pricing_error}</p>:null}
        {selected.is_draft?<div className="inventory-draft-note" role="note"><p><strong>Draft product.</strong> Added from a purchase bill. Review the details, then confirm it to use it in sales and the storefront, or merge it into an existing product.</p>
          <button className="btn" type="button" disabled={busy||(gstRegistered&&!selected.hsn_code)} onClick={()=>void perform(()=>api.inventoryConfirmProduct(selected.id),"Product confirmed.")}>Confirm product</button>
          {canDelete&&allProducts?<DraftMerge draft={selected} products={allProducts} value={merge} busy={busy} onChange={setMerge} onMerge={()=>void perform(async()=>{const merged=await api.inventoryMergeProduct(selected.id,{target_product_id:merge.target,target_variant_id:merge.variant||null});setMerge({target:"",variant:""});setSelectedProduct(merged);setSelectedId(merged.id);},"Draft merged. Its stock, purchase lines and vendor offers now belong to the selected product.")}/>
            :canDelete?<p role="status">{allLoading?"Loading merge targets...":"Unable to load merge targets."}</p>
            :<p className="ops-copy-note">An owner or administrator can merge this draft into an existing product.</p>}</div>:null}
        {error?<FloatingAlert>{error}</FloatingAlert>:null}{message?<FloatingAlert tone="success">{message}</FloatingAlert>:null}
        {tab==='details'?editor==='product'?<ProductEditor key={selected.id} product={selected} lookups={lookups} hsn={hsn} gstRegistered={gstRegistered} onSaved={saved} onClose={()=>setEditor(null)}/>:<>
          <div className="inventory-summary"><div><span>Catalog Price</span><strong>{inventoryMoney(selected.catalog_price)}</strong></div><div><span>Discount</span><strong>{selected.effective_discount==null?'-':`${Number(selected.effective_discount)}%`}</strong></div><div><span>Preferred Vendor</span><strong>{selected.preferred_vendor_name||'Not selected'}</strong></div><div><span>Owned Stock</span><strong>{Number(selected.stock_qty)}</strong></div></div>
          <p>{selected.description||'No description.'}</p><dl className="inventory-specs">{[['Item name',selected.item_name],['Size',selected.size],['Colour',selected.colour],['Weight (kg)',selected.weight],['Height (cm)',selected.height],['Width (cm)',selected.width],['Length (cm)',selected.length],...Object.entries(selected.attributes)].filter(([,value])=>value!=null&&value!=='').map(([label,value])=><div key={String(label)}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          <dl className="inventory-specs"><div><dt>Reorder Alerts</dt><dd>{selected.reorder_enabled?`At or below ${Number(selected.reorder_level)} · restock to ${Number(selected.reorder_target)}`:Number(selected.reorder_level)>0?`Off (level ${Number(selected.reorder_level)} set; enable in Edit Product)`:'Off'}</dd></div><div><dt>Preferred Vendor Availability</dt><dd>{selected.vendor_availability.split('_').join(' ')}</dd></div><div><dt>Vendor Available Quantity</dt><dd>{selected.vendor_available_quantity??'-'}</dd></div><div><dt>Vendor Lead Time (days)</dt><dd>{selected.vendor_lead_time_days??'-'}</dd></div></dl>
          <div className="inventory-actions"><button className="btn" type="button" onClick={()=>setEditor('product')}><Pencil size={16}/>Edit Product</button>{selected.catalog_visible&&selected.is_active?<Link className="ops-inline-link" to={`/products/${selected.id}`}>Customer View</Link>:null}
            {canDelete?<button className="inventory-secondary-action" type="button" disabled={busy} onClick={()=>{setDeleteConfirm(true);setDeleteName("");}}><Trash2 size={16}/>Delete product</button>:null}</div>
          {deleteConfirm?<fieldset className="inventory-delete-confirm" disabled={busy}><legend>Delete {selected.name}?</legend>
            <p>This permanently removes an unused product, its variants and vendor mappings. Products with stock, enquiries or business history cannot be deleted. Make those products inactive using Edit Product instead.</p>
            <label>Type {selected.portal_product_id} to confirm<input value={deleteName} autoComplete="off" onChange={event=>setDeleteName(event.target.value)}/></label>
            <div className="inventory-actions"><button className="btn" type="button" disabled={busy||deleteName!==selected.portal_product_id} onClick={()=>void perform(async()=>{await api.inventoryDeleteProduct(selected.id);closeProduct();},"Product deleted.")}>Permanently delete</button>
            <button className="ops-link-btn" type="button" onClick={()=>setDeleteConfirm(false)}>Cancel</button></div></fieldset>:null}
        </>:null}
        {tab==='variants'?<>
          <div className="inventory-section-head"><h3>Child Variants</h3><button className="btn" type="button" onClick={()=>{setVariantTarget(undefined);setEditor('variant');}}><Plus size={16}/>Add Variant</button></div>
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Variant</th><th>Size</th><th>Colour</th><th>Owned Stock</th><th>MRP</th><th>Catalog Price</th><th>Status</th><th></th></tr></thead><PaginatedTableBody>{selected.variants.length?selected.variants.map(variant=><tr key={variant.id}><td>{variant.variant_name}</td><td>{variant.size||'-'}</td><td>{variant.colour||'-'}</td><td>{Number(variant.stock_qty)}</td><td>{inventoryMoney(variant.effective_mrp)}</td><td>{inventoryMoney(variant.catalog_price)}</td><td>{variant.is_active?'Active':'Inactive'}</td><td><button className="ops-link-btn" type="button" title={`Edit ${variant.variant_name}`} aria-label={`Edit ${variant.variant_name}`} onClick={()=>{setVariantTarget(variant);setEditor('variant');}}><Pencil size={16}/></button></td></tr>):<tr><td colSpan={8}>No variants.</td></tr>}</PaginatedTableBody></table></div>
          {editor==='variant'?<ProductEditor key={variantTarget?.id||'new-variant'} product={selected} variant={variantTarget} variantMode lookups={lookups} hsn={hsn} gstRegistered={gstRegistered} onSaved={saved} onClose={()=>setEditor(null)}/>:null}
        </>:null}
        {tab==='vendors'?<>
          <div className="inventory-section-head"><h3>Vendors Mapped to This Product</h3><button className="btn" type="button" onClick={()=>setOfferEditor({variantId:null})}><Plus size={16}/>Map Vendor</button></div>
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Vendor / Contact</th><th>Product / Variant</th><th>MRP</th><th>Buying Price</th><th>Vendor Qty</th><th>Availability</th><th>Lead Days</th><th>Preferred</th><th></th></tr></thead><PaginatedTableBody>{allOffers.length?allOffers.map(offer=>{const target=offer.variant_id?selected.variants.find(variant=>variant.id===offer.variant_id):selected;return <tr key={offer.id}><td><strong>{offer.vendor_name}</strong><small>{offer.contact_person||''}</small>{offer.phone?<a href={`tel:${offer.phone}`}>{offer.phone}</a>:null}{offer.email?<small><a href={`mailto:${offer.email}`}>{offer.email}</a></small>:null}<small>{offer.address}</small></td><td>{offer.variant_id?selected.variants.find(variant=>variant.id===offer.variant_id)?.variant_name:'Base product'}</td><td>{inventoryMoney(offer.mrp)}</td><td>{inventoryMoney(offer.buying_price)}</td><td>{Number(offer.available_quantity)}</td><td>{offer.is_active&&offer.vendor_active?offer.availability.split('_').join(' '):'Inactive'}</td><td>{offer.lead_time_days}</td><td><button className="ops-link-btn" type="button" disabled={busy||!offer.is_active||!offer.vendor_active} title="Set preferred vendor" aria-label={`Prefer ${offer.vendor_name} for ${offer.variant_id||selected.id}`} onClick={()=>void prefer(offer)}><Star size={18} fill={target?.preferred_vendor_id===offer.vendor_id?'currentColor':'none'}/></button></td><td><button className="ops-link-btn" type="button" title="Edit vendor offer" aria-label={`Edit offer ${offer.id}`} onClick={()=>setOfferEditor({offer,variantId:offer.variant_id})}><Pencil size={16}/></button></td></tr>;}):<tr><td colSpan={9}>No vendor offers mapped.</td></tr>}</PaginatedTableBody></table></div>
          {offerEditor?<VendorOfferEditor key={offerEditor.offer?.id||'new-offer'} product={selected} offer={offerEditor.offer} variantId={offerEditor.variantId} vendors={lookups.vendors} onSaved={saved} onClose={()=>setOfferEditor(null)}/>:null}
        </>:null}
        {tab==='stock'?<>
          <div className="inventory-summary"><div><span>Total Owned Stock</span><strong>{Number(selected.stock_qty)}</strong></div><div><span>Base Product</span><strong>{Number(selected.base_stock_qty)}</strong></div></div>
          <h3>Stock by store and variant</h3>
          <p className="ops-copy-note">Recorded balances in stores you can access, including stock reserved for online orders. Stores without a recorded balance are not listed.</p>
          <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Store / warehouse</th><th>Product / variant</th><th>On hand</th></tr></thead>
            <PaginatedTableBody>{stockRows.length
              ? stockRows.map(row=><tr key={row.key}><td>{row.store.store_name} ({row.store.store_code})</td><td>{row.name}</td><td>{Number(row.store.quantity)}</td></tr>)
              : <tr><td colSpan={3}>No recorded balances in accessible stores.</td></tr>}</PaginatedTableBody></table></div>
          <div className="inventory-actions"><button className="inventory-secondary-action" type="button" disabled={busy||storeContext.stockStores.length<2||Number(selected.stock_qty)<=0} title={storeContext.stockStores.length<2?"Add a second stock-holding store to transfer stock":Number(selected.stock_qty)<=0?"No owned stock to transfer":"Move this product's stock between stores"} onClick={()=>{setTransferProductId(selected.id);setTransferOpen(true);}}><ArrowRightLeft size={16} aria-hidden="true"/>Transfer between stores</button></div>
          <form className="ops-form" onSubmit={adjust}><fieldset disabled={busy} className="inventory-fields"><StoreSelect value={storeContext.selectedId} onChange={storeContext.setSelectedId} stores={storeContext.stockStores}/><label>Stock Item<select value={stock.variant_id} onChange={event=>setStock(previous=>({...previous,variant_id:event.target.value}))}><option value="">Base product</option>{selected.variants.filter(variant=>variant.is_active).map(variant=><option value={variant.id} key={variant.id}>{variant.variant_name}</option>)}</select></label>
            <label>Movement<select value={stock.direction} onChange={event=>setStock(previous=>({...previous,direction:event.target.value as 'IN'|'OUT'}))}><option value="IN">Stock In</option><option value="OUT">Stock Out</option></select></label><label>Quantity<input required type="number" min="0.001" step="0.001" value={stock.quantity} onChange={event=>setStock(previous=>({...previous,quantity:event.target.value}))}/></label><label>Reason<input required maxLength={1000} value={stock.notes} onChange={event=>setStock(previous=>({...previous,notes:event.target.value}))}/></label></fieldset><button className="btn" disabled={busy}><PackagePlus size={16}/>Record Stock Movement</button></form>
          <h3>Stock History</h3>{movementError?<FloatingAlert>{movementError}</FloatingAlert>:null}<div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Date</th><th>Store</th><th>Item</th><th>Movement</th><th>Quantity</th><th>Reason</th>{canDelete?<th>Actions</th>:null}</tr></thead><tbody>{movements.length?movements.map(movement=><tr key={movement.id}><td>{new Date(movement.created_at).toLocaleString()}</td><td>{storeContext.stores.find(store=>store.id===movement.store_id)?.code||''}</td><td>{movement.variant_id?selected.variants.find(variant=>variant.id===movement.variant_id)?.variant_name:'Base product'}</td><td>{movement.movement_type}</td><td>{Number(movement.quantity)}</td><td>{movement.notes}</td>{canDelete?<td>{['manual_inventory','external_document'].includes(movement.reference_type||'')?<button type="button" className="ops-link-btn" onClick={()=>setMovementDelete({kind:'stock_adjustment',id:movement.id,title:`stock ${movement.movement_type.replace(/_/g,' ').toLowerCase()} of ${Number(movement.quantity)}`})}>Delete</button>:movement.reference_type==='stock_transfer'&&movement.reference_id?<button type="button" className="ops-link-btn" onClick={()=>setMovementDelete({kind:'stock_transfer',id:movement.reference_id as string,title:'stock transfer'})}>Delete transfer</button>:null}</td>:null}</tr>):<tr><td colSpan={canDelete?7:6}>{movementLoading?'Loading stock history...':movementError?'Stock history could not be loaded.':'No stock movements on this page.'}</td></tr>}</tbody></table></div>
          <CursorPagination size={movementSize} page={movementPage} hasNext={!!movementNext} busy={movementLoading} onSize={size=>{setMovementSize(size);setMovementCursors([null]);setMovementPage(0);}} onPrevious={()=>setMovementPage(page=>page-1)} onNext={()=>{if(movementNext){setMovementCursors(previous=>[...previous.slice(0,movementPage+1),movementNext]);setMovementPage(page=>page+1);}}}/>
        </>:null}
      </section></dialog>:null}
    </section>
    {view==='alerts'?<section className="inventory-body"><p className="ops-copy-note">Alerts compare stock pooled across your accessible stores with product-level thresholds. A shortage at one location may not appear here; check individual store balances.</p><div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Product / Variant</th><th>Owned Stock</th><th>Threshold</th><th>Reorder Qty</th><th>Reminder</th><th>Next Reminder</th><th></th></tr></thead><PaginatedTableBody>{alerts.length?alerts.map(alert=>{const key=`${alert.product_id}:${alert.variant_id||''}`;return <tr key={key}><td><button className="ops-link-btn" type="button" onClick={()=>void openById(alert.product_id)}>{alert.product_name}</button><small>{alert.variant_name}</small></td><td>{Number(alert.stock_qty)}</td><td>{Number(alert.reorder_level)}</td><td>{Number(alert.reorder_quantity)}</td><td>{alert.reminder_due?'Due':alert.low_stock?'Low stock':''}{alert.reminder_date?` · ${alert.reminder_date}`:''}</td><td><input aria-label={`Reminder date ${key}`} type="date" value={reminders[key]??alert.reminder_date??''} onChange={event=>setReminders(previous=>({...previous,[key]:event.target.value}))}/></td><td><button className="ops-link-btn" type="button" title="Save reminder" aria-label={`Save reminder ${key}`} disabled={busy||!(reminders[key]||alert.reminder_date)} onClick={()=>void perform(()=>api.inventoryRemind(alert.product_id,alert.variant_id,reminders[key]||alert.reminder_date!),"Reorder reminder saved.")}><Save size={16}/></button></td></tr>;}):<tr><td colSpan={7}>No reorder alerts or reminders due.</td></tr>}</PaginatedTableBody></table></div></section>:null}
  </main>;
}
export function DraftMerge({draft,products,value,busy,onChange,onMerge}:{draft:InventoryProduct;products:InventoryProduct[];value:{target:string;variant:string};busy:boolean;onChange:(value:{target:string;variant:string})=>void;onMerge:()=>void}){
  const targets=products.filter(product=>product.id!==draft.id&&product.is_active);
  const target=targets.find(product=>product.id===value.target);
  const variants=target?target.variants.filter(variant=>variant.is_active):[];
  const ready=!!target&&(!variants.length||variants.some(variant=>variant.id===value.variant));
  return <div className="inventory-draft-merge">
    <label>Merge into existing product<select value={value.target} onChange={event=>onChange({target:event.target.value,variant:""})}>
      <option value="">Select product</option>{targets.map(product=><option key={product.id} value={product.id}>{product.name} ({product.portal_product_id}){product.is_draft?" - draft":""}</option>)}</select></label>
    {variants.length?<label>Variant receiving the stock<select value={value.variant} onChange={event=>onChange({...value,variant:event.target.value})}>
      <option value="">Select variant</option>{variants.map(variant=><option key={variant.id} value={variant.id}>{variant.variant_name}</option>)}</select></label>:null}
    {target?<p className="ops-copy-note">{Number(draft.stock_qty)} in stock, its purchase bill lines and its vendor offers move to {target.name}. Existing offers from the same vendor are kept. {draft.name} is then removed.</p>:null}
    <button className="inventory-secondary-action" type="button" disabled={busy||!ready} onClick={onMerge}>Merge draft</button>
  </div>;
}
