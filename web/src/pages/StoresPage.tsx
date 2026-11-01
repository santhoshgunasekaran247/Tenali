import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Pencil, Save, Star, X } from "lucide-react";
import { api } from "../api";
import type { Account, Store, StoreInput } from "../types";

const empty: StoreInput = {
  code: "", name: "", kind: "offline", fulfilment_store_id: null, allows_pickup: false, address: null, state_code: null, pincode: null,
  latitude: null, longitude: null, gst_number: null, whatsapp_number: null, settlement_account_id: null, is_active: true,
};
const text = (value: string | number | null | undefined) => value === null || value === undefined ? "" : String(value);
const clean = (value: string) => value.trim() === "" ? null : value.trim();

export function StoresPage() {
  const [stores, setStores] = useState<Store[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [form, setForm] = useState<StoreInput>(empty);
  const [editing, setEditing] = useState<Store | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      const [storeList, accountList] = await Promise.all([api.stores(true), api.accounts({ active_only: true })]);
      setStores(storeList.items); setAccounts(accountList.items);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to load stores."); }
  };
  useEffect(() => { void load(); }, []);
  const update = (patch: Partial<StoreInput>) => setForm(previous => ({ ...previous, ...patch }));
  const reset = () => { setEditing(null); setForm(empty); };
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const payload: StoreInput = {
        ...form, code: form.code.trim().toUpperCase(), name: form.name.trim(),
        fulfilment_store_id: form.kind === "online" ? form.fulfilment_store_id : null,
        allows_pickup: form.kind === "online" ? false : form.allows_pickup,
        address: clean(text(form.address)), state_code: clean(text(form.state_code)), pincode: clean(text(form.pincode)),
        gst_number: clean(text(form.gst_number))?.toUpperCase() ?? null, whatsapp_number: clean(text(form.whatsapp_number)),
        settlement_account_id: form.settlement_account_id || null,
        latitude: form.latitude === null || Number.isNaN(Number(form.latitude)) ? null : Number(form.latitude),
        longitude: form.longitude === null || Number.isNaN(Number(form.longitude)) ? null : Number(form.longitude),
      };
      await api.saveStore(payload, editing?.id);
      setMessage(editing ? "Store updated." : "Store created."); reset(); await load();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Store could not be saved."); }
    finally { setBusy(false); }
  };
  const makeDefault = async (store: Store) => {
    setBusy(true); setError(""); setMessage("");
    try { await api.setDefaultStore(store.id); setMessage(`${store.code} is now the default store.`); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Default could not be changed."); }
    finally { setBusy(false); }
  };
  const stockStores = stores.filter(store => store.holds_stock && store.is_active);
  return <main className="ops-page masters-page">
    <header className="masters-heading"><Link className="ops-inline-link" to="/portal">Operations Portal</Link><h1>Stores</h1>
      <p>Shops and warehouses hold stock and number their own documents (INV-CODE-…, PUR-CODE-…). The online store sells from its fulfilment warehouse; shops that allow pickup appear to shoppers as nearby stores.</p></header>
    {error ? <p role="alert" className="masters-feedback ops-error">{error}</p> : null}
    {message ? <p role="status" className="masters-feedback">{message}</p> : null}
    <section className="ops-grid">
      <article className="ops-card"><div className="ops-card-head"><h2>{editing ? `Edit ${editing.code}` : "Add store"}</h2>{editing ? <button type="button" className="ops-link-btn" aria-label="Cancel editing" onClick={reset}><X size={16} /></button> : null}</div>
        <form className="ops-form" onSubmit={save}>
          <label>Code<input required maxLength={8} pattern="[A-Za-z0-9]{2,8}" value={form.code} onChange={event => update({ code: event.target.value.toUpperCase() })} /><small>2–8 letters/digits; used in document numbers and cannot change once documents exist.</small></label>
          <label>Name<input required maxLength={120} value={form.name} onChange={event => update({ name: event.target.value })} /></label>
          <label>Kind<select value={form.kind} onChange={event => update({ kind: event.target.value as StoreInput["kind"] })} disabled={!!editing}>
            <option value="offline">Shop (offline)</option><option value="warehouse">Warehouse</option><option value="online">Online store</option></select></label>
          {form.kind === "online" ? <label>Fulfilment warehouse / shop<select required value={form.fulfilment_store_id || ""} onChange={event => update({ fulfilment_store_id: event.target.value || null })}>
            <option value="">Select</option>{stockStores.filter(store => store.id !== editing?.id).map(store => <option key={store.id} value={store.id}>{store.code} · {store.name}</option>)}</select>
            <small>Prepaid and cash-on-delivery orders are held and dispatched from here.</small></label>
            : <label className="ops-toggle"><input type="checkbox" checked={form.allows_pickup} onChange={event => update({ allows_pickup: event.target.checked })} />Shoppers may collect orders here (shown as a nearby store)</label>}
          <label>Address<textarea maxLength={1000} value={text(form.address)} onChange={event => update({ address: event.target.value })} /></label>
          <label>GST state code<input maxLength={2} pattern="[0-9]{2}" placeholder="33" value={text(form.state_code)} onChange={event => update({ state_code: event.target.value })} /><small>Used for CGST/SGST vs IGST on this store's invoices. Blank = company GSTIN state.</small></label>
          <label>Pincode<input maxLength={6} pattern="[1-9][0-9]{5}" value={text(form.pincode)} onChange={event => update({ pincode: event.target.value })} /></label>
          <div className="company-fields"><label>Latitude<input type="number" step="any" min={-90} max={90} value={text(form.latitude)} onChange={event => update({ latitude: event.target.value === "" ? null : Number(event.target.value) })} /></label>
            <label>Longitude<input type="number" step="any" min={-180} max={180} value={text(form.longitude)} onChange={event => update({ longitude: event.target.value === "" ? null : Number(event.target.value) })} /></label></div>
          <label>Store GSTIN (only if separately registered)<input maxLength={15} value={text(form.gst_number)} onChange={event => update({ gst_number: event.target.value.toUpperCase() })} /></label>
          <label>WhatsApp number override<input placeholder="+919876543210" value={text(form.whatsapp_number)} onChange={event => update({ whatsapp_number: event.target.value })} /><small>Blank = company WhatsApp number from Company Setup.</small></label>
          <label>Settlement account<select value={form.settlement_account_id || ""} onChange={event => update({ settlement_account_id: event.target.value || null })}>
            <option value="">None</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.nickname} ({account.account_type})</option>)}</select>
            <small>Online store: the Razorpay clearing account that receives captured payments. Shops: optional cash drawer.</small></label>
          <label className="ops-toggle"><input type="checkbox" checked={form.is_active} onChange={event => update({ is_active: event.target.checked })} />Active</label>
          <button className="btn" disabled={busy}><Save size={16} />{editing ? "Save store" : "Create store"}</button>
        </form></article>
      <article className="ops-card ops-list-card"><div className="ops-card-head"><h2>All stores</h2></div>
        <div className="ops-table-wrap"><table className="ops-table"><thead><tr><th>Code</th><th>Name</th><th>Kind</th><th>Pickup</th><th>Fulfils from</th><th>State</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{stores.map(store => <tr key={store.id}><td>{store.code}{store.is_default ? <Star size={14} aria-label="Default store" /> : null}</td><td>{store.name}</td><td>{store.kind}</td><td>{store.allows_pickup ? "Yes" : ""}</td>
            <td>{store.fulfilment_store_id ? stores.find(item => item.id === store.fulfilment_store_id)?.code : ""}</td><td>{store.state_code || ""}</td><td>{store.is_active ? "Active" : "Inactive"}</td>
            <td><button className="ops-link-btn" type="button" aria-label={`Edit ${store.code}`} onClick={() => { setEditing(store); setForm({ ...store }); }}><Pencil size={16} /></button>
              {!store.is_default && store.holds_stock && store.is_active ? <button className="ops-link-btn" type="button" disabled={busy} onClick={() => void makeDefault(store)}>Make default</button> : null}</td></tr>)}</tbody></table></div>
        <p className="ops-copy-note">The default store receives documents posted without a store choice. Deactivating a store requires zero stock and no online store fulfilling from it.</p>
      </article>
    </section>
  </main>;
}
