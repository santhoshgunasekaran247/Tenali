import { FormEvent, useEffect, useState } from "react";
import { Pencil, Plus, Power, Save, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { HsnMaster } from "../types";

const EMPTY = { code: "", description: "", gst_rate: "", is_active: true };

export function MasterDataPage() {
  const [items, setItems] = useState<HsnMaster[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try { setItems((await api.hsnMasters({ active_only: !showInactive })).items); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to load HSN master."); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [showInactive]);

  const clear = () => { setEditingId(null); setForm(EMPTY); };
  const edit = (item: HsnMaster) => {
    setEditingId(item.id);
    setForm({ code: item.code, description: item.description, gst_rate: String(item.gst_rate), is_active: item.is_active });
    setMessage("");
    setError("");
    document.getElementById("hsn-description")?.focus();
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const payload = { description: form.description, gst_rate: Number(form.gst_rate), is_active: form.is_active };
      if (editingId) await api.updateHsnMaster(editingId, payload);
      else await api.createHsnMaster({ ...payload, code: form.code });
      clear();
      setMessage(editingId ? "HSN / GST settings updated." : "HSN / SAC code added.");
      window.dispatchEvent(new Event("hsn-master-updated"));
      await load();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to save HSN master."); }
    finally { setSaving(false); }
  };
  const toggle = async (item: HsnMaster) => {
    if (item.is_active && !window.confirm(`Deactivate ${item.code}? Existing documents will keep their saved tax details.`)) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await api.updateHsnMaster(item.id, { description: item.description, gst_rate: Number(item.gst_rate), is_active: !item.is_active });
      if (editingId === item.id) clear();
      setMessage(item.is_active ? "HSN / SAC code deactivated." : "HSN / SAC code reactivated.");
      window.dispatchEvent(new Event("hsn-master-updated"));
      await load();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to update HSN status."); }
    finally { setSaving(false); }
  };
  const filtered = items.filter((item) => `${item.code} ${item.description}`.toLowerCase().includes(search.trim().toLowerCase()));

  return <main className="ops-page masters-page">
    <header className="masters-heading">
      <Link className="ops-inline-link" to="/portal">Portal</Link>
      <h1>Master Data</h1>
      <nav className="masters-nav" aria-label="Master modules">
        <Link to="/portal/masters/hsn" aria-current="page">HSN / GST</Link>
        <Link to="/portal/masters/brands">Brands</Link>
        <Link to="/portal/masters/categories">Categories</Link>
        <Link to="/portal/parties">Parties</Link>
        <Link to="/portal/company">Company Setup</Link>
      </nav>
    </header>
    {error ? <p className="masters-feedback ops-error" role="alert">{error}</p> : null}
    {message ? <p className="masters-feedback" role="status">{message}</p> : null}
    <section className="ops-grid">
      <article className="ops-card">
        <div className="ops-card-head">
          <h2>{editingId ? "Edit HSN / SAC" : "Add HSN / SAC"}</h2>
          {editingId ? <button className="ops-link-btn" title="Cancel editing" aria-label="Cancel editing" type="button" onClick={clear}><X size={18} aria-hidden="true" /></button> : null}
        </div>
        <form className="ops-form" onSubmit={submit}>
          <label>HSN / SAC Code<input required inputMode="numeric" pattern="(?:[0-9]{4}|[0-9]{6}|[0-9]{8})" maxLength={8}
            title="4, 6 or 8 digits" disabled={!!editingId || saving} value={form.code} onChange={(event) => setForm((previous) => ({ ...previous, code: event.target.value }))} /></label>
          <label>Description<input id="hsn-description" required maxLength={300} disabled={saving} value={form.description}
            onChange={(event) => setForm((previous) => ({ ...previous, description: event.target.value }))} /></label>
          <label>GST Rate (%)<input required type="number" min="0" max="100" step="0.01" disabled={saving} value={form.gst_rate}
            onChange={(event) => setForm((previous) => ({ ...previous, gst_rate: event.target.value }))} /></label>
          <label className="ops-toggle"><input type="checkbox" disabled={saving} checked={form.is_active}
            onChange={(event) => setForm((previous) => ({ ...previous, is_active: event.target.checked }))} />Active</label>
          <button className="btn masters-action" type="submit" disabled={saving}>
            {editingId ? <Save size={16} aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
            {saving ? "Saving..." : editingId ? "Save Changes" : "Add Code"}
          </button>
        </form>
      </article>
      <article className="ops-card ops-list-card">
        <div className="ops-card-head"><h2>HSN / GST Register</h2><span className="catalog-count">{filtered.length} codes</span></div>
        <div className="ops-list-tools">
          <input type="search" aria-label="Search HSN master" placeholder="Code or description" value={search} onChange={(event) => setSearch(event.target.value)} />
          <label className="ops-toggle"><input type="checkbox" checked={showInactive} onChange={(event) => setShowInactive(event.target.checked)} />Include inactive</label>
        </div>
        {loading ? <p role="status">Loading...</p> : null}
        <div className="ops-table-wrap"><table className="ops-table">
          <thead><tr><th>HSN / SAC</th><th>Description</th><th>GST %</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{filtered.length ? filtered.map((item) => <tr key={item.id}>
            <td>{item.code}</td><td>{item.description}</td><td>{Number(item.gst_rate).toFixed(2)}</td>
            <td><span className={`ops-status-badge ${item.is_active ? "posted" : "reversed"}`}>{item.is_active ? "Active" : "Inactive"}</span></td>
            <td>
              <button className="ops-link-btn" type="button" disabled={saving} title={`Edit ${item.code}`} aria-label={`Edit ${item.code}`} onClick={() => edit(item)}><Pencil size={16} aria-hidden="true" /></button>
              <button className="ops-link-btn" type="button" disabled={saving} title={`${item.is_active ? "Deactivate" : "Reactivate"} ${item.code}`} aria-label={`${item.is_active ? "Deactivate" : "Reactivate"} ${item.code}`} onClick={() => void toggle(item)}><Power size={16} aria-hidden="true" /></button>
            </td>
          </tr>) : <tr><td colSpan={5}>{loading ? "Loading..." : "No HSN / SAC codes found."}</td></tr>}</tbody>
        </table></div>
      </article>
    </section>
  </main>;
}